"""Tests de los builders del Evidence Layer (ADR-0029)."""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

from orbital_sentinel.analytics.anomalies import detect_anomalies
from orbital_sentinel.analytics.conjunctions.storage import ConjunctionDetection
from orbital_sentinel.analytics.evidence import (
    EVIDENCE_TYPE_ANOMALY,
    EVIDENCE_TYPE_CONJUNCTION,
    EVIDENCE_TYPE_MANEUVER,
    build_anomaly_evidence,
    build_conjunction_evidence,
    build_maneuver_evidence,
)
from orbital_sentinel.analytics.maneuvers import (
    OrbitalElementSeries,
    detect_maneuvers,
)
from tests.unit.test_maneuver_series import make_element

DERIVED_AT_FIXED = datetime(2026, 6, 6, 12, 0, tzinfo=timezone.utc)


def _fixed_clock() -> datetime:
    return DERIVED_AT_FIXED


def _series_with_maneuver(n: int = 20, jump_at: int = 15) -> OrbitalElementSeries:
    els = []
    for i in range(n):
        bump = 1e-2 if i > jump_at else 0.0
        els.append(
            make_element(
                days_offset=float(i),
                mean_motion=15.5 + 1e-7 * i + bump,
                tle_hash=f"{i:064x}",
            )
        )
    return OrbitalElementSeries.from_elements(els)


def _series_with_anomaly_shift(n: int = 25, shift_at: int = 21) -> OrbitalElementSeries:
    els = []
    for i in range(n):
        bump = 1e-2 if i >= shift_at else 0.0
        els.append(
            make_element(
                days_offset=float(i),
                mean_motion=15.5 + bump,
                tle_hash=f"{i:064x}",
            )
        )
    return OrbitalElementSeries.from_elements(els)


def _make_conjunction(
    *, norad_a: int, norad_b: int, miss_km: float = 0.5, pc_value: float = 0.0,
) -> ConjunctionDetection:
    tca = datetime(2024, 6, 15, 12, 0, tzinfo=timezone.utc)
    canonical = f"conj-{norad_a}-{norad_b}-{tca.isoformat()}"
    detection_hash = hashlib.sha256(canonical.encode()).hexdigest()
    return ConjunctionDetection(
        detection_content_hash=detection_hash,
        norad_a=norad_a,
        norad_b=norad_b,
        element_a_content_hash_source="a" * 64,
        element_a_tle_index=0,
        element_a_tle_content_hash="1" + "0" * 63,
        element_b_content_hash_source="b" * 64,
        element_b_tle_index=0,
        element_b_tle_content_hash="2" + "0" * 63,
        window_start=tca - timedelta(hours=1),
        window_end=tca + timedelta(hours=1),
        step_minutes=1.0,
        n_samples=120,
        tca=tca,
        miss_distance_km=miss_km,
        relative_velocity_km_s=14.0,
        minutes_from_epoch_a_at_tca=10.0,
        minutes_from_epoch_b_at_tca=12.0,
        sgp4_uncertainty_baseline_km=3.0,
        sgp4_uncertainty_growth_km_per_day=3.0,
        tca_resolution_minutes=0.01666,
        tca_was_refined=True,
        pc=pc_value,
        combined_hard_body_radius_km=0.01,
        covariance_model_name="tle_isotropic_spherical_v1",
        covariance_baseline_sigma_km=1.0,
        covariance_growth_sigma_km_per_day=1.0,
        combined_sigma_at_tca_km=1.41,
        pc_method="foster_1992_fast_approximation",
        analysis_schema_version="0.3.0",
        analysis_engine_version="0.3.0",
        analysis_derived_at=DERIVED_AT_FIXED,
        persistence_schema_version="0.2.0",
        persisted_at=DERIVED_AT_FIXED,
    )


# --- build_maneuver_evidence ------------------------------------------


def test_build_maneuver_empty_result_returns_empty_list() -> None:
    series = OrbitalElementSeries.from_elements([
        make_element(days_offset=0.0, tle_hash="a" * 64),
        make_element(days_offset=1.0, tle_hash="b" * 64),
    ])
    result = detect_maneuvers(series, clock=_fixed_clock)
    assert build_maneuver_evidence(result) == []


