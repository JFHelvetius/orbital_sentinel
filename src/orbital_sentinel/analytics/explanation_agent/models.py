"""Modelos públicos del Explanation Agent v0.1 (ADR-0033).

El agente toma un :class:`AgentInput` verificado y produce un
:class:`ExplanationArtifact` con explicación deterministically derivada
del bundle. Sin interpretación, sin inferencia, sin clasificación.

Cada línea de ``explanation_text`` corresponde a una evidencia
referenciada en ``referenced_evidence_ids``. Toda afirmación se respalda
por una entrada en el bundle. Si no hay evidencia: no se afirma.
"""

from __future__ import annotations

import hashlib

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

EXPLANATION_AGENT_SCHEMA_VERSION = "0.1.0"
"""SemVer del esquema (ADR-0010)."""

EXPLANATION_AGENT_ENGINE_VERSION = "0.1.0"
"""SemVer del motor del agente (ADR-0010)."""

MODEL_IDENTIFIER_V01 = "template_explanation_v01"
"""Identificador del modelo subyacente.

ADR-0033 v0.1: deterministic template concatenation. No LLM, no ML, no AI.
Cualquier reemplazo por LLM en una versión futura requerirá nuevo
``model_identifier`` y nuevo ADR.
"""

GENERATION_METHOD_V01 = "deterministic_template_concatenation_v01"


def compute_explanation_id(
    *,
    source_agent_input_id: str,
    source_bundle_id: str,
    prompt_hash: str,
    explanation_engine_version: str,
) -> str:
    """SHA-256 content-addressable del artifact.

    Determinístico: mismo input + mismo prompt + misma versión → mismo
    explanation_id.
    """
    canonical = "|".join([
        source_agent_input_id,
        source_bundle_id,
        prompt_hash,
        explanation_engine_version,
    ])
    return hashlib.sha256(canonical.encode("ascii")).hexdigest()


def compute_prompt_hash(*, templates_canonical: str, engine_version: str) -> str:
    """SHA-256 sobre las plantillas + versión del motor."""
    canonical = f"{templates_canonical}|{engine_version}"
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class ExplanationGenerationMetadata(BaseModel):
    """Metadatos del proceso generativo. ADR-0033."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    model_identifier: str = Field(default=MODEL_IDENTIFIER_V01)
    generation_method: str = Field(default=GENERATION_METHOD_V01)
    prompt_hash: str
    n_evidence_processed: int = Field(ge=0)


class ExplanationAuditRecord(BaseModel):
    """Registro de auditoría de la generación. Determinístico (ADR-0033)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    explanation_id: str
    agent_input_id: str
    bundle_id: str
    evidence_ids_used: list[str]
    generation_timestamp: AwareDatetime
    prompt_hash: str
    model_identifier: str = Field(default=MODEL_IDENTIFIER_V01)


class ExplanationArtifact(BaseModel):
    """Artifact emitido por el agente explicativo (ADR-0033).

    Hard invariants:

    * Todo evidence_id en ``referenced_evidence_ids`` aparece en
      ``audit_record.evidence_ids_used``.
    * El ``explanation_id`` coincide con el computado de los campos
      content-addressable.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    explanation_id: str
    source_agent_input_id: str
    source_bundle_id: str
    referenced_evidence_ids: list[str]
    explanation_text: str
    generation_metadata: ExplanationGenerationMetadata
    audit_record: ExplanationAuditRecord
    schema_version: str = Field(default=EXPLANATION_AGENT_SCHEMA_VERSION)
    explanation_engine_version: str = Field(default=EXPLANATION_AGENT_ENGINE_VERSION)
    generated_at: AwareDatetime

    @model_validator(mode="after")
    def _references_must_match_audit_ids(self) -> ExplanationArtifact:
        if set(self.referenced_evidence_ids) != set(self.audit_record.evidence_ids_used):
            raise ValueError(
                "referenced_evidence_ids must match audit_record.evidence_ids_used "
                "(ADR-0033 invariant)."
            )
        return self

    @model_validator(mode="after")
    def _audit_explanation_id_must_match(self) -> ExplanationArtifact:
        if self.audit_record.explanation_id != self.explanation_id:
            raise ValueError(
                "audit_record.explanation_id must equal artifact.explanation_id "
                "(ADR-0033 invariant)."
            )
        return self
