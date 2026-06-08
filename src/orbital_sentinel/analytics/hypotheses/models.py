"""Modelos del Hypothesis Layer v1 (ADR-0036).

Agrupa múltiples ``VerifiableClaim`` existentes en una ``Hypothesis`` con
``hypothesis_id`` content-addressable. NO genera claims nuevos. NO genera
evidencia nueva. Sólo referencia un ``ClaimRegistry`` previamente válido.

Hard invariants enforced por model_validator:

* ``Hypothesis``: ``hypothesis_id`` recompute correctamente.
* ``HypothesisRegistry``: ``registry_id == registry_hash``.
"""

from __future__ import annotations

from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from orbital_sentinel.analytics.hypotheses.hashing import (
    compute_hypothesis_id,
    compute_hypothesis_registry_hash,
)

HYPOTHESIS_LAYER_SCHEMA_VERSION = "1.0.0"
"""SemVer del esquema (ADR-0010)."""

HYPOTHESIS_LAYER_ENGINE_VERSION = "1.0.0"
"""SemVer del motor de construcción (ADR-0010)."""

HYPOTHESIS_VERIFIER_ENGINE_VERSION = "1.0.0"
"""SemVer del verifier (ADR-0010)."""

SUPPORTED_HYPOTHESIS_MODELS_V1: tuple[str, ...] = (
    "template_hypothesis_grouping_v01",
)
"""Lista cerrada de modelos de agrupación que el builder sabe emitir.

v1.0 sólo soporta el agrupador determinístico por ``(object_id, evidence_type)``.
Cualquier futuro modelo de agrupación requerirá enmienda explícita al ADR.
"""

HypothesisRegistryEmitReason = Literal[
    "claim_registry_populated", "empty_claim_registry",
]

HypothesisVerificationFindingType = Literal[
    "hypothesis_id_recompute_mismatch",
    "hypothesis_without_supporting_claims",
    "supporting_claim_not_in_registry",
    "duplicate_hypothesis_index",
    "hypothesis_index_not_sequential",
    "forward_index_mismatch",
    "reverse_index_mismatch",
    "registry_id_signature_alias_violation",
    "n_hypotheses_count_mismatch",
    "claim_referenced_by_multiple_hypotheses",
    "claim_not_referenced_by_any_hypothesis",
    "source_claim_registry_id_mismatch",
    "source_bundle_id_mismatch",
    "source_agent_input_id_mismatch",
    "hypothesis_label_does_not_match_template",
    "unsupported_hypothesis_model",
    "duplicate_hypothesis_id",
    "forward_index_key_set_mismatch",
    "reverse_index_key_set_mismatch",
]


class Hypothesis(BaseModel):
    """Agrupación atómica de claims bajo una explicación composicional.

    No genera contenido nuevo: sólo referencia claim_ids existentes en el
    ``ClaimRegistry`` origen.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    hypothesis_id: str
    source_claim_registry_id: str
    hypothesis_index: int = Field(ge=0)
    grouping_key: str = Field(
        description="Clave determinística que llevó al agrupador a unir estos claims.",
    )
    supporting_claim_ids: list[str] = Field(min_length=1)
    hypothesis_label: str = Field(
        description="Texto descriptivo template-driven; nunca interpretativo.",
    )
    schema_version: str = Field(default=HYPOTHESIS_LAYER_SCHEMA_VERSION)

    @model_validator(mode="after")
    def _hypothesis_id_must_recompute(self) -> Hypothesis:
        expected = compute_hypothesis_id(
            source_claim_registry_id=self.source_claim_registry_id,
            hypothesis_index=self.hypothesis_index,
            grouping_key=self.grouping_key,
            supporting_claim_ids=self.supporting_claim_ids,
            hypothesis_label=self.hypothesis_label,
            hypothesis_layer_engine_version=HYPOTHESIS_LAYER_ENGINE_VERSION,
        )
        if self.hypothesis_id != expected:
            raise ValueError(
                "hypothesis_id does not match recomputed hash (ADR-0036 HYP-001); "
                f"got {self.hypothesis_id!r}, expected {expected!r}."
            )
        return self


class HypothesisRegistry(BaseModel):
    """Registro de hipótesis derivado de un :class:`ClaimRegistry` válido.

    Hard invariant ADR-0036: ``registry_id == registry_hash``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    registry_id: str
    registry_hash: str
    source_claim_registry_id: str
    source_bundle_id: str
    source_agent_input_id: str
    source_explanation_id: str
    source_model_identifier: str
    source_claim_layer_engine_version: str
    n_hypotheses: int = Field(ge=0)
    hypotheses: list[Hypothesis]
    hypothesis_to_claim_index: dict[str, list[str]]
    claim_to_hypothesis_index: dict[str, list[str]]
    registry_emit_reason: HypothesisRegistryEmitReason
    schema_version: str = Field(default=HYPOTHESIS_LAYER_SCHEMA_VERSION)
    hypothesis_layer_engine_version: str = Field(default=HYPOTHESIS_LAYER_ENGINE_VERSION)
    derived_at: AwareDatetime

    @model_validator(mode="after")
    def _registry_id_must_equal_registry_hash(self) -> HypothesisRegistry:
        if self.registry_id != self.registry_hash:
            raise ValueError(
                "registry_id must be a strict alias of registry_hash "
                "(ADR-0036 HYP-008); "
                f"got registry_id={self.registry_id!r}, "
                f"registry_hash={self.registry_hash!r}."
            )
        expected = compute_hypothesis_registry_hash(
            source_claim_registry_id=self.source_claim_registry_id,
            source_bundle_id=self.source_bundle_id,
            source_agent_input_id=self.source_agent_input_id,
            hypothesis_ids=[h.hypothesis_id for h in self.hypotheses],
            hypothesis_layer_engine_version=self.hypothesis_layer_engine_version,
        )
        if self.registry_hash != expected:
            raise ValueError(
                "registry_hash does not match recomputed hash (ADR-0036); "
                f"got {self.registry_hash!r}, expected {expected!r}."
            )
        return self


class HypothesisVerificationFinding(BaseModel):
    """Una violación reportada por :func:`verify_hypothesis_registry`."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    finding_type: HypothesisVerificationFindingType
    affected_id: str
    expected: str
    actual: str


class HypothesisVerificationReport(BaseModel):
    """Reporte determinista del verifier del Hypothesis Layer."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    registry_id: str
    is_valid: bool
    n_hypotheses_verified: int = Field(ge=0)
    n_hypotheses_with_findings: int = Field(ge=0)
    n_findings: int = Field(ge=0)

    forward_index_consistent: bool
    reverse_index_consistent: bool
    all_supporting_claims_in_registry: bool
    all_claims_covered_by_some_hypothesis: bool
    all_hypothesis_ids_recompute_correctly: bool
    registry_id_is_alias_of_registry_hash: bool
    all_source_ids_match: bool
    source_model_supported: bool

    findings: list[HypothesisVerificationFinding]

    verification_hash: str
    verifier_engine_version: str = Field(default=HYPOTHESIS_VERIFIER_ENGINE_VERSION)
    schema_version: str = Field(default=HYPOTHESIS_LAYER_SCHEMA_VERSION)
    verified_at: AwareDatetime