def test_build_maneuver_produces_one_evidence_per_event() -> None:
    series = _series_with_maneuver()
    result = detect_maneuvers(series, baseline_window_days=30.0, clock=_fixed_clock)
    evidence = build_maneuver_evidence(result)
    assert len(evidence) == result.n_events
    assert len(evidence) >= 1


def test_build_maneuver_evidence_type_correct() -> None:
    series = _series_with_maneuver()
    result = detect_maneuvers(series, baseline_window_days=30.0, clock=_fixed_clock)
    for ev in build_maneuver_evidence(result):
        assert ev.evidence_type == EVIDENCE_TYPE_MANEUVER
        assert ev.source_detector == "maneuver_detection_v01"


def test_build_maneuver_preserves_honesty_fields() -> None:
    series = _series_with_maneuver()
    result = detect_maneuvers(
        series, baseline_window_days=30.0, detection_threshold_sigma=3.5,
        clock=_fixed_clock,
    )
    evidence = build_maneuver_evidence(result)
    assert evidence
    payload = evidence[0].honesty_payload
    for required in (
        "detection_method_name", "baseline_window_days",
        "detection_threshold_sigma", "n_baseline_samples",
        "dominant_component", "delta_t_days",
        "z_score_mean_motion", "z_score_eccentricity", "z_score_inclination",
    ):
        assert required in payload, f"falta {required} en honesty_payload"


def test_build_maneuver_uses_epoch_after_as_event_epoch() -> None:
    series = _series_with_maneuver()
    result = detect_maneuvers(series, baseline_window_days=30.0, clock=_fixed_clock)
    for ev_obj, source in zip(build_maneuver_evidence(result), result.events, strict=True):
        assert ev_obj.event_epoch == source.epoch_after


def test_build_maneuver_evidence_id_deterministic() -> None:
    series = _series_with_maneuver()
    result_a = detect_maneuvers(series, baseline_window_days=30.0, clock=_fixed_clock)
    result_b = detect_maneuvers(series, baseline_window_days=30.0, clock=_fixed_clock)
    ids_a = [e.evidence_id for e in build_maneuver_evidence(result_a)]
    ids_b = [e.evidence_id for e in build_maneuver_evidence(result_b)]
    assert ids_a == ids_b


def test_build_maneuver_is_apparent_not_confirmed_true() -> None:
    series = _series_with_maneuver()
    result = detect_maneuvers(series, baseline_window_days=30.0, clock=_fixed_clock)
    for ev in build_maneuver_evidence(result):
        assert ev.is_apparent_not_confirmed is True


# --- build_anomaly_evidence -------------------------------------------


def test_build_anomaly_empty_result_returns_empty_list() -> None:
    series = OrbitalElementSeries.from_elements([
        make_element(days_offset=0.0, tle_hash="a" * 64),
        make_element(days_offset=1.0, tle_hash="b" * 64),
    ])
    result = detect_anomalies(series, clock=_fixed_clock)
    assert build_anomaly_evidence(result) == []


def test_build_anomaly_produces_one_evidence_per_event() -> None:
    series = _series_with_anomaly_shift()
    result = detect_anomalies(series, baseline_window_days=30.0, clock=_fixed_clock)
    evidence = build_anomaly_evidence(result)
    assert len(evidence) == result.total_anomalies_found
    assert len(evidence) >= 1


def test_build_anomaly_evidence_type_correct() -> None:
    series = _series_with_anomaly_shift()
    result = detect_anomalies(series, baseline_window_days=30.0, clock=_fixed_clock)
    for ev in build_anomaly_evidence(result):
        assert ev.evidence_type == EVIDENCE_TYPE_ANOMALY
        assert ev.source_detector == "anomaly_detection_v01"


def test_build_anomaly_preserves_honesty_fields() -> None:
    series = _series_with_anomaly_shift()
    result = detect_anomalies(series, baseline_window_days=30.0, clock=_fixed_clock)
    evidence = build_anomaly_evidence(result)
    assert evidence
    payload = evidence[0].honesty_payload
    for required in (
        "detection_method_name", "baseline_window_days",
        "threshold_sigma", "n_baseline_samples",
        "feature_name", "observed_value",
        "baseline_mean", "baseline_stddev", "anomaly_score",
    ):
        assert required in payload, f"falta {required}"


