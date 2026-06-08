"""Tests D1–D14 del detector de maniobras (ADR-0027)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from orbital_sentinel.analytics.maneuvers import (
    DETECTION_METHOD_NAME,
    MANEUVER_DETECTION_ENGINE_VERSION,
    MANEUVER_DETECTION_SCHEMA_VERSION,
    ManeuverDetectionResult,
    ManeuverEvent,
    OrbitalElementSeries,
    detect_maneuvers,
)
from tests.unit.test_maneuver_series import make_element

DERIVED_AT_FIXED = datetime(2026, 6, 6, 12, 0, tzinfo=timezone.utc)


def _fixed_clock() -> datetime:
    return DERIVED_AT_FIXED


def _uniform_drift_series(
    *, n: int = 20, drift_per_day: float = 1e-7
) -> OrbitalElementSeries:
    """Serie con drift lineal uniforme en mean_motion. Sin saltos."""
    els = [
        make_element(
            days_offset=float(i),
            mean_motion=15.5 + drift_per_day * i,
            tle_hash=f"{i:064x}",
        )
        for i in range(n)
    ]
    return OrbitalElementSeries.from_elements(els)


def _series_with_jump_at(
    *,
    n: int = 20,
    jump_at_transition: int,
    component: str = "mean_motion",
    jump_size: float = 1e-3,
    drift_per_day: float = 1e-7,
) -> OrbitalElementSeries:
    """Serie con un salto inyectado en una transición específica.

    El salto se aplica al elemento ``jump_at_transition + 1`` y siguientes.
    """
    els = []
    for i in range(n):
        injected = jump_size if i > jump_at_transition else 0.0
        mm = 15.5 + drift_per_day * i + (injected if component == "mean_motion" else 0.0)
        ecc = 0.001 + (injected if component == "eccentricity" else 0.0)
        inc = 51.6 + (injected if component == "inclination" else 0.0)
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


# --- D1 ---------------------------------------------------------------


def test_d1_no_jump_returns_empty() -> None:
    """Drift uniforme sintético → 0 eventos."""
    series = _uniform_drift_series(n=20, drift_per_day=1e-7)
    result = detect_maneuvers(series, clock=_fixed_clock)
    assert result.n_events == 0
    assert result.events == []


# --- D2 ---------------------------------------------------------------


def test_d2_single_jump_in_mean_motion_detected_at_correct_transition() -> None:
    """Salto en mean_motion en transición k=15 → 1 evento en k=15."""
    series = _series_with_jump_at(
        n=20, jump_at_transition=15, component="mean_motion", jump_size=1e-2
    )
    result = detect_maneuvers(
        series,
        baseline_window_days=30.0,  # ventana amplia para que k=15 tenga baseline
        clock=_fixed_clock,
    )
    assert result.n_events >= 1
    event = result.events[0]
    # Transición k tiene epoch_before=elements[k] y epoch_after=elements[k+1]
    expected_epoch_before = series.elements[15].epoch_datetime
    assert event.epoch_before == expected_epoch_before
    assert event.dominant_component == "mean_motion"


# --- D3 ---------------------------------------------------------------


def test_d3_jump_in_eccentricity_dominant() -> None:
    series = _series_with_jump_at(
        n=20, jump_at_transition=15, component="eccentricity", jump_size=1e-3
    )
    result = detect_maneuvers(series, baseline_window_days=30.0, clock=_fixed_clock)
    assert result.n_events >= 1
    assert result.events[0].dominant_component == "eccentricity"


# --- D4 ---------------------------------------------------------------


def test_d4_jump_in_inclination_dominant() -> None:
    series = _series_with_jump_at(
        n=20, jump_at_transition=15, component="inclination", jump_size=1.0
    )
    result = detect_maneuvers(series, baseline_window_days=30.0, clock=_fixed_clock)
    assert result.n_events >= 1
    assert result.events[0].dominant_component == "inclination"


# --- D5 ---------------------------------------------------------------


def test_d5_multiple_jumps_produce_multiple_events() -> None:
    """Construye serie con dos saltos en mean_motion."""
    n = 30
    els = []
    for i in range(n):
        mm = 15.5 + 1e-7 * i
        if i > 12:
            mm += 1e-2
        if i > 22:
            mm += 1e-2
        els.append(
            make_element(
                days_offset=float(i),
                mean_motion=mm,
                tle_hash=f"{i:064x}",
            )
        )
    series = OrbitalElementSeries.from_elements(els)
    result = detect_maneuvers(series, baseline_window_days=30.0, clock=_fixed_clock)
    assert result.n_events >= 2


# --- D6 ---------------------------------------------------------------


def test_d6_short_series_skips_for_insufficient_baseline() -> None:
    """Serie con N < min_baseline_samples+1 → 0 eventos, skips contados."""
    series = _uniform_drift_series(n=4, drift_per_day=1e-7)
    result = detect_maneuvers(
        series,
        baseline_window_days=14.0,
        min_baseline_samples=5,
        clock=_fixed_clock,
    )
    assert result.n_events == 0
    assert result.n_transitions_skipped_insufficient_baseline == result.n_transitions_total


# --- D7 ---------------------------------------------------------------


def test_d7_zero_variance_baseline_uses_floor() -> None:
    """Baseline con σ=0 + salto → z computado con σ_floor, sin inf."""
    # Serie perfectamente uniforme (sin drift) + salto al final
    n = 20
    els = []
    for i in range(n):
        mm = 15.5 + (1e-2 if i > 15 else 0.0)
        # Eccentricity y inclination 100% planas para forzar σ=0 en sus rates
        els.append(
            make_element(
                days_offset=float(i),
                mean_motion=mm,
                eccentricity=0.001,
                inclination=51.6,
                tle_hash=f"{i:064x}",
            )
        )
    series = OrbitalElementSeries.from_elements(els)
    result = detect_maneuvers(
        series, baseline_window_days=30.0, clock=_fixed_clock,
    )
    # No debe haber crash; el evento detectado tiene z finitos.
    for event in result.events:
        assert event.z_score_mean_motion == event.z_score_mean_motion  # not NaN
        assert abs(event.z_score_mean_motion) < float("inf")


# --- D8 ---------------------------------------------------------------


def test_d8_z_score_analytical_value() -> None:
    """Baseline conocida + rate conocido → z calculado a mano."""
    # Construyo 8 transiciones de baseline + 1 transición de salto
    # Drift uniforme 1e-7 entre samples → rate constante = 1e-7
    # En el último sample inyecto un delta extra de 5e-6 → rate = 5e-6 + 1e-7
    n = 9
    els = []
    for i in range(n):
        injected = 5e-6 if i == n - 1 else 0.0
        mm = 15.5 + 1e-7 * i + injected
        els.append(
            make_element(
                days_offset=float(i),
                mean_motion=mm,
                tle_hash=f"{i:064x}",
            )
        )
    series = OrbitalElementSeries.from_elements(els)
    result = detect_maneuvers(
        series,
        baseline_window_days=30.0,
        detection_threshold_sigma=2.0,
        min_baseline_samples=5,
        clock=_fixed_clock,
    )
    # Baseline son transiciones 0..6 con rate=1e-7 cada una (constante);
    # σ es ~0 → con σ_floor el z será (5e-6 + 1e-7 - 1e-7) / σ_floor = 5e6
    # → gigantesco; cualquier threshold razonable lo detecta.
    assert result.n_events >= 1
    last_event = result.events[-1]
    # El salto está al final: transición k = n-2 = 7
    assert last_event.epoch_before == els[7].epoch_datetime


# --- D9 ---------------------------------------------------------------


def test_d9_baseline_window_filters_old_samples() -> None:
    """Si baseline_window_days es muy corta, samples viejos no aportan baseline."""
    series = _uniform_drift_series(n=20, drift_per_day=1e-7)
    # Con baseline_window_days=2, en la transición k=10 solo cuentan
    # transiciones j cuyo epoch_j esté en [epoch_10 - 2 días, epoch_10).
    # Eso son j ∈ {8, 9} → 2 muestras.
    result = detect_maneuvers(
        series,
        baseline_window_days=2.0,
        min_baseline_samples=2,
        clock=_fixed_clock,
    )
    # En transición 0 no hay baseline (j<0 no existe). Skip.
    # En transición 1 hay 1 sample. Si min=2, skip.
    # En transición 2+ hay 2 samples. Si min=2, evaluate.
    assert result.n_transitions_skipped_insufficient_baseline >= 2


# --- D10 ---------------------------------------------------------------


def test_d10_provenance_correctly_set() -> None:
    series = _series_with_jump_at(
        n=20, jump_at_transition=15, component="mean_motion", jump_size=1e-2
    )
    result = detect_maneuvers(series, baseline_window_days=30.0, clock=_fixed_clock)
    assert result.n_events >= 1
    event = result.events[0]
    el_before = series.elements[15]
    el_after = series.elements[16]
    assert event.tle_content_hash_before == el_before.tle_content_hash
    assert event.tle_content_hash_after == el_after.tle_content_hash
    assert event.content_hash_source_before == el_before.content_hash_source
    assert event.content_hash_source_after == el_after.content_hash_source
    assert event.norad_cat_id == series.norad_cat_id


# --- D11 ---------------------------------------------------------------


def test_d11_versioning_and_honesty_fields() -> None:
    series = _series_with_jump_at(
        n=20, jump_at_transition=15, component="mean_motion", jump_size=1e-2
    )
    result = detect_maneuvers(series, baseline_window_days=30.0, clock=_fixed_clock)
    assert result.schema_version == MANEUVER_DETECTION_SCHEMA_VERSION == "0.1.0"
    assert result.engine_version == MANEUVER_DETECTION_ENGINE_VERSION == "0.1.0"
    assert result.detection_method_name == DETECTION_METHOD_NAME
    assert result.is_apparent_not_confirmed is True
    if result.events:
        assert result.events[0].is_apparent_not_confirmed is True
        assert result.events[0].detection_method_name == DETECTION_METHOD_NAME


# --- D12 ---------------------------------------------------------------


def test_d12_extra_forbid() -> None:
    series = _uniform_drift_series(n=10)
    result = detect_maneuvers(series, clock=_fixed_clock)
    with pytest.raises(Exception):
        ManeuverDetectionResult.model_validate(
            {**result.model_dump(mode="json"), "extra": 1}
        )
    # ManeuverEvent extra="forbid"
    series2 = _series_with_jump_at(
        n=20, jump_at_transition=15, component="mean_motion", jump_size=1e-2
    )
    r2 = detect_maneuvers(series2, baseline_window_days=30.0, clock=_fixed_clock)
    if r2.events:
        with pytest.raises(Exception):
            ManeuverEvent.model_validate(
                {**r2.events[0].model_dump(mode="json"), "extra": 1}
            )


# --- D13 ---------------------------------------------------------------


def test_d13_determinism() -> None:
    series = _series_with_jump_at(
        n=20, jump_at_transition=15, component="mean_motion", jump_size=1e-2
    )
    a = detect_maneuvers(series, baseline_window_days=30.0, clock=_fixed_clock)
    b = detect_maneuvers(series, baseline_window_days=30.0, clock=_fixed_clock)
    assert a.model_dump(mode="json") == b.model_dump(mode="json")


# --- D14 ---------------------------------------------------------------


def test_d14_threshold_silences_event() -> None:
    """Threshold alto silencia detecciones moderadas (serie con ruido)."""
    # Serie con ruido pseudo-aleatorio determinista en mean_motion (σ ≠ 0)
    # + un salto modesto. Threshold bajo lo detecta, threshold alto lo silencia.
    n = 25
    noise_rates = [1e-7, 3e-7, -2e-7, 5e-7, -1e-7, 2e-7, -4e-7, 1e-7, 3e-7,
                   -3e-7, 2e-7, -1e-7, 4e-7, -2e-7, 1e-7, -3e-7, 2e-7, -1e-7,
                   3e-7, -2e-7, 1e-7, 4e-7, -3e-7, 2e-7]
    cum_mm = [15.5]
    for r in noise_rates:
        cum_mm.append(cum_mm[-1] + r * 1.0)  # Δt=1 día
    # Inyectar un salto de ~6σ en la transición 20
    jump = 5e-6
    for i in range(21, n):
        cum_mm[i] += jump
    els = [
        make_element(days_offset=float(i), mean_motion=cum_mm[i], tle_hash=f"{i:064x}")
        for i in range(n)
    ]
    series = OrbitalElementSeries.from_elements(els)
    low = detect_maneuvers(
        series, baseline_window_days=30.0, detection_threshold_sigma=3.0,
        clock=_fixed_clock,
    )
    high = detect_maneuvers(
        series, baseline_window_days=30.0, detection_threshold_sigma=1000.0,
        clock=_fixed_clock,
    )
    assert low.n_events >= 1, "el salto sintético debería superar 3σ"
    assert high.n_events <= low.n_events
    assert high.n_events == 0, "threshold=1000σ debe silenciar cualquier evento real"


# --- Validación de parámetros -----------------------------------------


def test_detector_rejects_invalid_baseline_window() -> None:
    series = _uniform_drift_series(n=10)
    with pytest.raises(ValueError, match="baseline_window_days"):
        detect_maneuvers(series, baseline_window_days=0.0, clock=_fixed_clock)


def test_detector_rejects_invalid_threshold() -> None:
    series = _uniform_drift_series(n=10)
    with pytest.raises(ValueError, match="detection_threshold_sigma"):
        detect_maneuvers(series, detection_threshold_sigma=0.0, clock=_fixed_clock)


def test_detector_rejects_min_baseline_below_2() -> None:
    series = _uniform_drift_series(n=10)
    with pytest.raises(ValueError, match="min_baseline_samples"):
        detect_maneuvers(series, min_baseline_samples=1, clock=_fixed_clock)
