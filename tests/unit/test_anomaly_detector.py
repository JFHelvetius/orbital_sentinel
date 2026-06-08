"""Tests del detector de anomalías (ADR-0028)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from orbital_sentinel.analytics.anomalies import (
    ANOMALY_DETECTION_ENGINE_VERSION,
    ANOMALY_DETECTION_SCHEMA_VERSION,
    AVAILABLE_FEATURES,
    DETECTION_METHOD_NAME,
    AnomalyDetectionConfig,
    AnomalyDetectionResult,
    AnomalyEvent,
    UnknownFeatureError,
    detect_anomalies,
)
from orbital_sentinel.analytics.maneuvers import OrbitalElementSeries
from tests.unit.test_maneuver_series import make_element

DERIVED_AT_FIXED = datetime(2026, 6, 6, 12, 0, tzinfo=timezone.utc)


def _fixed_clock() -> datetime:
    return DERIVED_AT_FIXED


def _steady_series(n: int = 20) -> OrbitalElementSeries:
    """Serie completamente estática (sin drift, sin saltos)."""
    els = [
        make_element(
            days_offset=float(i),
            mean_motion=15.5,
            eccentricity=0.001,
            inclination=51.6,
            tle_hash=f"{i:064x}",
        )
        for i in range(n)
    ]
    return OrbitalElementSeries.from_elements(els)


def _series_with_value_shift(
    n: int = 20,
    shift_at: int = 15,
    feature: str = "mean_motion",
    shift_size: float = 1e-2,
) -> OrbitalElementSeries:
    """Serie con un cambio escalonado de valor a partir del índice ``shift_at``."""
    els = []
    for i in range(n):
        bump = shift_size if i >= shift_at else 0.0
        mm = 15.5 + (bump if feature == "mean_motion" else 0.0)
        ecc = 0.001 + (bump if feature == "eccentricity" else 0.0)
        inc = 51.6 + (bump if feature == "inclination_deg" else 0.0)
        els.append(
            make_element(
                days_offset=float(i),
                mean_motion=mm,
                eccentricity=ecc,
                inclination=inc,
                tle_hash=f"{i:064x}",
            )
        )
    return OrbitalElementSeries.from_elements(els)


# --- 1. Detector correctness ------------------------------------------


def test_detector_steady_series_no_events() -> None:
    series = _steady_series(n=20)
    result = detect_anomalies(series, clock=_fixed_clock)
    assert result.total_anomalies_found == 0
    assert result.events == []


def test_detector_detects_mean_motion_shift() -> None:
    series = _series_with_value_shift(feature="mean_motion", shift_size=1e-2)
    result = detect_anomalies(
        series, baseline_window_days=30.0, clock=_fixed_clock,
    )
    assert result.total_anomalies_found >= 1
    feature_names = {ev.feature_name for ev in result.events}
    assert "mean_motion" in feature_names


def test_detector_detects_eccentricity_shift() -> None:
    series = _series_with_value_shift(feature="eccentricity", shift_size=1e-3)
    result = detect_anomalies(series, baseline_window_days=30.0, clock=_fixed_clock)
    assert any(ev.feature_name == "eccentricity" for ev in result.events)


def test_detector_detects_inclination_shift() -> None:
    series = _series_with_value_shift(feature="inclination_deg", shift_size=1.0)
    result = detect_anomalies(series, baseline_window_days=30.0, clock=_fixed_clock)
    assert any(ev.feature_name == "inclination_deg" for ev in result.events)


def test_detector_detects_altitude_via_mean_motion_change() -> None:
    """Una bajada de mean_motion sostenida sube la altitud → la feature
    derivada también debería detectarse."""
    series = _series_with_value_shift(feature="mean_motion", shift_size=1e-2)
    result = detect_anomalies(series, baseline_window_days=30.0, clock=_fixed_clock)
    feature_names = {ev.feature_name for ev in result.events}
    # Probable: tanto mean_motion como altitude_km muestran z elevados
    assert "altitude_km" in feature_names


# --- 2. Empty / minimal history ----------------------------------------


def test_detector_min_series_two_elements_returns_no_events() -> None:
    """Con N=2 nunca hay baseline suficiente para min_baseline_samples ≥ 2."""
    series = _steady_series(n=2)
    result = detect_anomalies(
        series, min_baseline_samples=2, clock=_fixed_clock,
    )
    assert result.total_anomalies_found == 0


def test_detector_first_element_always_skipped() -> None:
    """El primer elemento de la serie no tiene historia previa: skip."""
    series = _steady_series(n=10)
    result = detect_anomalies(series, clock=_fixed_clock)
    # No hay evento cuyo epoch == series_start_epoch
    assert all(ev.epoch_datetime != series.series_start_epoch for ev in result.events)


# --- 3. Insufficient baseline ------------------------------------------


def test_detector_insufficient_baseline_counted_in_skips() -> None:
    """Serie con < min_baseline_samples elements útiles → todos skip."""
    series = _steady_series(n=4)
    result = detect_anomalies(
        series, min_baseline_samples=5, clock=_fixed_clock,
    )
    # 4 elementos × 4 features = 16 evaluaciones potenciales, todas skip
    assert result.total_evaluations_skipped_insufficient_baseline > 0
    assert result.total_evaluations == 0
    assert result.total_anomalies_found == 0


def test_detector_short_baseline_window_filters_old_samples() -> None:
    """Si baseline_window_days=2, los samples lejanos no aportan."""
    series = _steady_series(n=20)
    result = detect_anomalies(
        series, baseline_window_days=2.0, min_baseline_samples=2, clock=_fixed_clock,
    )
    assert result.total_evaluations_skipped_insufficient_baseline > 0


# --- 4. Deterministic ordering -----------------------------------------


def test_detector_events_ordered_by_epoch_then_feature_name() -> None:
    """Eventos siempre ordenados (epoch asc, feature_name asc)."""
    series = _series_with_value_shift(feature="mean_motion", shift_size=1e-2)
    result = detect_anomalies(series, baseline_window_days=30.0, clock=_fixed_clock)
    epochs_and_features = [(ev.epoch_datetime, ev.feature_name) for ev in result.events]
    assert epochs_and_features == sorted(epochs_and_features)


# --- 5. Reproducibility ------------------------------------------------


def test_detector_deterministic_across_runs() -> None:
    series = _series_with_value_shift(feature="mean_motion", shift_size=1e-2)
    a = detect_anomalies(series, baseline_window_days=30.0, clock=_fixed_clock)
    b = detect_anomalies(series, baseline_window_days=30.0, clock=_fixed_clock)
    assert a.model_dump(mode="json") == b.model_dump(mode="json")


# --- 6. Anomaly model validation ---------------------------------------


def test_event_extra_forbid() -> None:
    series = _series_with_value_shift()
    result = detect_anomalies(series, baseline_window_days=30.0, clock=_fixed_clock)
    if result.events:
        with pytest.raises(Exception):
            AnomalyEvent.model_validate(
                {**result.events[0].model_dump(mode="json"), "extra": 1}
            )


def test_result_extra_forbid() -> None:
    series = _steady_series(n=10)
    result = detect_anomalies(series, clock=_fixed_clock)
    with pytest.raises(Exception):
        AnomalyDetectionResult.model_validate(
            {**result.model_dump(mode="json"), "extra": 1}
        )


def test_config_extra_forbid() -> None:
    series = _steady_series(n=10)
    result = detect_anomalies(series, clock=_fixed_clock)
    with pytest.raises(Exception):
        AnomalyDetectionConfig.model_validate(
            {**result.configuration_used.model_dump(mode="json"), "extra": 1}
        )


def test_event_required_fields_present_post_detection() -> None:
    series = _series_with_value_shift()
    result = detect_anomalies(series, baseline_window_days=30.0, clock=_fixed_clock)
    assert result.events, "este test exige al menos un evento sintético"
    ev = result.events[0]
    assert ev.object_id  # no vacío
    assert isinstance(ev.norad_cat_id, int)
    assert isinstance(ev.epoch_datetime, datetime)
    assert ev.feature_name in AVAILABLE_FEATURES
    assert isinstance(ev.anomaly_score, float)
    assert ev.n_baseline_samples >= 1
    assert ev.is_apparent_not_confirmed is True


def test_event_object_id_uses_object_name_when_present() -> None:
    series = _series_with_value_shift()
    result = detect_anomalies(series, baseline_window_days=30.0, clock=_fixed_clock)
    for ev in result.events:
        # make_element pone object_name=f"SAT-{norad}"
        assert ev.object_id.startswith("SAT-")


# --- 7. CLI behavior (covered en test_cli_anomalies.py integration) ---


# --- 8. Honesty fields presence ----------------------------------------


def test_result_honesty_and_versioning_fields() -> None:
    series = _series_with_value_shift()
    result = detect_anomalies(series, baseline_window_days=30.0, clock=_fixed_clock)
    assert result.schema_version == ANOMALY_DETECTION_SCHEMA_VERSION == "0.1.0"
    assert result.analysis_engine_version == ANOMALY_DETECTION_ENGINE_VERSION == "0.1.0"
    assert result.is_apparent_not_confirmed is True
    assert result.configuration_used.detection_method_name == DETECTION_METHOD_NAME


def test_event_carries_full_honesty_payload() -> None:
    series = _series_with_value_shift()
    result = detect_anomalies(series, baseline_window_days=30.0, clock=_fixed_clock)
    if result.events:
        ev = result.events[0]
        assert ev.detection_method_name == DETECTION_METHOD_NAME
        assert ev.baseline_window_days > 0
        assert ev.threshold_sigma > 0
        assert ev.n_baseline_samples >= 1
        assert ev.is_apparent_not_confirmed is True
        assert ev.analysis_engine_version == ANOMALY_DETECTION_ENGINE_VERSION


def test_configuration_used_persists_features_used() -> None:
    series = _steady_series(n=10)
    result = detect_anomalies(
        series, features=("mean_motion", "eccentricity"), clock=_fixed_clock,
    )
    assert result.configuration_used.features_used == ["mean_motion", "eccentricity"]


# --- 9. Baseline calculations ------------------------------------------


def test_anomaly_score_signed_positive_for_upward_shift() -> None:
    """Un salto hacia arriba produce z > 0."""
    series = _series_with_value_shift(feature="mean_motion", shift_size=1e-2)
    result = detect_anomalies(series, baseline_window_days=30.0, clock=_fixed_clock)
    mm_events = [ev for ev in result.events if ev.feature_name == "mean_motion"]
    assert mm_events
    assert mm_events[0].anomaly_score > 0


def test_anomaly_score_signed_negative_for_downward_shift() -> None:
    series = _series_with_value_shift(feature="mean_motion", shift_size=-1e-2)
    result = detect_anomalies(series, baseline_window_days=30.0, clock=_fixed_clock)
    mm_events = [ev for ev in result.events if ev.feature_name == "mean_motion"]
    assert mm_events
    assert mm_events[0].anomaly_score < 0


def test_baseline_mean_and_stddev_finite() -> None:
    series = _series_with_value_shift()
    result = detect_anomalies(series, baseline_window_days=30.0, clock=_fixed_clock)
    for ev in result.events:
        assert ev.baseline_mean == ev.baseline_mean  # not NaN
        assert ev.baseline_stddev >= 0.0
        assert abs(ev.baseline_mean) < float("inf")


# --- 10. Threshold edge cases ------------------------------------------


def test_high_threshold_silences_events() -> None:
    """Una serie con ruido + shift moderado: threshold bajo detecta, alto silencia."""
    n = 25
    noise = [0.0, 1e-7, -2e-7, 5e-7, -1e-7, 3e-7, -4e-7, 1e-7, 2e-7, -3e-7,
             2e-7, -1e-7, 3e-7, -2e-7, 1e-7, -3e-7, 2e-7, -1e-7, 4e-7, -2e-7,
             1e-7, 3e-7, -3e-7, 2e-7, -1e-7]
    els = []
    for i in range(n):
        bump = 5e-6 if i >= 22 else 0.0
        mm = 15.5 + noise[i] + bump
        els.append(make_element(days_offset=float(i), mean_motion=mm, tle_hash=f"{i:064x}"))
    series = OrbitalElementSeries.from_elements(els)
    low = detect_anomalies(
        series, baseline_window_days=30.0, threshold_sigma=3.0,
        features=("mean_motion",), clock=_fixed_clock,
    )
    high = detect_anomalies(
        series, baseline_window_days=30.0, threshold_sigma=1000.0,
        features=("mean_motion",), clock=_fixed_clock,
    )
    assert low.total_anomalies_found >= 1
    assert high.total_anomalies_found == 0


def test_zero_variance_baseline_uses_floor_without_crash() -> None:
    series = _series_with_value_shift(feature="mean_motion", shift_size=1e-3)
    result = detect_anomalies(series, baseline_window_days=30.0, clock=_fixed_clock)
    for ev in result.events:
        assert abs(ev.anomaly_score) < float("inf")
        assert ev.anomaly_score == ev.anomaly_score  # not NaN


# --- 11. Serialization stability ---------------------------------------


def test_result_roundtrips_through_model_dump_validate() -> None:
    series = _series_with_value_shift()
    result = detect_anomalies(series, baseline_window_days=30.0, clock=_fixed_clock)
    raw = result.model_dump(mode="json")
    rehydrated = AnomalyDetectionResult.model_validate(raw)
    assert rehydrated.model_dump(mode="json") == raw


def test_event_roundtrips_through_model_dump_validate() -> None:
    series = _series_with_value_shift()
    result = detect_anomalies(series, baseline_window_days=30.0, clock=_fixed_clock)
    if result.events:
        raw = result.events[0].model_dump(mode="json")
        rehydrated = AnomalyEvent.model_validate(raw)
        assert rehydrated.model_dump(mode="json") == raw


# --- 12. Engine version propagation ------------------------------------


def test_engine_version_consistent_top_level_and_per_event() -> None:
    series = _series_with_value_shift()
    result = detect_anomalies(series, baseline_window_days=30.0, clock=_fixed_clock)
    for ev in result.events:
        assert ev.analysis_engine_version == result.analysis_engine_version


# --- 13. Input validation ----------------------------------------------


def test_rejects_invalid_baseline_window() -> None:
    series = _steady_series(n=10)
    with pytest.raises(ValueError, match="baseline_window_days"):
        detect_anomalies(series, baseline_window_days=0.0, clock=_fixed_clock)


def test_rejects_invalid_threshold() -> None:
    series = _steady_series(n=10)
    with pytest.raises(ValueError, match="threshold_sigma"):
        detect_anomalies(series, threshold_sigma=-1.0, clock=_fixed_clock)


def test_rejects_min_baseline_below_2() -> None:
    series = _steady_series(n=10)
    with pytest.raises(ValueError, match="min_baseline_samples"):
        detect_anomalies(series, min_baseline_samples=1, clock=_fixed_clock)


def test_rejects_invalid_sigma_floor() -> None:
    series = _steady_series(n=10)
    with pytest.raises(ValueError, match="sigma_floor"):
        detect_anomalies(series, sigma_floor=0.0, clock=_fixed_clock)


def test_rejects_empty_features() -> None:
    series = _steady_series(n=10)
    with pytest.raises(ValueError, match="features"):
        detect_anomalies(series, features=(), clock=_fixed_clock)


def test_rejects_unknown_feature() -> None:
    series = _steady_series(n=10)
    with pytest.raises(UnknownFeatureError):
        detect_anomalies(
            series, features=("altitude_km", "not_a_feature"), clock=_fixed_clock,
        )


# --- 14. Counts auditables --------------------------------------------


def test_counts_consistent_total_objects_and_anomalies() -> None:
    series = _series_with_value_shift()
    result = detect_anomalies(series, baseline_window_days=30.0, clock=_fixed_clock)
    assert result.total_objects_analyzed == 1
    assert result.total_anomalies_found == len(result.events)
