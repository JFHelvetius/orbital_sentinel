"""Modelos del Verifiable Claim Layer v0.1 (ADR-0035).

Atomiza ``ExplanationArtifact.explanation_text`` en :class:`VerifiableClaim`
content-addressable con enlace explícito a la evidencia exacta que la
sostiene. Materializa forward y reverse indices en el propio registry.

Hard invariants enforced por model_validator:

* ``VerifiableClaim``: ``claim_id`` recompute correctamente.
* ``ClaimRegistry``: ``registry_id == registry_hash``.
"""

from __future__ import annotations

from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from orbital_sentinel.analytics.claims.hashing import (
    compute_claim_id,
    compute_registry_hash,
)

CLAIM_LAYER_SCHEMA_VERSION = "0.1.0"
"""SemVer del esquema (ADR-0010)."""

CLAIM_LAYER_ENGINE_VERSION = "0.1.0"
"""SemVer del motor de construcción (ADR-0010)."""

CLAIM_VERIFIER_ENGINE_VERSION = "0.1.0"
"""SemVer del verifier (ADR-0010)."""

SUPPORTED_SOURCE_MODELS_V01: tuple[str, ...] = ("template_explanation_v01",)
"""Lista cerrada de modelos cuyo output el builder sabe atomizar.

ADR-0035 v0.1 solo soporta el agente determinístico de plantillas (ADR-0033).
Cualquier futuro modelo requerirá enmienda explícita.
"""

RegistryEmitReason = Literal["evidence_bundle", "empty_bundle"]

ClaimVerificationFindingType = Literal[
    "claim_id_recompute_mismatch",
    "claim_without_supporting_evidence",
    "supporting_evidence_not_in_bundle",
    "duplicate_claim_index",
    "claim_index_not_sequential",
    "forward_index_mismatch",
    "reverse_index_mismatch",
    "registry_id_signature_alias_violation",
    "n_claims_count_mismatch",
    "claim_references_unknown_evidence",
    "referenced_evidence_not_covered_by_any_claim",
    "source_explanation_id_mismatch",
    "source_bundle_id_mismatch",
    "source_agent_input_id_mismatch",
    "claim_text_does_not_match_explanation_line",
    "unsupported_source_model",
    "duplicate_claim_id",
    "forward_index_key_set_mismatch",
    "reverse_index_key_set_mismatch",
]


class VerifiableClaim(BaseModel):
    """Una afirmación atómica con enlace explícito a evidencia (ADR-0035)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    claim_id: str
    source_explanation_id: str
    claim_index: int = Field(ge=0)
    supporting_evidence_ids: list[str] = Field(min_length=1)
    claim_text: str
    schema_version: str = Field(default=CLAIM_LAYER_SCHEMA_VERSION)

    @model_validator(mode="after")
    def _claim_id_must_recompute(self) -> VerifiableClaim:
        expected = compute_claim_id(
            source_explanation_id=self.source_explanation_id,
            claim_index=self.claim_index,
            supporting_evidence_ids=self.supporting_evidence_ids,
            claim_text=self.claim_text,
            claim_layer_engine_version=CLAIM_LAYER_ENGINE_VERSION,
        )
        if self.claim_id != expected:
            raise ValueError(
                "claim_id does not match recomputed hash (ADR-0035 CLAIM-001); "
                f"got {self.claim_id!r}, expected {expected!r}."
            )
        return self


class ClaimRegistry(BaseModel):
    """Registro atómico de afirmaciones derivado de una explicación.

    Hard invariant ADR-0035: ``registry_id == registry_hash``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    registry_id: str
    registry_hash: str
    source_explanation_id: str
    source_bundle_id: str
    source_agent_input_id: str
    source_model_identifier: str
    source_explanation_engine_version: str
    n_claims: int = Field(ge=0)
    claims: list[VerifiableClaim]
    claim_to_evidence_index: dict[str, list[str]]
    evidence_to_claim_index: dict[str, list[str]]
    registry_emit_reason: RegistryEmitReason
    schema_version: str = Field(default=CLAIM_LAYER_SCHEMA_VERSION)
    claim_layer_engine_version: str = Field(default=CLAIM_LAYER_ENGINE_VERSION)
    derived_at: AwareDatetime

    @model_validator(mode="after")
    def _registry_id_must_equal_registry_hash(self) -> ClaimRegistry:
        if self.registry_id != self.registry_hash:
            raise ValueError(
                "registry_id must be a strict alias of registry_hash "
                "(ADR-0035 CLAIM-008); "
                f"got registry_id={self.registry_id!r}, "
                f"registry_hash={self.registry_hash!r}."
            )
        # Defensa: registry_hash debe recomputar correctamente
        expected = compute_registry_hash(
            source_explanation_id=self.source_explanation_id,
            source_bundle_id=self.source_bundle_id,
            source_agent_input_id=self.source_agent_input_id,
            claim_ids=[c.claim_id for c in self.claims],
            claim_layer_engine_version=self.claim_layer_engine_version,
        )
        if self.registry_hash != expected:
            raise ValueError(
                "registry_hash does not match recomputed hash (ADR-0035); "
                f"got {self.registry_hash!r}, expected {expected!r}."
            )
        return self


class ClaimVerificationFinding(BaseModel):
    """Una violación de integridad reportada por :func:`verify_claim_registry`."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    finding_type: ClaimVerificationFindingType
    affected_id: str
    expected: str
    actual: str


class ClaimVerificationReport(BaseModel):
    """Reporte determinista de verificación del :class:`ClaimRegistry`.

    Nunca lanzado por el verifier; siempre retornado.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    registry_id: str
    is_valid: bool
    n_claims_verified: int = Field(ge=0)
    n_claims_with_findings: int = Field(ge=0)
    n_findings: int = Field(ge=0)

    forward_index_consistent: bool
    reverse_index_consistent: bool
    all_supporting_evidence_in_bundle: bool
    all_referenced_evidence_covered: bool
    all_claim_ids_recompute_correctly: bool
    registry_id_is_alias_of_registry_hash: bool
    all_source_ids_match: bool
    all_claim_texts_match_explanation: bool
    source_model_supported: bool

    findings: list[ClaimVerificationFinding]

    verification_hash: str
    verifier_engine_version: str = Field(default=CLAIM_VERIFIER_ENGINE_VERSION)
    schema_version: str = Field(default=CLAIM_LAYER_SCHEMA_VERSION)
    verified_at: AwareDatetime
