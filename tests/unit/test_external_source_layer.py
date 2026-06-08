"""Tests del External Source Provenance Layer (ADR-0040)."""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

import pytest

from orbital_sentinel.analytics.bundles import build_evidence_bundle
from orbital_sentinel.analytics.evidence import (
    EVIDENCE_TYPE_MANEUVER,
    DerivedEvidence,
    EvidenceCatalog,
    compute_evidence_id,
)
from orbital_sentinel.analytics.explanation import build_explanation_context
from orbital_sentinel.analytics.external_sources import (
    SourceVerificationReport,
    build_external_source_record,
    build_external_source_registry,
    verify_external_source_registry,
)
from orbital_sentinel.core.errors import ExternalSourceRegistryBuilderError

EPOCH = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)
DERIVED_AT = datetime(2026, 6, 7, 12, 0, tzinfo=timezone.utc)
FETCHED_AT = datetime(2024, 1, 1, 6, 0, tzinfo=timezone.utc)


def _clock() -> datetime:
    return DERIVED_AT


def _make_evidence(*, detector_event_id: str = "evt", days_offset: float = 0.0) -> DerivedEvidence:
    ep = EPOCH + timedelta(days=days_offset)
    return DerivedEvidence(
        evidence_id=compute_evidence_id(
            source_detector="maneuver_detection_v01", object_id=25544,
            detector_event_id=detector_event_id, event_epoch=ep,
            analysis_engine_version="0.1.0",
        ),
        object_id=25544,
        evidence_type=EVIDENCE_TYPE_MANEUVER,
        source_detector="maneuver_detection_v01",
        detector_event_id=detector_event_id,
        event_epoch=ep,
        honesty_payload={"detection_method_name": "test"},
        analysis_engine_version="0.1.0",
    )


def _bundle_and_evidence(*evs: DerivedEvidence):  # type: ignore[no-untyped-def]
    catalog = EvidenceCatalog.from_evidence(list(evs), derived_at=DERIVED_AT)
    ctx = build_explanation_context(catalog, object_id=25544, clock=_clock)
    bundle = build_evidence_bundle(ctx, catalog, clock=_clock)
    return bundle, list(evs)


def _make_source_record(*, dataset: str = "active.txt", payload: bytes = b"TLE_DATA"):  # type: ignore[no-untyped-def]
    return build_external_source_record(
        source_provider="celestrak",
        source_url=f"https://celestrak.org/NORAD/elements/{dataset}",
        source_dataset_identifier=dataset,
        fetched_at=FETCHED_AT,
        source_payload_hash=hashlib.sha256(payload).hexdigest(),
        source_payload_size_bytes=len(payload),
        source_content_type="tle_text",
    )


# --- Build records ---------------------------------------------


def test_build_external_source_record_deterministic() -> None:
    r1 = _make_source_record()
    r2 = _make_source_record()
    assert r1.source_record_id == r2.source_record_id


def test_build_external_source_record_id_recomputes() -> None:
    r = _make_source_record()
    from orbital_sentinel.analytics.external_sources.hashing import (
        compute_external_source_record_id,
    )
    expected = compute_external_source_record_id(
        source_provider=r.source_provider,
        source_url=r.source_url,
        source_dataset_identifier=r.source_dataset_identifier,
        fetched_at=r.fetched_at,
        source_payload_hash=r.source_payload_hash,
        source_payload_size_bytes=r.source_payload_size_bytes,
        source_content_type=r.source_content_type,
        source_layer_engine_version="1.0.0",
    )
    assert r.source_record_id == expected


# --- Build registry ---------------------------------------------


def test_build_empty_registry() -> None:
    bundle, _ = _bundle_and_evidence()
    reg = build_external_source_registry(bundle, [], {}, clock=_clock)
    assert reg.n_records == 0
    assert reg.registry_emit_reason == "empty_registry"
    assert reg.registry_id == reg.registry_hash


def test_build_full_registry() -> None:
    bundle, evs = _bundle_and_evidence(_make_evidence(detector_event_id="x"))
    src = _make_source_record()
    mapping = {evs[0].evidence_id: [src.source_record_id]}
    reg = build_external_source_registry(bundle, [src], mapping, clock=_clock)
    assert reg.n_records == 1
    assert reg.registry_emit_reason == "records_present"
    assert reg.source_bundle_id == bundle.bundle_id


def test_build_registry_rejects_uncovered_evidence() -> None:
    bundle, _ = _bundle_and_evidence(_make_evidence(detector_event_id="x"))
    with pytest.raises(ExternalSourceRegistryBuilderError, match="not covered"):
        build_external_source_registry(bundle, [_make_source_record()], {}, clock=_clock)


def test_build_registry_rejects_unknown_source_in_mapping() -> None:
    bundle, evs = _bundle_and_evidence(_make_evidence(detector_event_id="x"))
    src = _make_source_record()
    mapping = {evs[0].evidence_id: ["unknown_source_id"]}
    with pytest.raises(ExternalSourceRegistryBuilderError, match="unknown"):
        build_external_source_registry(bundle, [src], mapping, clock=_clock)


