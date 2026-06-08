"""Tests del EvidenceCatalog (ADR-0029)."""

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

DERIVED_AT = datetime(2026, 6, 6, 12, 0, tzinfo=timezone.utc)
EPOCH = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)


def _ev(
    *,
    norad: int = 25544,
    detector: str = "maneuver_detection_v01",
    evidence_type: str = EVIDENCE_TYPE_MANEUVER,
    epoch_days_offset: float = 0.0,
    detector_event_id: str = "evt",
    engine: str = "0.1.0",
) -> DerivedEvidence:
    ep = EPOCH + timedelta(days=epoch_days_offset)
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
        honesty_payload={"detection_method_name": "test"},
        analysis_engine_version=engine,
    )


# --- Construcción ----------------------------------------------------


def test_empty_catalog_has_n_zero() -> None:
    cat = EvidenceCatalog.from_evidence([], derived_at=DERIVED_AT)
    assert cat.n_evidence == 0
    assert cat.list_all() == []


def test_catalog_orders_by_epoch_ascending() -> None:
    events = [
        _ev(detector_event_id="e3", epoch_days_offset=3),
        _ev(detector_event_id="e1", epoch_days_offset=1),
        _ev(detector_event_id="e2", epoch_days_offset=2),
    ]
    cat = EvidenceCatalog.from_evidence(events, derived_at=DERIVED_AT)
    epochs = [e.event_epoch for e in cat.evidence]
    assert epochs == sorted(epochs)


def test_catalog_orders_secondary_by_evidence_id() -> None:
    e1 = _ev(detector_event_id="z", epoch_days_offset=1.0)
    e2 = _ev(detector_event_id="a", epoch_days_offset=1.0)
    cat = EvidenceCatalog.from_evidence([e1, e2], derived_at=DERIVED_AT)
    ids = [e.evidence_id for e in cat.evidence]
    assert ids == sorted(ids)


def test_catalog_deduplicates_identical_evidence() -> None:
    e = _ev(detector_event_id="evt-dup")
    cat = EvidenceCatalog.from_evidence([e, e, e, e], derived_at=DERIVED_AT)
    assert cat.n_evidence == 1


def test_catalog_deduplicate_keeps_first_inserted() -> None:
    """Cuando hay dos evidencias con mismo ``evidence_id``, se conserva la
    primera vista. Determinismo de inserción."""
    a = _ev(detector_event_id="X")
    b = _ev(detector_event_id="X")
    assert a.evidence_id == b.evidence_id
    cat = EvidenceCatalog.from_evidence([a, b], derived_at=DERIVED_AT)
    assert cat.evidence[0] is a or cat.evidence[0] == a


# --- Filtros ---------------------------------------------------------


def test_list_by_norad_filters() -> None:
    a = _ev(norad=1, detector_event_id="a")
    b = _ev(norad=2, detector_event_id="b")
    c = _ev(norad=1, detector_event_id="c", epoch_days_offset=1.0)
    cat = EvidenceCatalog.from_evidence([a, b, c], derived_at=DERIVED_AT)
    result = cat.list_by_norad(1)
    assert {e.object_id for e in result} == {1}
    assert len(result) == 2


def test_list_by_norad_no_match() -> None:
    a = _ev(norad=1, detector_event_id="a")
    cat = EvidenceCatalog.from_evidence([a], derived_at=DERIVED_AT)
    assert cat.list_by_norad(99999) == []


def test_list_by_detector_maneuver() -> None:
    m = _ev(
        detector="maneuver_detection_v01",
        evidence_type=EVIDENCE_TYPE_MANEUVER,
        detector_event_id="m1",
    )
    a = _ev(
        detector="anomaly_detection_v01",
        evidence_type=EVIDENCE_TYPE_ANOMALY,
        detector_event_id="a1",
        epoch_days_offset=1.0,
    )
    c = _ev(
        detector="conjunction_detection_v01",
        evidence_type=EVIDENCE_TYPE_CONJUNCTION,
        detector_event_id="c1",
        epoch_days_offset=2.0,
    )
    cat = EvidenceCatalog.from_evidence([m, a, c], derived_at=DERIVED_AT)
    assert cat.list_by_detector("maneuver_detection_v01") == [m]
    assert cat.list_by_detector("anomaly_detection_v01") == [a]
    assert cat.list_by_detector("conjunction_detection_v01") == [c]


