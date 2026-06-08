"""Modelos del Revocation Layer v1 (ADR-0039).

Permite marcar artefactos previamente emitidos (cualquier capa ADR-0031 a
ADR-0038) como **revocados** preservando su trazabilidad content-addressable.

Una revocación NO modifica el artefacto target. NO lo borra. NO requiere
acceso a su payload. Sólo emite un :class:`RevocationRecord` content-
addressable que cualquier consumidor offline puede consultar antes de
aceptar el artefacto como vigente.

Hard invariants enforced por model_validator:

* ``RevocationRecord``: ``revocation_id`` recompute correctamente.
* ``RevocationLedger``: ``ledger_id == ledger_hash``.
"""

from __future__ import annotations

from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from orbital_sentinel.analytics.revocations.hashing import (
    compute_revocation_id,
    compute_revocation_ledger_hash,
)

REVOCATION_LAYER_SCHEMA_VERSION = "1.0.0"
REVOCATION_LAYER_ENGINE_VERSION = "1.0.0"
REVOCATION_VERIFIER_ENGINE_VERSION = "1.0.0"

RevocationTargetType = Literal[
    "evidence_bundle",
    "agent_input",
    "explanation_artifact",
    "claim_registry",
    "hypothesis_registry",
    "evidence_chain",
    "investigation_case",
]

RevocationReason = Literal[
    "superseded_by_corrected_upstream",
    "retracted_by_emitter",
    "integrity_violation_discovered",
    "schema_obsolete",
    "voluntary_withdrawal",
]

LedgerEmitReason = Literal["records_present", "empty_ledger"]

RevocationVerificationFindingType = Literal[
    "revocation_id_recompute_mismatch",
    "duplicate_revocation_id",
    "duplicate_target_artifact_id",
    "ledger_id_signature_alias_violation",
    "ledger_hash_recompute_mismatch",
    "n_records_count_mismatch",
    "target_index_mismatch",
    "target_index_key_set_mismatch",
    "unsupported_target_artifact_type",
    "unsupported_revocation_reason",
    "revocation_label_does_not_match_template",
    "superseding_artifact_id_required_for_reason",
    "supporting_evidence_required_for_reason",
    "revocation_layer_engine_version_mismatch",
]


class RevocationRecord(BaseModel):
    """Una revocación atómica de un artefacto previamente emitido."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    revocation_id: str
    target_artifact_type: RevocationTargetType
    target_artifact_id: str
    target_artifact_signature: str = Field(
        description=(
            "Firma content-addressable del artefacto target al momento de la "
            "revocación. Permite detectar que se quiso revocar 'la versión X' "
            "y no una mutación posterior."
        ),
    )
    revocation_reason: RevocationReason
    superseding_artifact_id: str = Field(
        default="",
        description=(
            "ID content-addressable del artefacto que sustituye al revocado. "
            "Vacío si no aplica (e.g., voluntary_withdrawal sin reemplazo)."
        ),
    )
    supporting_evidence_ids: list[str] = Field(
        default_factory=list,
        description=(
            "evidence_ids que justifican la revocación (e.g., evidencia de "
            "corrección upstream). Puede estar vacío para retract puro."
        ),
    )
    revocation_label: str = Field(
        description="Texto descriptivo template-driven; nunca interpretativo.",
    )
    emitted_at: AwareDatetime
    schema_version: str = Field(default=REVOCATION_LAYER_SCHEMA_VERSION)

    @model_validator(mode="after")
    def _revocation_id_must_recompute(self) -> RevocationRecord:
        expected = compute_revocation_id(
            target_artifact_type=self.target_artifact_type,
            target_artifact_id=self.target_artifact_id,
            target_artifact_signature=self.target_artifact_signature,
            revocation_reason=self.revocation_reason,
            superseding_artifact_id=self.superseding_artifact_id,
            supporting_evidence_ids=self.supporting_evidence_ids,
            revocation_label=self.revocation_label,
            revocation_layer_engine_version=REVOCATION_LAYER_ENGINE_VERSION,
        )
        if self.revocation_id != expected:
            raise ValueError(
                "revocation_id does not match recomputed hash (ADR-0039 REV-001); "
                f"got {self.revocation_id!r}, expected {expected!r}."
            )
        return self


class RevocationLedger(BaseModel):
    """Registro acumulativo de revocaciones.

    Hard invariant ADR-0039: ``ledger_id == ledger_hash``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    ledger_id: str
    ledger_hash: str
    records: list[RevocationRecord]
    n_records: int = Field(ge=0)
    target_to_revocation_index: dict[str, list[str]] = Field(
        description="Forward index: target_artifact_id → [revocation_id, …].",
    )
    ledger_emit_reason: LedgerEmitReason
    schema_version: str = Field(default=REVOCATION_LAYER_SCHEMA_VERSION)
    revocation_layer_engine_version: str = Field(
        default=REVOCATION_LAYER_ENGINE_VERSION,
    )
    derived_at: AwareDatetime

    @model_validator(mode="after")
    def _ledger_id_must_equal_hash(self) -> RevocationLedger:
        if self.ledger_id != self.ledger_hash:
            raise ValueError(
                "ledger_id must be a strict alias of ledger_hash "
                "(ADR-0039 REV-008); "
                f"got ledger_id={self.ledger_id!r}, "
                f"ledger_hash={self.ledger_hash!r}."
            )
        expected = compute_revocation_ledger_hash(
            revocation_ids=[r.revocation_id for r in self.records],
            revocation_layer_engine_version=self.revocation_layer_engine_version,
        )
        if self.ledger_hash != expected:
            raise ValueError(
                "ledger_hash does not match recomputed hash (ADR-0039); "
                f"got {self.ledger_hash!r}, expected {expected!r}.",
            )
        return self


class RevocationVerificationFinding(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    finding_type: RevocationVerificationFindingType
    affected_id: str
    expected: str
    actual: str


class RevocationVerificationReport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    ledger_id: str
    is_valid: bool
    n_records_verified: int = Field(ge=0)
    n_findings: int = Field(ge=0)

    ledger_id_is_alias_of_ledger_hash: bool
    ledger_hash_recomputes_correctly: bool
    all_revocation_ids_recompute_correctly: bool
    no_duplicate_revocation_ids: bool
    no_duplicate_target_artifact_ids: bool
    target_index_consistent: bool
    revocation_layer_engine_version_consistent: bool

    findings: list[RevocationVerificationFinding]

    verification_hash: str
    verifier_engine_version: str = Field(default=REVOCATION_VERIFIER_ENGINE_VERSION)
    schema_version: str = Field(default=REVOCATION_LAYER_SCHEMA_VERSION)
    verified_at: AwareDatetime
