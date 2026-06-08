"""Builder del Dissent Layer (ADR-0041)."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import datetime, timezone

from orbital_sentinel.analytics.dissent.hashing import (
    compute_dissent_id,
    compute_dissent_ledger_hash,
)
from orbital_sentinel.analytics.dissent.models import (
    DISSENT_LAYER_ENGINE_VERSION,
    DissentLedger,
    DissentLedgerEmitReason,
    DissentRecord,
    DissentType,
)
from orbital_sentinel.core.errors import DissentLedgerBuilderError


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _format_dissent_label(
    *, target_case_id: str, dissent_type: str, dissent_index: int,
) -> str:
    """Template determinístico v1."""
    return (
        f"Dissent #{dissent_index} on case {target_case_id}: "
        f"type={dissent_type}."
    )


def build_dissent_record(
    *,
    target_case_id: str,
    target_case_signature: str,
    dissent_index: int,
    dissent_type: DissentType,
    dissent_basis_evidence_ids: Iterable[str] | None = None,
    referenced_alternative_case_id: str = "",
    clock: Callable[[], datetime] | None = None,
) -> DissentRecord:
    """Construye un :class:`DissentRecord` content-addressable."""
    basis = sorted(dissent_basis_evidence_ids or [])
    label = _format_dissent_label(
        target_case_id=target_case_id,
        dissent_type=dissent_type,
        dissent_index=dissent_index,
    )
    did = compute_dissent_id(
        target_case_id=target_case_id,
        target_case_signature=target_case_signature,
        dissent_index=dissent_index,
        dissent_type=dissent_type,
        dissent_basis_evidence_ids=basis,
        referenced_alternative_case_id=referenced_alternative_case_id,
        dissent_label=label,
        dissent_layer_engine_version=DISSENT_LAYER_ENGINE_VERSION,
    )
    emitted_at = (clock or _utc_now)()
    return DissentRecord(
        dissent_id=did,
        target_case_id=target_case_id,
        target_case_signature=target_case_signature,
        dissent_index=dissent_index,
        dissent_type=dissent_type,
        dissent_basis_evidence_ids=basis,
        referenced_alternative_case_id=referenced_alternative_case_id,
        dissent_label=label,
        emitted_at=emitted_at,
    )


def build_dissent_ledger(
    *,
    target_case_id: str,
    target_case_signature: str,
    records: Iterable[DissentRecord],
    clock: Callable[[], datetime] | None = None,
) -> DissentLedger:
    """Construye un :class:`DissentLedger` content-addressable.

    Raises:
        DissentLedgerBuilderError: si algún record no apunta al mismo
            ``(target_case_id, target_case_signature)``, o si los índices
            no son secuenciales 0..N-1.
    """
    records_list = list(records)
    for r in records_list:
        if r.target_case_id != target_case_id:
            raise DissentLedgerBuilderError(
                f"Record {r.dissent_id[:12]}… targets a different case "
                f"({r.target_case_id[:12]}…) than ledger ({target_case_id[:12]}…).",
            )
        if r.target_case_signature != target_case_signature:
            raise DissentLedgerBuilderError(
                f"Record {r.dissent_id[:12]}… target_case_signature differs "
                "from ledger.",
            )
    expected_indices = set(range(len(records_list)))
    actual_indices = {r.dissent_index for r in records_list}
    if records_list and actual_indices != expected_indices:
        raise DissentLedgerBuilderError(
            f"Dissent indices must be sequential 0..{len(records_list) - 1}; "
            f"got {sorted(actual_indices)}.",
        )

    type_index: dict[str, list[str]] = {}
    for r in records_list:
        type_index.setdefault(r.dissent_type, []).append(r.dissent_id)
    type_index_ordered = {
        k: sorted(type_index[k]) for k in sorted(type_index.keys())
    }

    emit_reason: DissentLedgerEmitReason = (
        "empty_ledger" if not records_list else "records_present"
    )
    ledger_hash = compute_dissent_ledger_hash(
        target_case_id=target_case_id,
        target_case_signature=target_case_signature,
        dissent_ids=[r.dissent_id for r in records_list],
        dissent_layer_engine_version=DISSENT_LAYER_ENGINE_VERSION,
    )
    derived_at = (clock or _utc_now)()
    return DissentLedger(
        ledger_id=ledger_hash,
        ledger_hash=ledger_hash,
        target_case_id=target_case_id,
        target_case_signature=target_case_signature,
        records=records_list,
        n_records=len(records_list),
        dissent_type_index=type_index_ordered,
        ledger_emit_reason=emit_reason,
        derived_at=derived_at,
    )