def test_list_by_detector_no_match() -> None:
    e = _ev(detector_event_id="x")
    cat = EvidenceCatalog.from_evidence([e], derived_at=DERIVED_AT)
    assert cat.list_by_detector("anomaly_detection_v01") == []


def test_list_by_epoch_range_start_only() -> None:
    events = [
        _ev(detector_event_id=f"e{i}", epoch_days_offset=float(i)) for i in range(5)
    ]
    cat = EvidenceCatalog.from_evidence(events, derived_at=DERIVED_AT)
    after = cat.list_by_epoch_range(start=EPOCH + timedelta(days=2))
    assert len(after) == 3  # days 2, 3, 4


def test_list_by_epoch_range_end_only() -> None:
    events = [
        _ev(detector_event_id=f"e{i}", epoch_days_offset=float(i)) for i in range(5)
    ]
    cat = EvidenceCatalog.from_evidence(events, derived_at=DERIVED_AT)
    before = cat.list_by_epoch_range(end=EPOCH + timedelta(days=2))
    assert len(before) == 3  # days 0, 1, 2


def test_list_by_epoch_range_both_bounds() -> None:
    events = [
        _ev(detector_event_id=f"e{i}", epoch_days_offset=float(i)) for i in range(5)
    ]
    cat = EvidenceCatalog.from_evidence(events, derived_at=DERIVED_AT)
    span = cat.list_by_epoch_range(
        start=EPOCH + timedelta(days=1), end=EPOCH + timedelta(days=3),
    )
    assert len(span) == 3


def test_list_by_epoch_range_inverted_returns_empty() -> None:
    events = [_ev(detector_event_id="e", epoch_days_offset=1.0)]
    cat = EvidenceCatalog.from_evidence(events, derived_at=DERIVED_AT)
    inverted = cat.list_by_epoch_range(
        start=EPOCH + timedelta(days=3), end=EPOCH + timedelta(days=1),
    )
    assert inverted == []


def test_list_by_epoch_range_neither_bound_returns_all() -> None:
    events = [_ev(detector_event_id=f"e{i}", epoch_days_offset=float(i)) for i in range(3)]
    cat = EvidenceCatalog.from_evidence(events, derived_at=DERIVED_AT)
    assert cat.list_by_epoch_range() == list(cat.evidence)


# --- Determinismo y reproducibilidad --------------------------------


def test_catalog_construction_is_deterministic() -> None:
    events = [
        _ev(detector_event_id=f"e{i}", epoch_days_offset=float(i)) for i in range(10)
    ]
    a = EvidenceCatalog.from_evidence(events, derived_at=DERIVED_AT)
    b = EvidenceCatalog.from_evidence(events, derived_at=DERIVED_AT)
    assert a.model_dump(mode="json") == b.model_dump(mode="json")


def test_catalog_construction_independent_of_input_order() -> None:
    forward = [_ev(detector_event_id=f"e{i}", epoch_days_offset=float(i)) for i in range(5)]
    reverse = list(reversed(forward))
    a = EvidenceCatalog.from_evidence(forward, derived_at=DERIVED_AT)
    b = EvidenceCatalog.from_evidence(reverse, derived_at=DERIVED_AT)
    assert [e.evidence_id for e in a.evidence] == [e.evidence_id for e in b.evidence]


# --- Errores --------------------------------------------------------


def test_n_evidence_matches_len_after_dedupe() -> None:
    a = _ev(detector_event_id="X")
    b = _ev(detector_event_id="X")  # mismo evidence_id
    c = _ev(detector_event_id="Y")
    cat = EvidenceCatalog.from_evidence([a, b, c], derived_at=DERIVED_AT)
    assert cat.n_evidence == 2
    assert len(cat.evidence) == 2


def test_list_all_returns_independent_copy() -> None:
    """``list_all`` debe devolver una copia: mutar el resultado no debe alterar
    el catálogo (es frozen)."""
    e = _ev(detector_event_id="evt")
    cat = EvidenceCatalog.from_evidence([e], derived_at=DERIVED_AT)
    snapshot = cat.list_all()
    snapshot.clear()
    assert cat.n_evidence == 1
    assert len(cat.evidence) == 1