def test_build_anomaly_evidence_id_deterministic() -> None:
    series = _series_with_anomaly_shift()
    a = detect_anomalies(series, baseline_window_days=30.0, clock=_fixed_clock)
    b = detect_anomalies(series, baseline_window_days=30.0, clock=_fixed_clock)
    ids_a = [e.evidence_id for e in build_anomaly_evidence(a)]
    ids_b = [e.evidence_id for e in build_anomaly_evidence(b)]
    assert ids_a == ids_b


def test_build_anomaly_each_feature_distinct_evidence_id() -> None:
    """En un mismo epoch, dos features distintas producen evidencias distintas."""
    series = _series_with_anomaly_shift()
    result = detect_anomalies(series, baseline_window_days=30.0, clock=_fixed_clock)
    evs = build_anomaly_evidence(result)
    ids = {e.evidence_id for e in evs}
    assert len(ids) == len(evs)


def test_build_anomaly_is_apparent_not_confirmed_true() -> None:
    series = _series_with_anomaly_shift()
    result = detect_anomalies(series, baseline_window_days=30.0, clock=_fixed_clock)
    for ev in build_anomaly_evidence(result):
        assert ev.is_apparent_not_confirmed is True


def test_build_anomaly_event_epoch_matches_source() -> None:
    series = _series_with_anomaly_shift()
    result = detect_anomalies(series, baseline_window_days=30.0, clock=_fixed_clock)
    for ev_obj, source in zip(build_anomaly_evidence(result), result.events, strict=True):
        assert ev_obj.event_epoch == source.epoch_datetime


# --- build_conjunction_evidence ---------------------------------------


def test_build_conjunction_empty_input_returns_empty() -> None:
    assert build_conjunction_evidence([]) == []


def test_build_conjunction_emits_two_per_detection_one_per_side() -> None:
    det = _make_conjunction(norad_a=11111, norad_b=22222)
    evs = build_conjunction_evidence([det])
    assert len(evs) == 2
    norads = {e.object_id for e in evs}
    assert norads == {11111, 22222}


def test_build_conjunction_filter_by_target_norad() -> None:
    det = _make_conjunction(norad_a=11111, norad_b=22222)
    evs = build_conjunction_evidence([det], only_for_norad=11111)
    assert len(evs) == 1
    assert evs[0].object_id == 11111


def test_build_conjunction_filter_target_not_in_detection_yields_empty() -> None:
    det = _make_conjunction(norad_a=11111, norad_b=22222)
    evs = build_conjunction_evidence([det], only_for_norad=99999)
    assert evs == []


def test_build_conjunction_evidence_type_correct() -> None:
    det = _make_conjunction(norad_a=11111, norad_b=22222)
    for ev in build_conjunction_evidence([det]):
        assert ev.evidence_type == EVIDENCE_TYPE_CONJUNCTION
        assert ev.source_detector == "conjunction_detection_v01"


def test_build_conjunction_preserves_honesty_payload() -> None:
    det = _make_conjunction(norad_a=11111, norad_b=22222, miss_km=0.123, pc_value=1e-5)
    ev = build_conjunction_evidence([det])[0]
    for required in (
        "miss_distance_km", "pc", "covariance_model_name", "pc_method",
        "sgp4_uncertainty_baseline_km", "combined_hard_body_radius_km",
        "combined_sigma_at_tca_km", "tca_resolution_minutes", "tca_was_refined",
        "other_norad_cat_id", "detection_content_hash", "side",
    ):
        assert required in ev.honesty_payload, f"falta {required}"
    assert ev.honesty_payload["miss_distance_km"] == 0.123
    assert ev.honesty_payload["pc"] == 1e-5


def test_build_conjunction_event_epoch_is_tca() -> None:
    det = _make_conjunction(norad_a=11111, norad_b=22222)
    for ev in build_conjunction_evidence([det]):
        assert ev.event_epoch == det.tca


def test_build_conjunction_evidence_id_distinct_per_side() -> None:
    det = _make_conjunction(norad_a=11111, norad_b=22222)
    evs = build_conjunction_evidence([det])
    assert evs[0].evidence_id != evs[1].evidence_id


