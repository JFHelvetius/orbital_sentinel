"""Modelos del Dissent Layer v1 (ADR-0041).

Protocolo content-addressable para registrar **disensión** sobre un
:class:`InvestigationCase` previamente emitido. Cualquier tercero puede
publicar un :class:`DissentLedger` apuntando a un case_id objetivo y
declarando:

* qué tipo de objeción se eleva (cinco categorías cerradas);
* qué evidencia adicional la sustenta (opcional);
* qué caso alternativo se propone (opcional).

El layer NO juzga la disensión. NO la valida contra el caso target. Sólo
prueba que la disensión existe y es content-addressable. La verificabilidad
de la disensión en sí misma es separable de su mérito.

Hard invariants enforced por model_validator:

* ``DissentRecord``: ``dissent_id`` recompute correctamente.
* ``DissentLedger``: ``ledger_id == ledger_hash``.
"""

from __future__ import annotations

from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from orbital_sentinel.analytics.dissent.hashing import (
    compute_dissent_id,
    compute_dissent_ledger_hash,
)

DISSENT_LAYER_SCHEMA_VERSION = "1.0.0"
DISSENT_LAYER_ENGINE_VERSION = "1.0.0"
DISSENT_VERIFIER_ENGINE_VERSION = "1.0.0"

DissentType = Literal[
    "factual_correction",
    "alternative_explanation",
    "missing_evidence",
    "methodological_objection",
    "scope_disagreement",
]

DissentLedgerEmitReason = Literal["records_present", "empty_ledger"]

DissentVerificationFindingType = Literal[
    "dissent_id_recompute_mismatch",
    "duplicate_dissent_id",
    "duplicate_dissent_index",
    "dissent_index_not_sequential",
    "ledger_id_signature_alias_violation",
    "ledger_hash_recompute_mismatch",
    "n_records_count_mismatch",
    "target_case_id_inconsistent_across_records",
    "target_case_signature_inconsistent_across_records",
    "dissent_type_index_mismatch",
    "dissent_type_index_key_set_mismatch",
    "dissent_label_does_not_match_template",
    "missing_evidence_requires_basis_evidence",
    "factual_correction_requires_basis_evidence",
    "alternative_explanation_requires_referenced_case",
    "dissent_layer_engine_version_mismatch",
]


class DissentRecord(BaseModel):
    """Una objeción atómica firmada sobre un :class:`InvestigationCase`."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    dissent_id: str
    target_case_id: str
    target_case_signature: str = Field(
        description=(
            "Firma content-addressable del caso target al momento de la "
            "disensión. Permite saber sobre qué versión del caso se objeta."
        ),
    )
    dissent_index: int = Field(ge=0)
    dissent_type: DissentType
    dissent_basis_evidence_ids: list[str] = Field(
        default_factory=list,
        description=(
            "evidence_ids que sustentan la disensión. Obligatorio para "
            "'factual_correction' y 'missing_evidence'."
        ),
    )
    referenced_alternative_case_id: str = Field(
        default="",
        description=(
            "case_id de un :class:`InvestigationCase` alternativo. "
            "Obligatorio para 'alternative_explanation'."
        ),
    )
    dissent_label: str = Field(
        description="Texto descriptivo template-driven; nunca interpretativo.",
    )
    emitted_at: AwareDatetime
    schema_version: str = Field(default=DISSENT_LAYER_SCHEMA_VERSION)

    @model_validator(mode="after")
    def _dissent_id_must_recompute(self) -> DissentRecord:
        expected = compute_dissent_id(
            target_case_id=self.target_case_id,
            target_case_signature=self.target_case_signature,
            dissent_index=self.dissent_index,
            dissent_type=self.dissent_type,
            dissent_basis_evidence_ids=self.dissent_basis_evidence_ids,
            referenced_alternative_case_id=self.referenced_alternative_case_id,
            dissent_label=self.dissent_label,
            dissent_layer_engine_version=DISSENT_LAYER_ENGINE_VERSION,
        )
        if self.dissent_id != expected:
            raise ValueError(
                "dissent_id does not match recomputed hash (ADR-0041 DIS-001); "
                f"got {self.dissent_id!r}, expected {expected!r}."
            )
        return self


class DissentLedger(BaseModel):
    """Registro de disensiones sobre un caso target.

    Hard invariant ADR-0041: ``ledger_id == ledger_hash``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    ledger_id: str
    ledger_hash: str
    target_case_id: str
    target_case_signature: str
    records: list[DissentRecord]
    n_records: int = Field(ge=0)
    dissent_type_index: dict[str, list[str]] = Field(
        description="Forward index: dissent_type → [dissent_id, …].",
    )
    ledger_emit_reason: DissentLedgerEmitReason
    schema_version: str = Field(default=DISSENT_LAYER_SCHEMA_VERSION)
    dissent_layer_engine_version: str = Field(default=DISSENT_LAYER_ENGINE_VERSION)
    derived_at: AwareDatetime

    @model_validator(mode="after")
    def _ledger_id_must_equal_hash(self) -> DissentLedger:
        if self.ledger_id != self.ledger_hash:
            raise ValueError(
                "ledger_id must be a strict alias of ledger_hash "
                "(ADR-0041 DIS-008); "
                f"got ledger_id={self.ledger_id!r}, "
                f"ledger_hash={self.ledger_hash!r}."
            )
        expected = compute_dissent_ledger_hash(
            target_case_id=self.target_case_id,
            target_case_signature=self.target_case_signature,
            dissent_ids=[r.dissent_id for r in self.records],
            dissent_layer_engine_version=self.dissent_layer_engine_version,
        )
        if self.ledger_hash != expected:
            raise ValueError(
                "ledger_hash does not match recomputed hash (ADR-0041); "
                f"got {self.ledger_hash!r}, expected {expected!r}.",
            )
        return self


class DissentVerificationFinding(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    finding_type: DissentVerificationFindingType
    affected_id: str
    expected: str
    actual: str


class DissentVerificationReport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    ledger_id: str
    is_valid: bool
    n_records_verified: int = Field(ge=0)
    n_findings: int = Field(ge=0)

    ledger_id_is_alias_of_ledger_hash: bool
    ledger_hash_recomputes_correctly: bool
    all_dissent_ids_recompute_correctly: bool
    no_duplicate_dissent_ids: bool
    dissent_indices_sequential: bool
    target_case_consistent_across_records: bool
    dissent_type_index_consistent: bool
    all_required_fields_present_for_type: bool
    dissent_layer_engine_version_consistent: bool

    findings: list[DissentVerificationFinding]

    verification_hash: str
    verifier_engine_version: str = Field(default=DISSENT_VERIFIER_ENGINE_VERSION)
    schema_version: str = Field(default=DISSENT_LAYER_SCHEMA_VERSION)
    verified_at: AwareDatetime
