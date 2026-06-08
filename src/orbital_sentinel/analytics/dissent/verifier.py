"""Verifier del :class:`DissentLedger` (ADR-0041)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone

from orbital_sentinel.analytics.dissent.builder import _format_dissent_label
from orbital_sentinel.analytics.dissent.hashing import (
    compute_dissent_id,
    compute_dissent_ledger_hash,
    compute_dissent_verification_hash,
)
from orbital_sentinel.analytics.dissent.models import (
    DISSENT_LAYER_ENGINE_VERSION,
    DISSENT_VERIFIER_ENGINE_VERSION,
    DissentLedger,
    DissentVerificationFinding,
    DissentVerificationFindingType,
    DissentVerificationReport,
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _f(
    ft: DissentVerificationFindingType, affected: str, expected: str, actual: str,
) -> DissentVerificationFinding:
    return DissentVerificationFinding(
        finding_type=ft, affected_id=affected, expected=expected, actual=actual,
    )


def verify_dissent_ledger(
    ledger: DissentLedger,
    *,
    clock: Callable[[], datetime] | None = None,
) -> DissentVerificationReport:
    """Recomputa cada record y la firma global. Nunca lanza."""
    findings: list[DissentVerificationFinding] = []
    records = list(ledger.records)

    # --- 1. Alias -------------------------------------------------
    alias_ok = ledger.ledger_id == ledger.ledger_hash
    if not alias_ok:
        findings.append(_f(
            "ledger_id_signature_alias_violation", "ledger",
            ledger.ledger_hash, ledger.ledger_id,
        ))

    # --- 2. ledger_hash recompute --------------------------------
    expected_lh = compute_dissent_ledger_hash(
        target_case_id=ledger.target_case_id,
        target_case_signature=ledger.target_case_signature,
        dissent_ids=[r.dissent_id for r in records],
        dissent_layer_engine_version=ledger.dissent_layer_engine_version,
    )
    hash_ok = ledger.ledger_hash == expected_lh
    if not hash_ok:
        findings.append(_f(
            "ledger_hash_recompute_mismatch", "ledger",
            expected_lh, ledger.ledger_hash,
        ))

    # --- 3. n_records ---------------------------------------------
    n_ok = ledger.n_records == len(records)
    if not n_ok:
        findings.append(_f(
            "n_records_count_mismatch", "ledger",
            str(len(records)), str(ledger.n_records),
        ))

    # --- 4. engine version ---------------------------------------
    eng_ok = ledger.dissent_layer_engine_version == DISSENT_LAYER_ENGINE_VERSION
    if not eng_ok:
        findings.append(_f(
            "dissent_layer_engine_version_mismatch", "ledger",
            DISSENT_LAYER_ENGINE_VERSION, ledger.dissent_layer_engine_version,
        ))

    # --- 5. Per-record --------------------------------------------
    seen_dids: set[str] = set()
    seen_indices: set[int] = set()
    all_rec_recompute = True
    no_dup_dids = True
    no_dup_idx = True
    target_consistent = True
    required_ok = True
    for r in records:
        expected = compute_dissent_id(
            target_case_id=r.target_case_id,
            target_case_signature=r.target_case_signature,
            dissent_index=r.dissent_index,
            dissent_type=r.dissent_type,
            dissent_basis_evidence_ids=r.dissent_basis_evidence_ids,
            referenced_alternative_case_id=r.referenced_alternative_case_id,
            dissent_label=r.dissent_label,
            dissent_layer_engine_version=DISSENT_LAYER_ENGINE_VERSION,
        )
        if r.dissent_id != expected:
            all_rec_recompute = False
            findings.append(_f(
                "dissent_id_recompute_mismatch", r.dissent_id,
                expected, r.dissent_id,
            ))
        if r.dissent_id in seen_dids:
            no_dup_dids = False
            findings.append(_f(
                "duplicate_dissent_id", r.dissent_id,
                "unique", r.dissent_id,
            ))
        seen_dids.add(r.dissent_id)
        if r.dissent_index in seen_indices:
            no_dup_idx = False
            findings.append(_f(
                "duplicate_dissent_index", r.dissent_id,
                "unique", str(r.dissent_index),
            ))
        seen_indices.add(r.dissent_index)
        if r.target_case_id != ledger.target_case_id:
            target_consistent = False
            findings.append(_f(
                "target_case_id_inconsistent_across_records", r.dissent_id,
                ledger.target_case_id, r.target_case_id,
            ))
        if r.target_case_signature != ledger.target_case_signature:
            target_consistent = False
            findings.append(_f(
                "target_case_signature_inconsistent_across_records", r.dissent_id,
                ledger.target_case_signature, r.target_case_signature,
            ))
        # Label template check
        expected_label = _format_dissent_label(
            target_case_id=r.target_case_id,
            dissent_type=r.dissent_type,
            dissent_index=r.dissent_index,
        )
        if r.dissent_label != expected_label:
            findings.append(_f(
                "dissent_label_does_not_match_template", r.dissent_id,
                expected_label, r.dissent_label,
            ))
        # Required field rules
        if r.dissent_type == "factual_correction" \
                and not r.dissent_basis_evidence_ids:
            required_ok = False
            findings.append(_f(
                "factual_correction_requires_basis_evidence", r.dissent_id,
                "≥1 dissent_basis_evidence_id", "0",
            ))
        if r.dissent_type == "missing_evidence" \
                and not r.dissent_basis_evidence_ids:
            required_ok = False
            findings.append(_f(
                "missing_evidence_requires_basis_evidence", r.dissent_id,
                "≥1 dissent_basis_evidence_id", "0",
            ))
        if r.dissent_type == "alternative_explanation" \
                and not r.referenced_alternative_case_id:
            required_ok = False
            findings.append(_f(
                "alternative_explanation_requires_referenced_case", r.dissent_id,
                "non-empty referenced_alternative_case_id", "empty",
            ))

    # --- 6. dissent_index sequential ------------------------------
    expected_indices = set(range(len(records)))
    indices_ok = seen_indices == expected_indices
    if records and not indices_ok:
        findings.append(_f(
            "dissent_index_not_sequential", "ledger",
            f"{{0..{len(records) - 1}}}",
            ",".join(str(i) for i in sorted(seen_indices)),
        ))

    # --- 7. dissent_type_index ------------------------------------
    expected_idx: dict[str, list[str]] = {}
    for r in records:
        expected_idx.setdefault(r.dissent_type, []).append(r.dissent_id)
    expected_idx_sorted = {k: sorted(v) for k, v in expected_idx.items()}
    actual_idx_sorted = {
        k: sorted(v) for k, v in ledger.dissent_type_index.items()
    }
    type_index_ok = expected_idx_sorted == actual_idx_sorted
    if not type_index_ok:
        findings.append(_f(
            "dissent_type_index_mismatch", "ledger",
            "matches records dissent_type→ids", "differs",
        ))
    type_keys_ok = (
        set(ledger.dissent_type_index.keys()) == set(expected_idx.keys())
    )
    if not type_keys_ok:
        findings.append(_f(
            "dissent_type_index_key_set_mismatch", "ledger",
            "set(dissent_types present)", "differs",
        ))

    is_valid = (
        alias_ok and hash_ok and n_ok and eng_ok
        and all_rec_recompute and no_dup_dids and no_dup_idx
        and target_consistent and required_ok
        and indices_ok and type_index_ok and type_keys_ok
    )

    verification_hash = compute_dissent_verification_hash(
        ledger_id=ledger.ledger_id,
        is_valid=is_valid,
        n_records_verified=len(records),
        n_findings=len(findings),
        verifier_engine_version=DISSENT_VERIFIER_ENGINE_VERSION,
    )
    verified_at = (clock or _utc_now)()
    return DissentVerificationReport(
        ledger_id=ledger.ledger_id,
        is_valid=is_valid,
        n_records_verified=len(records),
        n_findings=len(findings),
        ledger_id_is_alias_of_ledger_hash=alias_ok,
        ledger_hash_recomputes_correctly=hash_ok,
        all_dissent_ids_recompute_correctly=all_rec_recompute,
        no_duplicate_dissent_ids=no_dup_dids,
        dissent_indices_sequential=indices_ok,
        target_case_consistent_across_records=target_consistent,
        dissent_type_index_consistent=type_index_ok and type_keys_ok,
        all_required_fields_present_for_type=required_ok,
        dissent_layer_engine_version_consistent=eng_ok,
        findings=findings,
        verification_hash=verification_hash,
        verified_at=verified_at,
    )
