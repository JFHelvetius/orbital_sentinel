"""Builder del Revocation Layer (ADR-0039).

Funciones puras. Componen revocation records y ledgers content-addressable.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import datetime, timezone

from orbital_sentinel.analytics.revocations.hashing import (
    compute_revocation_id,
    compute_revocation_ledger_hash,
)
from orbital_sentinel.analytics.revocations.models import (
    REVOCATION_LAYER_ENGINE_VERSION,
    LedgerEmitReason,
    RevocationLedger,
    RevocationReason,
    RevocationRecord,
    RevocationTargetType,
)
from orbital_sentinel.core.errors import RevocationLedgerBuilderError


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _format_revocation_label(
    *,
    target_artifact_type: str,
    target_artifact_id: str,
    revocation_reason: str,
) -> str:
    """Template determinístico v1. Nunca interpretativo."""
    return (
        f"{target_artifact_type} {target_artifact_id} "
        f"revoked: reason={revocation_reason}."
    )


def build_revocation_record(
    *,
    target_artifact_type: RevocationTargetType,
    target_artifact_id: str,
    target_artifact_signature: str,
    revocation_reason: RevocationReason,
    superseding_artifact_id: str = "",
    supporting_evidence_ids: Iterable[str] | None = None,
    clock: Callable[[], datetime] | None = None,
) -> RevocationRecord:
    """Construye un :class:`RevocationRecord` content-addressable."""
    supporting = sorted(supporting_evidence_ids or [])
    label = _format_revocation_label(
        target_artifact_type=target_artifact_type,
        target_artifact_id=target_artifact_id,
        revocation_reason=revocation_reason,
    )
    rid = compute_revocation_id(
        target_artifact_type=target_artifact_type,
        target_artifact_id=target_artifact_id,
        target_artifact_signature=target_artifact_signature,
        revocation_reason=revocation_reason,
        superseding_artifact_id=superseding_artifact_id,
        supporting_evidence_ids=supporting,
        revocation_label=label,
        revocation_layer_engine_version=REVOCATION_LAYER_ENGINE_VERSION,
    )
    emitted_at = (clock or _utc_now)()
    return RevocationRecord(
        revocation_id=rid,
        target_artifact_type=target_artifact_type,
        target_artifact_id=target_artifact_id,
        target_artifact_signature=target_artifact_signature,
        revocation_reason=revocation_reason,
        superseding_artifact_id=superseding_artifact_id,
        supporting_evidence_ids=supporting,
        revocation_label=label,
        emitted_at=emitted_at,
    )


def build_revocation_ledger(
    records: Iterable[RevocationRecord],
    *,
    clock: Callable[[], datetime] | None = None,
) -> RevocationLedger:
    """Construye un :class:`RevocationLedger` content-addressable.

    Raises:
        RevocationLedgerBuilderError: si hay duplicados por
            ``target_artifact_id`` (una revocación por target en el mismo
            ledger; cualquier corrección debe emitirse en un ledger
            nuevo con record nuevo).
    """
    records_list = list(records)
    seen_targets: set[str] = set()
    for r in records_list:
        if r.target_artifact_id in seen_targets:
            raise RevocationLedgerBuilderError(
                "Duplicate target_artifact_id in ledger: "
                f"{r.target_artifact_id[:12]}…. "
                "v1 prohibits multiple revocations of the same target in a "
                "single ledger.",
            )
        seen_targets.add(r.target_artifact_id)

    forward: dict[str, list[str]] = {}
    for r in records_list:
        forward.setdefault(r.target_artifact_id, []).append(r.revocation_id)
    forward_ordered: dict[str, list[str]] = {
        k: sorted(forward[k]) for k in sorted(forward.keys())
    }

    emit_reason: LedgerEmitReason = (
        "empty_ledger" if not records_list else "records_present"
    )
    ledger_hash = compute_revocation_ledger_hash(
        revocation_ids=[r.revocation_id for r in records_list],
        revocation_layer_engine_version=REVOCATION_LAYER_ENGINE_VERSION,
    )
    derived_at = (clock or _utc_now)()
    return RevocationLedger(
        ledger_id=ledger_hash,
        ledger_hash=ledger_hash,
        records=records_list,
        n_records=len(records_list),
        target_to_revocation_index=forward_ordered,
        ledger_emit_reason=emit_reason,
        derived_at=derived_at,
    )


def is_artifact_revoked(
    ledger: RevocationLedger, *, artifact_id: str,
) -> RevocationRecord | None:
    """Retorna el :class:`RevocationRecord` que revoca ``artifact_id``, o ``None``.

    Función pura. No usa el verifier — asume que el ledger fue verificado
    por separado.
    """
    for r in ledger.records:
        if r.target_artifact_id == artifact_id:
            return r
    return None
