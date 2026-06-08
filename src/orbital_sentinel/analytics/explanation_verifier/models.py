"""Modelos del Explanation Verification Layer v0.1 (ADR-0034).

Capa determinista que valida que cada explanation referencia exclusivamente
evidencia presente en el bundle y mantiene consistencia content-addressable
con su agent_input/bundle de origen.

El verifier NUNCA muta. NUNCA lanza por integridad rota. SIEMPRE retorna
un :class:`ExplanationVerificationReport`.
"""

from __future__ import annotations

import hashlib
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

EXPLANATION_VERIFICATION_SCHEMA_VERSION = "0.1.0"
EXPLANATION_VERIFIER_ENGINE_VERSION = "0.1.0"

ExplanationFindingType = Literal[
    "evidence_id_not_in_bundle",
    "referenced_id_missing_from_audit",
    "audit_id_missing_from_referenced",
    "explanation_id_recompute_mismatch",
    "audit_explanation_id_mismatch",
    "audit_bundle_id_mismatch",
    "audit_agent_input_id_mismatch",
    "prompt_hash_mismatch_between_metadata_and_audit",
    "source_bundle_id_mismatch",
    "source_agent_input_id_mismatch",
]


class ExplanationVerificationFinding(BaseModel):
    """Una violación de integridad de la explicación. Literal cerrado."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    finding_type: ExplanationFindingType
    affected_id: str
    expected: str
    actual: str


def compute_verification_hash(
    *,
    explanation_id: str,
    bundle_id: str,
    agent_input_id: str,
    is_valid: bool,
    referenced_evidence_count: int,
    verifier_engine_version: str,
) -> str:
    """SHA-256 content-addressable del reporte (excluye verified_at)."""
    canonical = "|".join([
        explanation_id, bundle_id, agent_input_id,
        "1" if is_valid else "0",
        str(referenced_evidence_count),
        verifier_engine_version,
    ])
    return hashlib.sha256(canonical.encode("ascii")).hexdigest()


class ExplanationVerificationReport(BaseModel):
    """Reporte deterministico de verificación de una :class:`ExplanationArtifact`."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    explanation_id: str
    bundle_id: str
    agent_input_id: str

    is_valid: bool

    referenced_evidence_count: int = Field(ge=0)
    n_orphan_references: int = Field(ge=0)
    n_findings: int = Field(ge=0)

    # Checks individuales
    explanation_id_recomputes_correctly: bool
    audit_explanation_id_matches: bool
    audit_bundle_id_matches: bool
    audit_agent_input_id_matches: bool
    prompt_hash_consistent_metadata_audit: bool
    referenced_audit_ids_consistent: bool
    source_bundle_id_matches_agent_input: bool
    source_agent_input_id_matches_agent_input: bool

    findings: list[ExplanationVerificationFinding]

    verification_hash: str
    verifier_engine_version: str = Field(default=EXPLANATION_VERIFIER_ENGINE_VERSION)
    schema_version: str = Field(default=EXPLANATION_VERIFICATION_SCHEMA_VERSION)
    verified_at: AwareDatetime
