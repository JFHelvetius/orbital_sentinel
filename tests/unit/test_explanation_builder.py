"""Tests del :func:`build_explanation_context` (ADR-0030)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from orbital_sentinel.analytics.evidence import (
    EVIDENCE_TYPE_ANOMALY,
    EVIDENCE_TYPE_CONJUNCTION,
    EVIDENCE_TYPE_MANEUVER,
    DerivedEvidence,
    EvidenceCatalog,
    compute_evidence_id,
)
from orbital_sentinel.analytics.explanation import (
    CANONICAL_DETECTORS_V01,
    EXPLANATION_LAYER_ENGINE_VERSION,
    build_explanation_context,
    compute_context_id,
    compute_payload_hash,
    compute_source_catalog_signature,
)

EPOCH = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)
DERIVED_AT = datetime(2026, 6, 6, 12, 0, tzinfo=timezone.utc)


def _fixed_clock() -> datetime:
    return DERIVED_AT


def _make_evidence(
    *,
    norad: int = 25544,
    epoch_offset_days: float = 0.0,
    detector: str = "maneuver_detection_v01",
    evidence_type: str = EVIDENCE_TYPE_MANEUVER,
    detector_event_id: str = "evt",
    payload: dict | None = None,
    engine: str = "0.1.0",
) -> DerivedEvidence:
    ep = EPOCH + timedelta(days=epoch_offset_days)
    return DerivedEvidence(
        evidence_id=compute_evidence_id(
            source_detector=detector, object_id=norad,
            detector_event_id=detector_event_id, event_epoch=ep,
            analysis_engine_version=engine,
        ),
        object_id=norad,
        evidence_type=evidence_type,
        source_detector=detector,
        detector_event_id=detector_event_id,
        event_epoch=ep,
        honesty_payload=payload or {"detection_method_name": "test"},
        analysis_engine_version=engine,
    )


def _catalog_from(*evidence: DerivedEvidence) -> EvidenceCatalog:
    return EvidenceCatalog.from_evidence(list(evidence), derived_at=DERIVED_AT)


# --- Casos vacíos / minimos ------------------------------------------


def test_empty_catalog_produces_empty_context() -> None:
    catalog = _catalog_from()
    ctx = build_explanation_context(catalog, object_id=25544, clock=_fixed_clock)
    assert ctx.n_evidence_total == 0
    assert ctx.coverage_window_start is None
    assert ctx.coverage_window_end is None
    assert ctx.coverage_duration_seconds is None
    assert ctx.evidence_type_counts == {}
    assert ctx.evidence_references == []
    assert ctx.timeline.n_entries == 0
    assert ctx.timeline.first_epoch is None
    assert ctx.timeline.last_epoch is None


def test_single_evidence_coverage_start_equals_end() -> None:
    e = _make_evidence(epoch_offset_days=5.0, detector_event_id="solo")
    catalog = _catalog_from(e)
    ctx = build_explanation_context(catalog, object_id=25544, clock=_fixed_clock)
    assert ctx.n_evidence_total == 1
    assert ctx.coverage_window_start == ctx.coverage_window_end == e.event_epoch
    assert ctx.coverage_duration_seconds == 0.0


# --- Filtrado por object_id -----------------------------------------


def test_builder_filters_by_object_id() -> None:
    a = _make_evidence(norad=1, detector_event_id="a")
    b = _make_evidence(norad=2, detector_event_id="b")
    catalog = _catalog_from(a, b)
    ctx = build_explanation_context(catalog, object_id=1, clock=_fixed_clock)
    assert ctx.n_evidence_total == 1
    assert all(ref.object_id == 1 for ref in ctx.evidence_references)


# --- Detector summaries: shape estable ------------------------------


def test_detector_summaries_always_contain_three_detectors() -> None:
    e = _make_evidence(detector_event_id="x")
    catalog = _catalog_from(e)
    ctx = build_explanation_context(catalog, object_id=25544, clock=_fixed_clock)
    detectors = [s.source_detector for s in ctx.detector_summaries]
    assert detectors == list(CANONICAL_DETECTORS_V01)


def test_detector_summary_n_events_zero_for_absent_detector() -> None:
    e = _make_evidence(
        detector="maneuver_detection_v01",
        evidence_type=EVIDENCE_TYPE_MANEUVER,
        detector_event_id="m",
    )
    catalog = _catalog_from(e)
    ctx = build_explanation_context(catalog, object_id=25544, clock=_fixed_clock)
    by_det = {s.source_detector: s for s in ctx.detector_summaries}
    assert by_det["anomaly_detection_v01"].n_events == 0
    assert by_det["conjunction_detection_v01"].n_events == 0
    assert by_det["maneuver_detection_v01"].n_events == 1


def test_detector_summary_with_zero_events_has_none_epochs() -> None:
    catalog = _catalog_from()
    ctx = build_explanation_context(catalog, object_id=25544, clock=_fixed_clock)
    for s in ctx.detector_summaries:
        assert s.first_event_epoch is None
        assert s.last_event_epoch is None
        assert s.evidence_ids == []
        assert s.evidence_type_breakdown == {}


def test_detector_summary_n_events_matches_evidence_ids_length() -> None:
    a = _make_evidence(detector_event_id="a", epoch_offset_days=0)
    b = _make_evidence(detector_event_id="b", epoch_offset_days=1)
    c = _make_evidence(detector_event_id="c", epoch_offset_days=2)
    catalog = _catalog_from(a, b, c)
    ctx = build_explanation_context(catalog, object_id=25544, clock=_fixed_clock)
    summary = next(s for s in ctx.detector_summaries
                   if s.source_detector == "maneuver_detection_v01")
    assert summary.n_events == 3
    assert len(summary.evidence_ids) == 3


def test_detector_summary_first_last_epoch_correct() -> None:
    a = _make_evidence(detector_event_id="a", epoch_offset_days=5)
    b = _make_evidence(detector_event_id="b", epoch_offset_days=1)
    c = _make_evidence(detector_event_id="c", epoch_offset_days=3)
    catalog = _catalog_from(a, b, c)
    ctx = build_explanation_context(catalog, object_id=25544, clock=_fixed_clock)
    summary = next(s for s in ctx.detector_summaries
                   if s.source_detector == "maneuver_detection_v01")
    assert summary.first_event_epoch == b.event_epoch
    assert summary.last_event_epoch == a.event_epoch


def test_detector_summary_evidence_type_breakdown_sums_n_events() -> None:
    a = _make_evidence(detector_event_id="a", evidence_type=EVIDENCE_TYPE_MANEUVER)
    b = _make_evidence(detector_event_id="b", evidence_type=EVIDENCE_TYPE_MANEUVER,
                       epoch_offset_days=1.0)
    catalog = _catalog_from(a, b)
    ctx = build_explanation_context(catalog, object_id=25544, clock=_fixed_clock)
    summary = next(s for s in ctx.detector_summaries
                   if s.source_detector == "maneuver_detection_v01")
    assert sum(summary.evidence_type_breakdown.values()) == summary.n_events


# --- evidence_type_counts -------------------------------------------


def test_evidence_type_counts_sum_equals_n_total() -> None:
    a = _make_evidence(detector_event_id="a", evidence_type=EVIDENCE_TYPE_MANEUVER)
    b = _make_evidence(detector_event_id="b",
                       detector="anomaly_detection_v01",
                       evidence_type=EVIDENCE_TYPE_ANOMALY,
                       epoch_offset_days=1)
    catalog = _catalog_from(a, b)
    ctx = build_explanation_context(catalog, object_id=25544, clock=_fixed_clock)
    assert sum(ctx.evidence_type_counts.values()) == ctx.n_evidence_total


def test_evidence_type_counts_keys_sorted_alphabetically() -> None:
    """Keys insertadas en orden alfabético (preservado por Pydantic)."""
    a = _make_evidence(detector_event_id="a",
                       detector="maneuver_detection_v01",
                       evidence_type=EVIDENCE_TYPE_MANEUVER)
    b = _make_evidence(detector_event_id="b",
                       detector="anomaly_detection_v01",
                       evidence_type=EVIDENCE_TYPE_ANOMALY,
                       epoch_offset_days=1)
    catalog = _catalog_from(a, b)
    ctx = build_explanation_context(catalog, object_id=25544, clock=_fixed_clock)
    keys = list(ctx.evidence_type_counts.keys())
    assert keys == sorted(keys)


def test_evidence_type_counts_only_present_types() -> None:
    """Solo tipos observados; el catálogo no infla con zeros para tipos ausentes."""
    e = _make_evidence(evidence_type=EVIDENCE_TYPE_MANEUVER)
    catalog = _catalog_from(e)
    ctx = build_explanation_context(catalog, object_id=25544, clock=_fixed_clock)
    assert ctx.evidence_type_counts == {EVIDENCE_TYPE_MANEUVER: 1}


# --- Timeline -------------------------------------------------------


def test_timeline_orders_ascending_by_epoch() -> None:
    a = _make_evidence(detector_event_id="late", epoch_offset_days=5)
    b = _make_evidence(detector_event_id="early", epoch_offset_days=1)
    catalog = _catalog_from(a, b)
    ctx = build_explanation_context(catalog, object_id=25544, clock=_fixed_clock)
    epochs = [e.epoch for e in ctx.timeline.entries]
    assert epochs == sorted(epochs)


def test_timeline_n_entries_matches_n_total() -> None:
    a = _make_evidence(detector_event_id="a")
    b = _make_evidence(detector_event_id="b", epoch_offset_days=1)
    catalog = _catalog_from(a, b)
    ctx = build_explanation_context(catalog, object_id=25544, clock=_fixed_clock)
    assert ctx.timeline.n_entries == ctx.n_evidence_total


def test_timeline_first_last_epoch_match_extremes() -> None:
    a = _make_evidence(detector_event_id="a", epoch_offset_days=10)
    b = _make_evidence(detector_event_id="b", epoch_offset_days=1)
    c = _make_evidence(detector_event_id="c", epoch_offset_days=5)
    catalog = _catalog_from(a, b, c)
    ctx = build_explanation_context(catalog, object_id=25544, clock=_fixed_clock)
    assert ctx.timeline.first_epoch == b.event_epoch
    assert ctx.timeline.last_epoch == a.event_epoch


# --- coverage_* -----------------------------------------------------


def test_coverage_window_start_end_match_extremes() -> None:
    a = _make_evidence(detector_event_id="a", epoch_offset_days=3)
    b = _make_evidence(detector_event_id="b", epoch_offset_days=10)
    catalog = _catalog_from(a, b)
    ctx = build_explanation_context(catalog, object_id=25544, clock=_fixed_clock)
    assert ctx.coverage_window_start == a.event_epoch
    assert ctx.coverage_window_end == b.event_epoch


def test_coverage_duration_seconds_correct() -> None:
    a = _make_evidence(detector_event_id="a", epoch_offset_days=2)
    b = _make_evidence(detector_event_id="b", epoch_offset_days=5)
    catalog = _catalog_from(a, b)
    ctx = build_explanation_context(catalog, object_id=25544, clock=_fixed_clock)
    expected = (b.event_epoch - a.event_epoch).total_seconds()
    assert ctx.coverage_duration_seconds == expected


# --- Determinismo / identidad ---------------------------------------


def test_context_id_reproducible_across_runs() -> None:
    e = _make_evidence(detector_event_id="evt", epoch_offset_days=2)
    catalog = _catalog_from(e)
    a = build_explanation_context(catalog, object_id=25544, clock=_fixed_clock)
    b = build_explanation_context(catalog, object_id=25544, clock=_fixed_clock)
    assert a.context_id == b.context_id


def test_context_id_changes_with_different_object_id() -> None:
    e1 = _make_evidence(norad=1, detector_event_id="e", epoch_offset_days=1)
    e2 = _make_evidence(norad=2, detector_event_id="e", epoch_offset_days=1)
    cat = _catalog_from(e1, e2)
    ctx1 = build_explanation_context(cat, object_id=1, clock=_fixed_clock)
    ctx2 = build_explanation_context(cat, object_id=2, clock=_fixed_clock)
    assert ctx1.context_id != ctx2.context_id


def test_context_id_changes_with_different_evidence_set() -> None:
    e1 = _make_evidence(detector_event_id="x", epoch_offset_days=1)
    e2 = _make_evidence(detector_event_id="y", epoch_offset_days=2)
    cat1 = _catalog_from(e1)
    cat2 = _catalog_from(e1, e2)
    a = build_explanation_context(cat1, object_id=25544, clock=_fixed_clock)
    b = build_explanation_context(cat2, object_id=25544, clock=_fixed_clock)
    assert a.context_id != b.context_id


def test_source_catalog_signature_depends_only_on_evidence_ids() -> None:
    """Mismo conjunto de evidence_ids → misma signature, independiente
    de orden o derived_at."""
    e1 = _make_evidence(detector_event_id="a", epoch_offset_days=1)
    e2 = _make_evidence(detector_event_id="b", epoch_offset_days=2)
    cat_forward = _catalog_from(e1, e2)
    cat_reverse = _catalog_from(e2, e1)
    a = build_explanation_context(cat_forward, object_id=25544, clock=_fixed_clock)
    b = build_explanation_context(cat_reverse, object_id=25544, clock=_fixed_clock)
    assert a.source_catalog_signature == b.source_catalog_signature


def test_full_output_reproducible_run_to_run() -> None:
    """Mismo input + clock fijo → JSON idéntico."""
    e1 = _make_evidence(detector_event_id="a", epoch_offset_days=0)
    e2 = _make_evidence(detector_event_id="b", epoch_offset_days=1)
    catalog = _catalog_from(e1, e2)
    a = build_explanation_context(catalog, object_id=25544, clock=_fixed_clock)
    b = build_explanation_context(catalog, object_id=25544, clock=_fixed_clock)
    assert a.model_dump(mode="json") == b.model_dump(mode="json")


def test_clock_only_affects_derived_at() -> None:
    """Cambiar el clock no debe alterar context_id ni signature."""
    e = _make_evidence(detector_event_id="x")
    catalog = _catalog_from(e)
    early = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
    late = datetime(2027, 1, 1, 0, 0, tzinfo=timezone.utc)
    a = build_explanation_context(catalog, object_id=25544, clock=lambda: early)
    b = build_explanation_context(catalog, object_id=25544, clock=lambda: late)
    assert a.context_id == b.context_id
    assert a.source_catalog_signature == b.source_catalog_signature
    assert a.derived_at != b.derived_at


def test_builder_without_clock_uses_utc_now() -> None:
    catalog = _catalog_from()
    ctx = build_explanation_context(catalog, object_id=25544)
    assert ctx.derived_at.tzinfo is not None


# --- honesty payload hash ------------------------------------------


def test_honesty_payload_hash_same_payload_same_hash() -> None:
    payload = {"detection_method_name": "X", "z": 1.5}
    a = _make_evidence(detector_event_id="a", payload=payload)
    b = _make_evidence(detector_event_id="b", payload=payload, epoch_offset_days=1)
    catalog = _catalog_from(a, b)
    ctx = build_explanation_context(catalog, object_id=25544, clock=_fixed_clock)
    refs = {r.evidence_id: r for r in ctx.evidence_references}
    hashes = {r.honesty_payload_hash for r in refs.values()}
    assert len(hashes) == 1  # mismo payload → mismo hash


def test_honesty_payload_hash_different_payload_different_hash() -> None:
    a = _make_evidence(detector_event_id="a", payload={"k": 1})
    b = _make_evidence(detector_event_id="b", payload={"k": 2}, epoch_offset_days=1)
    catalog = _catalog_from(a, b)
    ctx = build_explanation_context(catalog, object_id=25544, clock=_fixed_clock)
    hashes = {r.honesty_payload_hash for r in ctx.evidence_references}
    assert len(hashes) == 2


def test_honesty_payload_hash_matches_compute_payload_hash_helper() -> None:
    """Cada honesty_payload_hash en el contexto debe coincidir bit-exacto con
    compute_payload_hash aplicado al payload original."""
    payload = {"detection_method_name": "X", "score": 4.2}
    e = _make_evidence(detector_event_id="x", payload=payload)
    catalog = _catalog_from(e)
    ctx = build_explanation_context(catalog, object_id=25544, clock=_fixed_clock)
    ref = ctx.evidence_references[0]
    assert ref.honesty_payload_hash == compute_payload_hash(payload)


# --- Trazabilidad y referencias ------------------------------------


def test_evidence_references_match_catalog_ids() -> None:
    a = _make_evidence(detector_event_id="a")
    b = _make_evidence(detector_event_id="b", epoch_offset_days=1)
    catalog = _catalog_from(a, b)
    ctx = build_explanation_context(catalog, object_id=25544, clock=_fixed_clock)
    catalog_ids = {e.evidence_id for e in catalog.list_by_norad(25544)}
    ctx_ids = {r.evidence_id for r in ctx.evidence_references}
    assert ctx_ids == catalog_ids


def test_evidence_references_orden_estable() -> None:
    a = _make_evidence(detector_event_id="z", epoch_offset_days=3)
    b = _make_evidence(detector_event_id="a", epoch_offset_days=1)
    c = _make_evidence(detector_event_id="m", epoch_offset_days=2)
    catalog = _catalog_from(a, b, c)
    ctx = build_explanation_context(catalog, object_id=25544, clock=_fixed_clock)
    epochs = [r.event_epoch for r in ctx.evidence_references]
    assert epochs == sorted(epochs)


def test_evidence_references_secondary_order_by_evidence_id_on_epoch_ties() -> None:
    """Dos evidencias con el mismo epoch → desempate ascendente por evidence_id."""
    a = _make_evidence(detector_event_id="a-id", epoch_offset_days=2)
    b = _make_evidence(
        detector_event_id="z-id", epoch_offset_days=2,
        detector="anomaly_detection_v01",
        evidence_type="anomaly_observed",
    )
    catalog = _catalog_from(a, b)
    ctx = build_explanation_context(catalog, object_id=25544, clock=_fixed_clock)
    epochs = [r.event_epoch for r in ctx.evidence_references]
    assert epochs[0] == epochs[1]  # mismo epoch
    ids = [r.evidence_id for r in ctx.evidence_references]
    assert ids == sorted(ids)


# --- Coherencia interna --------------------------------------------


def test_n_evidence_total_matches_references() -> None:
    a = _make_evidence(detector_event_id="a")
    b = _make_evidence(detector_event_id="b", epoch_offset_days=1)
    catalog = _catalog_from(a, b)
    ctx = build_explanation_context(catalog, object_id=25544, clock=_fixed_clock)
    assert ctx.n_evidence_total == len(ctx.evidence_references)


def test_sum_of_detector_n_events_equals_n_total() -> None:
    a = _make_evidence(detector_event_id="a",
                       detector="maneuver_detection_v01",
                       evidence_type=EVIDENCE_TYPE_MANEUVER)
    b = _make_evidence(detector_event_id="b",
                       detector="anomaly_detection_v01",
                       evidence_type=EVIDENCE_TYPE_ANOMALY,
                       epoch_offset_days=1)
    catalog = _catalog_from(a, b)
    ctx = build_explanation_context(catalog, object_id=25544, clock=_fixed_clock)
    total = sum(s.n_events for s in ctx.detector_summaries)
    assert total == ctx.n_evidence_total


# --- Mixed-detector / multi-type -----------------------------------


def test_builder_handles_all_three_evidence_types() -> None:
    m = _make_evidence(detector_event_id="m",
                       detector="maneuver_detection_v01",
                       evidence_type=EVIDENCE_TYPE_MANEUVER,
                       epoch_offset_days=0)
    a = _make_evidence(detector_event_id="a",
                       detector="anomaly_detection_v01",
                       evidence_type=EVIDENCE_TYPE_ANOMALY,
                       epoch_offset_days=1)
    c = _make_evidence(detector_event_id="c",
                       detector="conjunction_detection_v01",
                       evidence_type=EVIDENCE_TYPE_CONJUNCTION,
                       epoch_offset_days=2)
    catalog = _catalog_from(m, a, c)
    ctx = build_explanation_context(catalog, object_id=25544, clock=_fixed_clock)
    assert ctx.n_evidence_total == 3
    by_det = {s.source_detector: s for s in ctx.detector_summaries}
    assert by_det["maneuver_detection_v01"].n_events == 1
    assert by_det["anomaly_detection_v01"].n_events == 1
    assert by_det["conjunction_detection_v01"].n_events == 1


def test_evidence_type_counts_full_coverage() -> None:
    m = _make_evidence(detector_event_id="m",
                       detector="maneuver_detection_v01",
                       evidence_type=EVIDENCE_TYPE_MANEUVER)
    a = _make_evidence(detector_event_id="a",
                       detector="anomaly_detection_v01",
                       evidence_type=EVIDENCE_TYPE_ANOMALY,
                       epoch_offset_days=1)
    c = _make_evidence(detector_event_id="c",
                       detector="conjunction_detection_v01",
                       evidence_type=EVIDENCE_TYPE_CONJUNCTION,
                       epoch_offset_days=2)
    catalog = _catalog_from(m, a, c)
    ctx = build_explanation_context(catalog, object_id=25544, clock=_fixed_clock)
    assert set(ctx.evidence_type_counts.keys()) == {
        EVIDENCE_TYPE_MANEUVER, EVIDENCE_TYPE_ANOMALY, EVIDENCE_TYPE_CONJUNCTION,
    }


# --- Context_id depende del catálogo, no del clock ----------------


def test_context_id_uses_explanation_engine_version() -> None:
    e = _make_evidence(detector_event_id="x")
    catalog = _catalog_from(e)
    sig = compute_source_catalog_signature(
        r.evidence_id for r in catalog.list_by_norad(25544)
    )
    expected = compute_context_id(
        object_id=25544,
        explanation_engine_version=EXPLANATION_LAYER_ENGINE_VERSION,
        source_catalog_signature=sig,
    )
    ctx = build_explanation_context(catalog, object_id=25544, clock=_fixed_clock)
    assert ctx.context_id == expected


# --- Round-trip / serialización -------------------------------------


def test_built_context_roundtrips_through_model_dump_validate() -> None:
    a = _make_evidence(detector_event_id="a")
    b = _make_evidence(detector_event_id="b", epoch_offset_days=1)
    catalog = _catalog_from(a, b)
    ctx = build_explanation_context(catalog, object_id=25544, clock=_fixed_clock)
    raw = ctx.model_dump(mode="json")
    from orbital_sentinel.analytics.explanation import ExplanationContext
    re = ExplanationContext.model_validate(raw)
    assert re.model_dump(mode="json") == raw