def test_build_conjunction_evidence_id_deterministic() -> None:
    det = _make_conjunction(norad_a=11111, norad_b=22222)
    a = [e.evidence_id for e in build_conjunction_evidence([det])]
    b = [e.evidence_id for e in build_conjunction_evidence([det])]
    assert a == b


def test_build_conjunction_is_apparent_not_confirmed_true() -> None:
    det = _make_conjunction(norad_a=1, norad_b=2)
    for ev in build_conjunction_evidence([det]):
        assert ev.is_apparent_not_confirmed is True


def test_build_conjunction_carries_other_norad_in_payload() -> None:
    det = _make_conjunction(norad_a=11111, norad_b=22222)
    evs = build_conjunction_evidence([det])
    by_norad = {e.object_id: e for e in evs}
    assert by_norad[11111].honesty_payload["other_norad_cat_id"] == 22222
    assert by_norad[22222].honesty_payload["other_norad_cat_id"] == 11111


def test_build_conjunction_propagates_analysis_engine_version() -> None:
    det = _make_conjunction(norad_a=1, norad_b=2)
    for ev in build_conjunction_evidence([det]):
        assert ev.analysis_engine_version == det.analysis_engine_version


# --- consumed_source_hashes / provenance por-evidencia (ADR-0043) ------


def _series_with_maneuver_distinct(
    n: int = 20, jump_at: int = 15,
) -> OrbitalElementSeries:
    """Como _series_with_maneuver pero con content_hash_source distinto por
    elemento, para verificar que el par before/after consumido es preciso."""
    els = []
    for i in range(n):
        bump = 1e-2 if i > jump_at else 0.0
        els.append(
            make_element(
                days_offset=float(i),
                mean_motion=15.5 + 1e-7 * i + bump,
                tle_hash=f"{i:064x}",
                content_hash_source=f"{(i + 5000):064x}",
            )
        )
    return OrbitalElementSeries.from_elements(els)


def _series_with_anomaly_distinct(
    n: int = 25, shift_at: int = 21,
) -> OrbitalElementSeries:
    els = []
    for i in range(n):
        bump = 1e-2 if i >= shift_at else 0.0
        els.append(
            make_element(
                days_offset=float(i),
                mean_motion=15.5 + bump,
                tle_hash=f"{i:064x}",
                content_hash_source=f"{(i + 7000):064x}",
            )
        )
    return OrbitalElementSeries.from_elements(els)


def test_build_maneuver_consumed_hashes_are_before_after_pair() -> None:
    series = _series_with_maneuver_distinct()
    result = detect_maneuvers(series, baseline_window_days=30.0, clock=_fixed_clock)
    evs = build_maneuver_evidence(result)
    assert evs
    for ev, src in zip(evs, result.events, strict=True):
        expected = sorted({
            src.content_hash_source_before, src.content_hash_source_after,
        })
        assert ev.honesty_payload["consumed_source_hashes"] == expected
        # Distinct sources → exactamente dos hashes consumidos.
        assert len(ev.honesty_payload["consumed_source_hashes"]) == 2


def test_build_anomaly_consumed_hash_is_observed_point() -> None:
    series = _series_with_anomaly_distinct()
    result = detect_anomalies(series, baseline_window_days=30.0, clock=_fixed_clock)
    evs = build_anomaly_evidence(result)
    assert evs
    for ev, src in zip(evs, result.events, strict=True):
        assert ev.honesty_payload["content_hash_source"] == src.content_hash_source
        assert ev.honesty_payload["consumed_source_hashes"] == [
            src.content_hash_source
        ]


def test_build_conjunction_consumed_hash_is_side_specific() -> None:
    det = _make_conjunction(norad_a=11111, norad_b=22222)
    by_norad = {e.object_id: e for e in build_conjunction_evidence([det])}
    assert by_norad[11111].honesty_payload["consumed_source_hashes"] == [
        det.element_a_content_hash_source
    ]
    assert by_norad[22222].honesty_payload["consumed_source_hashes"] == [
        det.element_b_content_hash_source
    ]
    # El lado a NO arrastra el TLE del objeto b (precisión por-evidencia).
    assert (
        det.element_b_content_hash_source
        not in by_norad[11111].honesty_payload["consumed_source_hashes"]
    )
