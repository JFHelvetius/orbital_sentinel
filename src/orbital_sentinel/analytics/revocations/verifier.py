"""Verifier del :class:`RevocationLedger` (ADR-0039)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone

from orbital_sentinel.analytics.revocations.builder import _format_revocation_label
from orbital_sentinel.analytics.revocations.hashing import (
    compute_revocation_id,
    compute_revocation_ledger_hash,
    compute_revocation_verification_hash,
)
from orbital_sentinel.analytics.revocations.models import (
    REVOCATION_LAYER_ENGINE_VERSION,
    REVOCATION_VERIFIER_ENGINE_VERSION,
    RevocationLedger,
    RevocationVerificationFinding,
    RevocationVerificationFindingType,
    RevocationVerificationReport,
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _f(
    ft: RevocationVerificationFindingType, affected: str, expected: str, actual: str,
) -> RevocationVerificationFinding:
    return RevocationVerificationFinding(
        finding_type=ft, affected_id=affected, expected=expected, actual=actual,
    )


def verify_revocation_ledger(
    ledger: RevocationLedger,
    *,
    clock: Callable[[], datetime] | None = None,
) -> RevocationVerificationReport:
    """Recomputa cada record y la firma global. Nunca lanza."""
    findings: list[RevocationVerificationFinding] = []
    records = list(ledger.records)

    # --- 1. Alias ledger_id == ledger_hash ----------------------------
    alias_ok = ledger.ledger_id == ledger.ledger_hash
    if not alias_ok:
        findings.append(_f(
            "ledger_id_signature_alias_violation", "ledger",
            ledger.ledger_hash, ledger.ledger_id,
        ))

    # --- 2. ledger_hash recomputa --------------------------------------
    expected_lh = compute_revocation_ledger_hash(
        revocation_ids=[r.revocation_id for r in records],
        revocation_layer_engine_version=ledger.revocation_layer_engine_version,
    )
    hash_ok = ledger.ledger_hash == expected_lh
    if not hash_ok:
        findings.append(_f(
            "ledger_hash_recompute_mismatch", "ledger",
            expected_lh, ledger.ledger_hash,
        ))

    # --- 3. n_records ---------------------------------------------------
    n_ok = ledger.n_records == len(records)
    if not n_ok:
        findings.append(_f(
            "n_records_count_mismatch", "ledger",
            str(len(records)), str(ledger.n_records),
        ))

    # --- 4. revocation_layer_engine_version ----------------------------
    eng_ok = ledger.revocation_layer_engine_version == REVOCATION_LAYER_ENGINE_VERSION
    if not eng_ok:
        findings.append(_f(
            "revocation_layer_engine_version_mismatch", "ledger",
            REVOCATION_LAYER_ENGINE_VERSION,
            ledger.revocation_layer_engine_version,
        ))

    # --- 5. Per-record --------------------------------------------------
    seen_revocation_ids: set[str] = set()
    seen_targets: set[str] = set()
    all_rec_recompute = True
    no_dup_rid = True
    no_dup_targets = True
    for r in records:
        expected = compute_revocation_id(
            target_artifact_type=r.target_artifact_type,
            target_artifact_id=r.target_artifact_id,
            target_artifact_signature=r.target_artifact_signature,
            revocation_reason=r.revocation_reason,
            superseding_artifact_id=r.superseding_artifact_id,
            supporting_evidence_ids=r.supporting_evidence_ids,
            revocation_label=r.revocation_label,
            revocation_layer_engine_version=REVOCATION_LAYER_ENGINE_VERSION,
        )
        if r.revocation_id != expected:
            all_rec_recompute = False
            findings.append(_f(
                "revocation_id_recompute_mismatch", r.revocation_id,
                expected, r.revocation_id,
            ))
        if r.revocation_id in seen_revocation_ids:
            no_dup_rid = False
            findings.append(_f(
                "duplicate_revocation_id", r.revocation_id,
                "unique", r.revocation_id,
            ))
        seen_revocation_ids.add(r.revocation_id)
        if r.target_artifact_id in seen_targets:
            no_dup_targets = False
            findings.append(_f(
                "duplicate_target_artifact_id", r.target_artifact_id,
                "unique", r.target_artifact_id,
            ))
        seen_targets.add(r.target_artifact_id)
        expected_label = _format_revocation_label(
            target_artifact_type=r.target_artifact_type,
            target_artifact_id=r.target_artifact_id,
            revocation_reason=r.revocation_reason,
        )
        if r.revocation_label != expected_label:
            findings.append(_f(
                "revocation_label_does_not_match_template", r.revocation_id,
                expected_label, r.revocation_label,
            ))
        if r.revocation_reason == "superseded_by_corrected_upstream" \
                and not r.superseding_artifact_id:
            findings.append(_f(
                "superseding_artifact_id_required_for_reason", r.revocation_id,
                "non-empty superseding_artifact_id",
                "empty",
            ))
        if r.revocation_reason == "integrity_violation_discovered" \
                and not r.supporting_evidence_ids:
            findings.append(_f(
                "supporting_evidence_required_for_reason", r.revocation_id,
                "≥1 supporting_evidence_id", "0",
            ))

    # --- 6. target_to_revocation_index --------------------------------
    expected_forward: dict[str, list[str]] = {}
    for r in records:
        expected_forward.setdefault(r.target_artifact_id, []).append(r.revocation_id)
    expected_forward_sorted = {
        k: sorted(v) for k, v in expected_forward.items()
    }
    actual_forward_sorted = {
        k: sorted(v) for k, v in ledger.target_to_revocation_index.items()
    }
    index_ok = expected_forward_sorted == actual_forward_sorted
    if not index_ok:
        findings.append(_f(
            "target_index_mismatch", "ledger",
            "matches records target→revocation_id mapping", "differs",
        ))
    keys_ok = (
        set(ledger.target_to_revocation_index.keys())
        == set(expected_forward.keys())
    )
    if not keys_ok:
        findings.append(_f(
            "target_index_key_set_mismatch", "ledger",
            "set(target_artifact_ids)", "differs",
        ))

    is_valid = (
        alias_ok and hash_ok and n_ok and eng_ok
        and all_rec_recompute and no_dup_rid and no_dup_targets
        and index_ok and keys_ok
    )

    verification_hash = compute_revocation_verification_hash(
        ledger_id=ledger.ledger_id,
        is_valid=is_valid,
        n_records_verified=len(records),
        n_findings=len(findings),
        verifier_engine_version=REVOCATION_VERIFIER_ENGINE_VERSION,
    )
    verified_at = (clock or _utc_now)()
    return RevocationVerificationReport(
        ledger_id=ledger.ledger_id,
        is_valid=is_valid,
        n_records_verified=len(records),
        n_findings=len(findings),
        ledger_id_is_alias_of_ledger_hash=alias_ok,
        ledger_hash_recomputes_correctly=hash_ok,
        all_revocation_ids_recompute_correctly=all_rec_recompute,
        no_duplicate_revocation_ids=no_dup_rid,
        no_duplicate_target_artifact_ids=no_dup_targets,
        target_index_consistent=index_ok and keys_ok,
        revocation_layer_engine_version_consistent=eng_ok,
        findings=findings,
        verification_hash=verification_hash,
        verified_at=verified_at,
    )
