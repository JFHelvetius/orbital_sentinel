"""Tests del :func:`build_evidence_bundle` (ADR-0031)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from orbital_sentinel.analytics.bundles import (
    BUNDLE_ENGINE_VERSION,
    build_evidence_bundle,
    compute_bundle_payload_signature,
    compute_bundle_signature,
)
from orbital_sentinel.analytics.evidence import (
    EVIDENCE_TYPE_ANOMALY,
    EVIDENCE_TYPE_MANEUVER,
    DerivedEvidence,
    EvidenceCatalog,
    compute_evidence_id,
)
from orbital_sentinel.analytics.explanation import build_explanation_context

EPOCH = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)
DERIVED_AT = datetime(2026, 6, 6, 12, 0, tzinfo=timezone.utc)


def _fixed_clock() -> datetime:
    return DERIVED_AT


def _make_evidence(
    *,
    norad: int = 25544,
    days_offset: float = 0.0,
    detector_event_id: str = "evt",
    detector: str = "maneuver_detection_v01",
    evidence_type: str = EVIDENCE_TYPE_MANEUVER,
    payload: dict | None = None,
) -> DerivedEvidence:
    ep = EPOCH + timedelta(days=days_offset)
    return DerivedEvidence(
        evidence_id=compute_evidence_id(
            source_detector=detector, object_id=norad,
            detector_event_id=detector_event_id, event_epoch=ep,
            analysis_engine_version="0.1.0",
        ),
        object_id=norad,
        evidence_type=evidence_type,
        source_detector=detector,
        detector_event_id=detector_event_id,
        event_epoch=ep,
        honesty_payload=payload or {"detection_method_name": "test"},
        analysis_engine_version="0.1.0",
    )


def _catalog(*evs: DerivedEvidence) -> EvidenceCatalog:
    return EvidenceCatalog.from_evidence(list(evs), derived_at=DERIVED_AT)


# --- Construcción básica ---------------------------------------------


def test_build_bundle_empty_context_produces_empty_bundle() -> None:
    cat = _catalog()
    ctx = build_explanation_context(cat, object_id=25544, clock=_fixed_clock)
    bundle = build_evidence_bundle(ctx, cat, clock=_fixed_clock)
    assert bundle.n_evidence_payloads == 0
    assert bundle.evidence_payloads == []
    assert bundle.context.object_id == 25544


def test_build_bundle_single_evidence() -> None:
    e = _make_evidence(detector_event_id="solo")
    cat = _catalog(e)
    ctx = build_explanation_context(cat, object_id=25544, clock=_fixed_clock)
    bundle = build_evidence_bundle(ctx, cat, clock=_fixed_clock)
    assert bundle.n_evidence_payloads == 1
    assert bundle.evidence_payloads[0].evidence_id == e.evidence_id


def test_build_bundle_n_payloads_matches_context_references() -> None:
    a = _make_evidence(detector_event_id="a", days_offset=0)
    b = _make_evidence(detector_event_id="b", days_offset=1)
    c = _make_evidence(detector_event_id="c", days_offset=2)
    cat = _catalog(a, b, c)
    ctx = build_explanation_context(cat, object_id=25544, clock=_fixed_clock)
    bundle = build_evidence_bundle(ctx, cat, clock=_fixed_clock)
    assert bundle.n_evidence_payloads == len(ctx.evidence_references)
    assert bundle.n_evidence_payloads == 3


# --- bundle_id es alias estricto -------------------------------------


def test_built_bundle_id_equals_bundle_signature() -> None:
    """Hard invariant ADR-0031."""
    e = _make_evidence(detector_event_id="solo")
    cat = _catalog(e)
    ctx = build_explanation_context(cat, object_id=25544, clock=_fixed_clock)
    bundle = build_evidence_bundle(ctx, cat, clock=_fixed_clock)
    assert bundle.bundle_id == bundle.bundle_signature


# --- payload_integrity_verified_at_build -----------------------------


def test_bundled_payloads_verified_at_build_when_consistent() -> None:
    e = _make_evidence(detector_event_id="x")
    cat = _catalog(e)
    ctx = build_explanation_context(cat, object_id=25544, clock=_fixed_clock)
    bundle = build_evidence_bundle(ctx, cat, clock=_fixed_clock)
    for bp in bundle.evidence_payloads:
        assert bp.payload_integrity_verified_at_build is True


def test_recomputed_payload_hash_matches_context_reference() -> None:
    e = _make_evidence(detector_event_id="x")
    cat = _catalog(e)
    ctx = build_explanation_context(cat, object_id=25544, clock=_fixed_clock)
    bundle = build_evidence_bundle(ctx, cat, clock=_fixed_clock)
    bp = bundle.evidence_payloads[0]
    ref = next(r for r in ctx.evidence_references if r.evidence_id == bp.evidence_id)
    assert bp.recomputed_payload_hash == ref.honesty_payload_hash


# --- Determinismo -----------------------------------------------------


def test_build_bundle_signature_deterministic_across_runs() -> None:
    a = _make_evidence(detector_event_id="a", days_offset=0)
    b = _make_evidence(detector_event_id="b", days_offset=1)
    cat = _catalog(a, b)
    ctx = build_explanation_context(cat, object_id=25544, clock=_fixed_clock)
    bundle_a = build_evidence_bundle(ctx, cat, clock=_fixed_clock)
    bundle_b = build_evidence_bundle(ctx, cat, clock=_fixed_clock)
    assert bundle_a.bundle_signature == bundle_b.bundle_signature
    assert bundle_a.bundle_payload_signature == bundle_b.bundle_payload_signature
    assert bundle_a.bundle_id == bundle_b.bundle_id


def test_build_bundle_full_output_reproducible() -> None:
    e = _make_evidence(detector_event_id="x")
    cat = _catalog(e)
    ctx = build_explanation_context(cat, object_id=25544, clock=_fixed_clock)
    a = build_evidence_bundle(ctx, cat, clock=_fixed_clock)
    b = build_evidence_bundle(ctx, cat, clock=_fixed_clock)
    assert a.model_dump(mode="json") == b.model_dump(mode="json")


def test_clock_only_affects_derived_at_in_bundle() -> None:
    e = _make_evidence(detector_event_id="x")
    cat = _catalog(e)
    ctx = build_explanation_context(cat, object_id=25544, clock=_fixed_clock)

    def early() -> datetime:
        return datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)

    def late() -> datetime:
        return datetime(2027, 1, 1, 0, 0, tzinfo=timezone.utc)
    a = build_evidence_bundle(ctx, cat, clock=early)
    b = build_evidence_bundle(ctx, cat, clock=late)
    assert a.bundle_id == b.bundle_id
    assert a.bundle_signature == b.bundle_signature
    assert a.bundle_payload_signature == b.bundle_payload_signature
    assert a.derived_at != b.derived_at


def test_bundle_signature_matches_helper_computation() -> None:
    a = _make_evidence(detector_event_id="a", days_offset=0)
    b = _make_evidence(detector_event_id="b", days_offset=1)
    cat = _catalog(a, b)
    ctx = build_explanation_context(cat, object_id=25544, clock=_fixed_clock)
    bundle = build_evidence_bundle(ctx, cat, clock=_fixed_clock)
    expected_payload_sig = compute_bundle_payload_signature(bundle.evidence_payloads)
    expected_bundle_sig = compute_bundle_signature(
        context_id=ctx.context_id,
        bundle_payload_signature=expected_payload_sig,
        bundle_engine_version=BUNDLE_ENGINE_VERSION,
    )
    assert bundle.bundle_payload_signature == expected_payload_sig
    assert bundle.bundle_signature == expected_bundle_sig


# --- Multi-detector ---------------------------------------------------


def test_bundle_carries_all_detectors() -> None:
    m = _make_evidence(detector_event_id="m", days_offset=0)
    a = _make_evidence(detector_event_id="a", days_offset=1,
                       detector="anomaly_detection_v01",
                       evidence_type=EVIDENCE_TYPE_ANOMALY)
    cat = _catalog(m, a)
    ctx = build_explanation_context(cat, object_id=25544, clock=_fixed_clock)
    bundle = build_evidence_bundle(ctx, cat, clock=_fixed_clock)
    detectors = {bp.derived_evidence.source_detector for bp in bundle.evidence_payloads}
    assert "maneuver_detection_v01" in detectors
    assert "anomaly_detection_v01" in detectors


def test_bundle_payload_signatures_change_when_evidence_changes() -> None:
    a = _make_evidence(detector_event_id="a")
    b = _make_evidence(detector_event_id="b", days_offset=1)
    cat1 = _catalog(a)
    cat2 = _catalog(a, b)
    ctx1 = build_explanation_context(cat1, object_id=25544, clock=_fixed_clock)
    ctx2 = build_explanation_context(cat2, object_id=25544, clock=_fixed_clock)
    bundle1 = build_evidence_bundle(ctx1, cat1, clock=_fixed_clock)
    bundle2 = build_evidence_bundle(ctx2, cat2, clock=_fixed_clock)
    assert bundle1.bundle_signature != bundle2.bundle_signature
    assert bundle1.bundle_payload_signature != bundle2.bundle_payload_signature


# --- Context embebido literal ---------------------------------------


def test_bundle_carries_full_context_object() -> None:
    e = _make_evidence(detector_event_id="x")
    cat = _catalog(e)
    ctx = build_explanation_context(cat, object_id=25544, clock=_fixed_clock)
    bundle = build_evidence_bundle(ctx, cat, clock=_fixed_clock)
    assert bundle.context.context_id == ctx.context_id
    assert bundle.context.source_catalog_signature == ctx.source_catalog_signature
    assert bundle.context.n_evidence_total == ctx.n_evidence_total


def test_bundle_evidence_payloads_carry_full_derived_evidence() -> None:
    e = _make_evidence(detector_event_id="x", payload={"key": "value"})
    cat = _catalog(e)
    ctx = build_explanation_context(cat, object_id=25544, clock=_fixed_clock)
    bundle = build_evidence_bundle(ctx, cat, clock=_fixed_clock)
    bp = bundle.evidence_payloads[0]
    assert bp.derived_evidence.honesty_payload == {"key": "value"}
    assert bp.derived_evidence.evidence_id == e.evidence_id


# --- object_id en bundle ---------------------------------------------


def test_bundle_object_id_matches_context() -> None:
    e = _make_evidence(norad=99999, detector_event_id="x")
    cat = _catalog(e)
    ctx = build_explanation_context(cat, object_id=99999, clock=_fixed_clock)
    bundle = build_evidence_bundle(ctx, cat, clock=_fixed_clock)
    assert bundle.object_id == 99999
    assert bundle.context.object_id == 99999


def test_bundle_does_not_include_evidence_from_other_objects() -> None:
    a = _make_evidence(norad=1, detector_event_id="a")
    b = _make_evidence(norad=2, detector_event_id="b")
    cat = _catalog(a, b)
    ctx = build_explanation_context(cat, object_id=1, clock=_fixed_clock)
    bundle = build_evidence_bundle(ctx, cat, clock=_fixed_clock)
    assert bundle.n_evidence_payloads == 1
    for bp in bundle.evidence_payloads:
        assert bp.derived_evidence.object_id == 1