def test_build_registry_id_alias_of_hash() -> None:
    bundle, evs = _bundle_and_evidence(_make_evidence(detector_event_id="x"))
    src = _make_source_record()
    mapping = {evs[0].evidence_id: [src.source_record_id]}
    reg = build_external_source_registry(bundle, [src], mapping, clock=_clock)
    assert reg.registry_id == reg.registry_hash


def test_build_registry_clock_only_affects_derived_at() -> None:
    bundle, evs = _bundle_and_evidence(_make_evidence(detector_event_id="x"))
    src = _make_source_record()
    mapping = {evs[0].evidence_id: [src.source_record_id]}

    def early() -> datetime:
        return datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)

    def late() -> datetime:
        return datetime(2027, 1, 1, 0, 0, tzinfo=timezone.utc)
    r1 = build_external_source_registry(bundle, [src], mapping, clock=early)
    r2 = build_external_source_registry(bundle, [src], mapping, clock=late)
    assert r1.registry_id == r2.registry_id


# --- Verifier valid path --------------------------------------


def test_verify_empty_registry_valid() -> None:
    bundle, _ = _bundle_and_evidence()
    reg = build_external_source_registry(bundle, [], {}, clock=_clock)
    rpt = verify_external_source_registry(reg, bundle, clock=_clock)
    assert rpt.is_valid is True


def test_verify_full_registry_valid() -> None:
    bundle, evs = _bundle_and_evidence(_make_evidence(detector_event_id="x"))
    src = _make_source_record()
    mapping = {evs[0].evidence_id: [src.source_record_id]}
    reg = build_external_source_registry(bundle, [src], mapping, clock=_clock)
    rpt = verify_external_source_registry(reg, bundle, clock=_clock)
    assert rpt.is_valid is True
    assert rpt.findings == []
    assert rpt.n_records_verified == 1


def test_verify_all_checks_pass() -> None:
    bundle, evs = _bundle_and_evidence(_make_evidence(detector_event_id="x"))
    src = _make_source_record()
    mapping = {evs[0].evidence_id: [src.source_record_id]}
    reg = build_external_source_registry(bundle, [src], mapping, clock=_clock)
    rpt = verify_external_source_registry(reg, bundle, clock=_clock)
    assert rpt.registry_id_is_alias_of_registry_hash is True
    assert rpt.registry_hash_recomputes_correctly is True
    assert rpt.all_source_record_ids_recompute_correctly is True
    assert rpt.no_duplicate_source_record_ids is True
    assert rpt.forward_index_consistent is True
    assert rpt.reverse_index_consistent is True
    assert rpt.all_evidence_ids_covered is True
    assert rpt.source_bundle_id_matches is True
    assert rpt.source_layer_engine_version_consistent is True


# --- Verifier nunca lanza -----------------------------------


def test_verify_never_raises() -> None:
    bundle, _ = _bundle_and_evidence()
    reg = build_external_source_registry(bundle, [], {}, clock=_clock)
    rpt = verify_external_source_registry(reg, bundle, clock=_clock)
    assert isinstance(rpt, SourceVerificationReport)


# --- Swap detection ------------------------------------------


def test_verify_detects_bundle_mismatch() -> None:
    """Registry was built against bundle A but verified against bundle B."""
    bundle_a, evs_a = _bundle_and_evidence(_make_evidence(detector_event_id="a"))
    bundle_b, _ = _bundle_and_evidence(_make_evidence(detector_event_id="b"))
    src = _make_source_record()
    mapping = {evs_a[0].evidence_id: [src.source_record_id]}
    reg = build_external_source_registry(bundle_a, [src], mapping, clock=_clock)
    rpt = verify_external_source_registry(reg, bundle_b, clock=_clock)
    assert rpt.is_valid is False
    types = [f.finding_type for f in rpt.findings]
    assert "source_bundle_id_mismatch" in types


# --- Determinismo del reporte ----------------------------


def test_verify_report_reproducible() -> None:
    bundle, evs = _bundle_and_evidence(_make_evidence(detector_event_id="x"))
    src = _make_source_record()
    mapping = {evs[0].evidence_id: [src.source_record_id]}
    reg = build_external_source_registry(bundle, [src], mapping, clock=_clock)
    a = verify_external_source_registry(reg, bundle, clock=_clock)
    b = verify_external_source_registry(reg, bundle, clock=_clock)
    assert a.model_dump(mode="json") == b.model_dump(mode="json")


def test_verify_clock_only_affects_verified_at() -> None:
    bundle, evs = _bundle_and_evidence(_make_evidence(detector_event_id="x"))
    src = _make_source_record()
    mapping = {evs[0].evidence_id: [src.source_record_id]}
    reg = build_external_source_registry(bundle, [src], mapping, clock=_clock)

    def early() -> datetime:
        return datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)

    def late() -> datetime:
        return datetime(2027, 1, 1, 0, 0, tzinfo=timezone.utc)
    a = verify_external_source_registry(reg, bundle, clock=early)
    b = verify_external_source_registry(reg, bundle, clock=late)
    assert a.verification_hash == b.verification_hash
    assert a.verified_at != b.verified_at
