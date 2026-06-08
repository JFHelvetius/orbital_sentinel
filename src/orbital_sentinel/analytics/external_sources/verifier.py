"""Verifier del :class:`ExternalSourceRegistry` (ADR-0040)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone

from orbital_sentinel.analytics.bundles import EvidenceBundle
from orbital_sentinel.analytics.external_sources.hashing import (
    compute_external_source_record_id,
    compute_external_source_registry_hash,
    compute_source_verification_hash,
)
from orbital_sentinel.analytics.external_sources.models import (
    SOURCE_LAYER_ENGINE_VERSION,
    SOURCE_VERIFIER_ENGINE_VERSION,
    ExternalSourceRegistry,
    SourceVerificationFinding,
    SourceVerificationFindingType,
    SourceVerificationReport,
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _f(
    ft: SourceVerificationFindingType, affected: str, expected: str, actual: str,
) -> SourceVerificationFinding:
    return SourceVerificationFinding(
        finding_type=ft, affected_id=affected, expected=expected, actual=actual,
    )


def verify_external_source_registry(
    registry: ExternalSourceRegistry,
    bundle: EvidenceBundle,
    *,
    clock: Callable[[], datetime] | None = None,
) -> SourceVerificationReport:
    """Recomputa registros, índices y cobertura. Nunca lanza."""
    findings: list[SourceVerificationFinding] = []
    records = list(registry.records)
    bundle_evs = {bp.evidence_id for bp in bundle.evidence_payloads}

    # --- 1. Alias -------------------------------------------------
    alias_ok = registry.registry_id == registry.registry_hash
    if not alias_ok:
        findings.append(_f(
            "registry_id_signature_alias_violation", "registry",
            registry.registry_hash, registry.registry_id,
        ))

    # --- 2. registry_hash recompute -------------------------------
    expected_rh = compute_external_source_registry_hash(
        source_bundle_id=registry.source_bundle_id,
        source_record_ids=[r.source_record_id for r in records],
        source_layer_engine_version=registry.source_layer_engine_version,
    )
    hash_ok = registry.registry_hash == expected_rh
    if not hash_ok:
        findings.append(_f(
            "registry_hash_recompute_mismatch", "registry",
            expected_rh, registry.registry_hash,
        ))

    # --- 3. n_records ---------------------------------------------
    n_ok = registry.n_records == len(records)
    if not n_ok:
        findings.append(_f(
            "n_records_count_mismatch", "registry",
            str(len(records)), str(registry.n_records),
        ))

    # --- 4. source_layer_engine_version ---------------------------
    eng_ok = registry.source_layer_engine_version == SOURCE_LAYER_ENGINE_VERSION
    if not eng_ok:
        findings.append(_f(
            "source_layer_engine_version_mismatch", "registry",
            SOURCE_LAYER_ENGINE_VERSION, registry.source_layer_engine_version,
        ))

    # --- 5. source_bundle_id matches ------------------------------
    bundle_ok = registry.source_bundle_id == bundle.bundle_id
    if not bundle_ok:
        findings.append(_f(
            "source_bundle_id_mismatch", "registry",
            bundle.bundle_id, registry.source_bundle_id,
        ))

    # --- 6. Per-record --------------------------------------------
    seen_ids: set[str] = set()
    all_rec_recompute = True
    no_dup = True
    for r in records:
        expected = compute_external_source_record_id(
            source_provider=r.source_provider,
            source_url=r.source_url,
            source_dataset_identifier=r.source_dataset_identifier,
            fetched_at=r.fetched_at,
            source_payload_hash=r.source_payload_hash,
            source_payload_size_bytes=r.source_payload_size_bytes,
            source_content_type=r.source_content_type,
            source_layer_engine_version=SOURCE_LAYER_ENGINE_VERSION,
        )
        if r.source_record_id != expected:
            all_rec_recompute = False
            findings.append(_f(
                "source_record_id_recompute_mismatch", r.source_record_id,
                expected, r.source_record_id,
            ))
        if r.source_record_id in seen_ids:
            no_dup = False
            findings.append(_f(
                "duplicate_source_record_id", r.source_record_id,
                "unique", r.source_record_id,
            ))
        seen_ids.add(r.source_record_id)
        if r.source_payload_size_bytes < 0:
            findings.append(_f(
                "source_payload_size_negative", r.source_record_id,
                ">=0", str(r.source_payload_size_bytes),
            ))

    # --- 7. Forward index ----------------------------------------
    forward_records_set = {r.source_record_id for r in records}
    fwd_keys_match = (
        set(registry.source_record_to_evidence_index.keys()) == forward_records_set
    )
    if not fwd_keys_match:
        findings.append(_f(
            "source_record_to_evidence_index_mismatch", "registry",
            "set(source_record_ids)", "differs",
        ))

    # --- 8. Reverse index ---------------------------------------
    rev_keys_match = (
        set(registry.evidence_to_source_record_index.keys()) == bundle_evs
    )
    if not rev_keys_match:
        findings.append(_f(
            "evidence_to_source_record_index_mismatch", "registry",
            "set(bundle.evidence_ids)", "differs",
        ))

    # --- 9. Coverage --------------------------------------------
    covered_evs: set[str] = set()
    for srcs in registry.evidence_to_source_record_index.values():
        for src_id in srcs:
            if src_id not in forward_records_set:
                findings.append(_f(
                    "source_record_references_unknown_evidence", src_id,
                    "present in registry.records", "absent",
                ))
    for ev in bundle_evs:
        ev_srcs = registry.evidence_to_source_record_index.get(ev, [])
        if ev_srcs:
            covered_evs.add(ev)
        else:
            findings.append(_f(
                "evidence_not_covered_by_any_source_record", ev,
                "≥1 source_record_id", "0",
            ))
    coverage_ok = covered_evs == bundle_evs

    # --- 10. Forward/reverse transpose check ----------------------
    expected_fwd: dict[str, list[str]] = {r.source_record_id: [] for r in records}
    for ev, srcs in registry.evidence_to_source_record_index.items():
        for s in srcs:
            expected_fwd.setdefault(s, []).append(ev)
    expected_fwd_sorted = {k: sorted(v) for k, v in expected_fwd.items()}
    actual_fwd_sorted = {
        k: sorted(v) for k, v in registry.source_record_to_evidence_index.items()
    }
    fwd_transpose_ok = expected_fwd_sorted == actual_fwd_sorted
    if not fwd_transpose_ok:
        findings.append(_f(
            "source_record_to_evidence_index_mismatch", "registry",
            "transpose of evidence_to_source_record_index", "differs",
        ))

    forward_index_consistent = fwd_keys_match and fwd_transpose_ok
    reverse_index_consistent = rev_keys_match

    is_valid = (
        alias_ok and hash_ok and n_ok and eng_ok and bundle_ok
        and all_rec_recompute and no_dup
        and forward_index_consistent and reverse_index_consistent
        and coverage_ok
    )

    verification_hash = compute_source_verification_hash(
        registry_id=registry.registry_id,
        is_valid=is_valid,
        n_records_verified=len(records),
        n_findings=len(findings),
        verifier_engine_version=SOURCE_VERIFIER_ENGINE_VERSION,
    )
    verified_at = (clock or _utc_now)()
    return SourceVerificationReport(
        registry_id=registry.registry_id,
        is_valid=is_valid,
        n_records_verified=len(records),
        n_findings=len(findings),
        registry_id_is_alias_of_registry_hash=alias_ok,
        registry_hash_recomputes_correctly=hash_ok,
        all_source_record_ids_recompute_correctly=all_rec_recompute,
        no_duplicate_source_record_ids=no_dup,
        forward_index_consistent=forward_index_consistent,
        reverse_index_consistent=reverse_index_consistent,
        all_evidence_ids_covered=coverage_ok,
        source_bundle_id_matches=bundle_ok,
        source_layer_engine_version_consistent=eng_ok,
        findings=findings,
        verification_hash=verification_hash,
        verified_at=verified_at,
    )
