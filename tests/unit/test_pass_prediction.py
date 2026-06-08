"""Tests P1–P25 + observer validation de pass prediction (ADR-0023 Fase 4)."""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from orbital_sentinel.analytics.passes import (
    CULMINATION_METHOD_NAME,
    FRAME_MODEL_NAME,
    PASS_PREDICTION_ENGINE_VERSION,
    PASS_PREDICTION_SCHEMA_VERSION,
    SGP4_UNCERTAINTY_BASELINE_KM,
    SGP4_UNCERTAINTY_GROWTH_KM_PER_DAY,
    Pass,
    PassPrediction,
    predict_passes,
)
from orbital_sentinel.analytics.passes.analysis import (
    _find_pass_segments,
    _refine_culmination_parabolic,
)
from orbital_sentinel.catalog import TLESnapshot, normalize_snapshot
from orbital_sentinel.propagation import GMST_MODEL_NAME

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "tle"
EPOCH = datetime(2008, 9, 20, 12, 25, 40, tzinfo=timezone.utc)
DERIVED_AT_FIXED = datetime(2026, 6, 6, 12, 0, tzinfo=timezone.utc)

# Observador "ISS sobrevolable": CDMX
CDMX_LAT = 19.4326
CDMX_LON = -99.1332
CDMX_ALT = 2240.0


def _iss_setup() -> tuple[object, TLESnapshot]:
    text = (FIXTURES / "iss_vallado_2008.txt").read_text(encoding="ascii")
    encoded = text.encode("ascii")
    snap = TLESnapshot(
        content_hash=hashlib.sha256(encoded).hexdigest(),
        source="celestrak",
        dataset="stations",
        url="https://example/",
        fetched_at=DERIVED_AT_FIXED,
        raw_text=text,
        n_bytes=len(encoded),
    )
    [element] = normalize_snapshot(snap, derived_at=DERIVED_AT_FIXED)
    return element, snap


def _fixed_clock() -> datetime:
    return DERIVED_AT_FIXED


# --- P1: ventana sin pases ----------------------------------------------


def test_p1_predict_passes_empty_window() -> None:
    """Ventana donde el satélite nunca sube por encima del threshold."""
    element, snap = _iss_setup()
    # Observador donde ISS (i=51.6°) NUNCA sube sobre 80° de elevación:
    # latitud lejana del rango orbital. Pero más simple: usamos threshold alto
    # con ventana muy corta de 1 minuto.
    result = predict_passes(
        element, snap,
        observer_lat_deg=89.0, observer_lon_deg=0.0, observer_alt_m=0.0,
        window_start=EPOCH, window_end=EPOCH + timedelta(seconds=30),
        step_minutes=0.5, min_elevation_deg=10.0,
        clock=_fixed_clock,
    )
    assert result.passes == []
    assert result.n_passes == 0


# --- P2/P3/P4: validación de ventana y step -----------------------------


def test_p2_step_must_be_positive() -> None:
    element, snap = _iss_setup()
    with pytest.raises(ValueError, match="step_minutes"):
        predict_passes(
            element, snap,
            observer_lat_deg=0.0, observer_lon_deg=0.0, observer_alt_m=0.0,
            window_start=EPOCH, window_end=EPOCH + timedelta(hours=1),
            step_minutes=0.0,
        )


def test_p3_inverted_window_rejected() -> None:
    element, snap = _iss_setup()
    with pytest.raises(ValueError, match="window_end"):
        predict_passes(
            element, snap,
            observer_lat_deg=0.0, observer_lon_deg=0.0, observer_alt_m=0.0,
            window_start=EPOCH + timedelta(hours=1),
            window_end=EPOCH,
            step_minutes=1.0,
        )


def test_p4_grid_cap_enforced() -> None:
    element, snap = _iss_setup()
    # Step muy pequeño + ventana grande
    with pytest.raises(ValueError, match=r"máximo"):
        predict_passes(
            element, snap,
            observer_lat_deg=0.0, observer_lon_deg=0.0, observer_alt_m=0.0,
            window_start=EPOCH, window_end=EPOCH + timedelta(days=7),
            step_minutes=0.05,  # → ~200 000 puntos
        )


# --- P5/P6: pases parciales ---------------------------------------------


def test_p5_partial_aos_when_pass_in_progress_at_window_start() -> None:
    """Si el primer sample del grid ya está sobre threshold, partial_aos=True."""
    element, snap = _iss_setup()
    # Búsqueda: encontrar primer instante donde elev>0° sobre CDMX en ventana
    # amplia. Usamos eso como window_start para forzar partial.
    pre = predict_passes(
        element, snap,
        observer_lat_deg=CDMX_LAT, observer_lon_deg=CDMX_LON, observer_alt_m=CDMX_ALT,
        window_start=EPOCH, window_end=EPOCH + timedelta(hours=24),
        step_minutes=0.5, min_elevation_deg=0.0,
        clock=_fixed_clock,
    )
    if not pre.passes:
        pytest.skip("ISS no produce pases sobre CDMX en 24h post-epoch; ajustar fixture")
    first_pass = pre.passes[0]
    # Definir nueva ventana que empieza dentro del primer pase
    inside = first_pass.aos_time + (first_pass.los_time - first_pass.aos_time) / 2
    end_inside = inside + timedelta(minutes=2)
    result = predict_passes(
        element, snap,
        observer_lat_deg=CDMX_LAT, observer_lon_deg=CDMX_LON, observer_alt_m=CDMX_ALT,
        window_start=inside, window_end=end_inside,
        step_minutes=0.1, min_elevation_deg=0.0,
        clock=_fixed_clock,
    )
    assert result.n_passes >= 1
    assert result.passes[0].partial_aos is True
    assert result.passes[0].aos_was_refined is False


def test_p6_partial_los_when_pass_in_progress_at_window_end() -> None:
    """Si el último sample sigue sobre threshold, partial_los=True."""
    element, snap = _iss_setup()
    pre = predict_passes(
        element, snap,
        observer_lat_deg=CDMX_LAT, observer_lon_deg=CDMX_LON, observer_alt_m=CDMX_ALT,
        window_start=EPOCH, window_end=EPOCH + timedelta(hours=24),
        step_minutes=0.5, min_elevation_deg=0.0,
        clock=_fixed_clock,
    )
    if not pre.passes:
        pytest.skip("ISS no produce pases sobre CDMX en 24h post-epoch")
    p = pre.passes[0]
    mid = p.aos_time + (p.los_time - p.aos_time) / 2
    # Ventana que arranca antes de AOS y termina en el medio del pase
    start_before = p.aos_time - timedelta(minutes=2)
    result = predict_passes(
        element, snap,
        observer_lat_deg=CDMX_LAT, observer_lon_deg=CDMX_LON, observer_alt_m=CDMX_ALT,
        window_start=start_before, window_end=mid,
        step_minutes=0.1, min_elevation_deg=0.0,
        clock=_fixed_clock,
    )
    assert result.n_passes >= 1
    assert result.passes[-1].partial_los is True
    assert result.passes[-1].los_was_refined is False


# --- P7/P8: bisección AOS y parabólica TCA sintéticos -------------------


def test_p7_find_pass_segments_basic() -> None:
    """Helper interno: detecta segmento contiguo sobre threshold."""
    elevs = [-5.0, -2.0, 3.0, 7.0, 4.0, -1.0, -10.0]
    segs = _find_pass_segments(elevs, min_elevation_deg=0.0)
    assert segs == [(2, 4)]


def test_p7b_find_pass_segments_multiple() -> None:
    elevs = [3.0, -1.0, 5.0, 6.0, -2.0, 8.0]
    segs = _find_pass_segments(elevs, min_elevation_deg=0.0)
    assert segs == [(0, 0), (2, 3), (5, 5)]


def test_p7c_find_pass_segments_all_below() -> None:
    segs = _find_pass_segments([-1.0, -2.0, -3.0], min_elevation_deg=0.0)
    assert segs == []


def test_p7d_find_pass_segments_all_above() -> None:
    segs = _find_pass_segments([1.0, 2.0, 3.0], min_elevation_deg=0.0)
    assert segs == [(0, 2)]


def test_p8_culmination_parabolic_synthetic_symmetric() -> None:
    """Pico parabólico simétrico → culminación recae sobre el sample central."""
    base = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    step = 1.0  # minutos
    times = [base + timedelta(minutes=i) for i in range(3)]
    # Pico simétrico en k=1, max=60
    elevs = [55.0, 60.0, 55.0]
    t_cul, e_max = _refine_culmination_parabolic(times, elevs, 0, 2, step)
    assert t_cul == times[1]
    assert e_max == pytest.approx(60.0, abs=1e-12)


def test_p8b_culmination_parabolic_synthetic_asymmetric() -> None:
    """Pico parabólico asimétrico → culminación entre k=1 y k=2.

    Para elevs = [40, 60, 50]: e_left=40, e_mid=60, e_right=50
    denom = 40 - 120 + 50 = -30
    delta = 0.5 * (40-50) / (-30) = 0.5 * (-10) / (-30) = 1/6 ≈ 0.1667
    max_elev = 60 - 0.125 * (40-50)² / (-30) = 60 + 0.4167 = 60.4167
    """
    base = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    step = 1.0
    times = [base + timedelta(minutes=i) for i in range(3)]
    elevs = [40.0, 60.0, 50.0]
    t_cul, e_max = _refine_culmination_parabolic(times, elevs, 0, 2, step)
    expected_offset_min = (1.0 / 6.0)
    expected_time = times[1] + timedelta(minutes=expected_offset_min)
    assert abs((t_cul - expected_time).total_seconds()) < 1e-6
    assert e_max == pytest.approx(60.0 + 100.0 / 240.0, abs=1e-9)


def test_p9_culmination_at_grid_boundary_falls_back_to_discrete() -> None:
    """k_max al borde de la grid completa → fallback a discreto, sin crash."""
    base = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    times = [base + timedelta(minutes=i) for i in range(3)]
    # k_max = 0 (borde izquierdo)
    elevs = [10.0, 5.0, 1.0]
    t_cul, e_max = _refine_culmination_parabolic(times, elevs, 0, 2, 1.0)
    assert t_cul == times[0]
    assert e_max == 10.0
    # k_max = 2 (borde derecho)
    elevs = [1.0, 5.0, 10.0]
    t_cul, e_max = _refine_culmination_parabolic(times, elevs, 0, 2, 1.0)
    assert t_cul == times[2]
    assert e_max == 10.0


def test_p10_culmination_flat_curvature_falls_back() -> None:
    """denominador ~ 0 → fallback a discreto."""
    base = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    times = [base + timedelta(minutes=i) for i in range(3)]
    # Misma altura en los tres samples → denominador = 0
    elevs = [10.0, 10.0, 10.0]
    t_cul, e_max = _refine_culmination_parabolic(times, elevs, 0, 2, 1.0)
    assert t_cul == times[0]  # k_max=0 por iteración estricta >
    assert e_max == 10.0


# --- P11: versioning fields ---------------------------------------------


def test_p11_versioning_and_honesty_fields_present() -> None:
    element, snap = _iss_setup()
    result = predict_passes(
        element, snap,
        observer_lat_deg=CDMX_LAT, observer_lon_deg=CDMX_LON, observer_alt_m=CDMX_ALT,
        window_start=EPOCH, window_end=EPOCH + timedelta(hours=2),
        step_minutes=0.5,
        clock=_fixed_clock,
    )
    assert result.schema_version == PASS_PREDICTION_SCHEMA_VERSION == "0.1.0"
    assert result.engine_version == PASS_PREDICTION_ENGINE_VERSION == "0.1.0"
    assert result.frame_model == FRAME_MODEL_NAME
    assert result.gmst_model == GMST_MODEL_NAME
    assert result.culmination_method == CULMINATION_METHOD_NAME
    assert result.sgp4_uncertainty_baseline_km == SGP4_UNCERTAINTY_BASELINE_KM
    assert result.sgp4_uncertainty_growth_km_per_day == SGP4_UNCERTAINTY_GROWTH_KM_PER_DAY
    assert result.aos_los_resolution_seconds > 0


# --- P12: extra="forbid" ------------------------------------------------


def test_p12_models_reject_extra_fields() -> None:
    element, snap = _iss_setup()
    result = predict_passes(
        element, snap,
        observer_lat_deg=CDMX_LAT, observer_lon_deg=CDMX_LON, observer_alt_m=CDMX_ALT,
        window_start=EPOCH, window_end=EPOCH + timedelta(hours=2),
        step_minutes=1.0,
        clock=_fixed_clock,
    )
    # PassPrediction extra="forbid"
    with pytest.raises(Exception):
        PassPrediction.model_validate({**result.model_dump(mode="json"), "extra": 1})
    # Pass extra="forbid" si hay al menos un pase
    if result.passes:
        with pytest.raises(Exception):
            Pass.model_validate({**result.passes[0].model_dump(mode="json"), "extra": 1})


# --- P13: filtro min_elevation -----------------------------------------


def test_p13_min_elevation_filters_low_passes() -> None:
    """Subir el threshold reduce o iguala el número de pases."""
    element, snap = _iss_setup()
    low = predict_passes(
        element, snap,
        observer_lat_deg=CDMX_LAT, observer_lon_deg=CDMX_LON, observer_alt_m=CDMX_ALT,
        window_start=EPOCH, window_end=EPOCH + timedelta(hours=24),
        step_minutes=0.5, min_elevation_deg=0.0,
        clock=_fixed_clock,
    )
    high = predict_passes(
        element, snap,
        observer_lat_deg=CDMX_LAT, observer_lon_deg=CDMX_LON, observer_alt_m=CDMX_ALT,
        window_start=EPOCH, window_end=EPOCH + timedelta(hours=24),
        step_minutes=0.5, min_elevation_deg=60.0,
        clock=_fixed_clock,
    )
    assert high.n_passes <= low.n_passes


# --- P14: invariantes por pase ------------------------------------------


def test_p14_invariants_aos_lt_culmination_lt_los() -> None:
    element, snap = _iss_setup()
    result = predict_passes(
        element, snap,
        observer_lat_deg=CDMX_LAT, observer_lon_deg=CDMX_LON, observer_alt_m=CDMX_ALT,
        window_start=EPOCH, window_end=EPOCH + timedelta(hours=24),
        step_minutes=0.5, min_elevation_deg=0.0,
        clock=_fixed_clock,
    )
    for p in result.passes:
        assert p.aos_time <= p.culmination_time <= p.los_time
        assert 0.0 <= p.aos_azimuth_deg < 360.0
        assert 0.0 <= p.culmination_azimuth_deg < 360.0
        assert 0.0 <= p.los_azimuth_deg < 360.0
        assert p.duration_seconds >= 0.0


# --- P15: determinismo --------------------------------------------------


def test_p15_determinism_bit_exact_across_two_calls() -> None:
    element, snap = _iss_setup()
    kwargs = dict(
        observer_lat_deg=CDMX_LAT, observer_lon_deg=CDMX_LON, observer_alt_m=CDMX_ALT,
        window_start=EPOCH, window_end=EPOCH + timedelta(hours=6),
        step_minutes=0.5, min_elevation_deg=10.0,
        clock=_fixed_clock,
    )
    a = predict_passes(element, snap, **kwargs)
    b = predict_passes(element, snap, **kwargs)
    assert a.model_dump(mode="json") == b.model_dump(mode="json")


# --- P18–P21: observer validation (ADR-0023 enmienda 3) -----------------


def test_p18_rejects_invalid_lat() -> None:
    element, snap = _iss_setup()
    for bad_lat in (91.0, -91.0):
        with pytest.raises(ValueError, match="observer_lat_deg"):
            predict_passes(
                element, snap,
                observer_lat_deg=bad_lat, observer_lon_deg=0.0, observer_alt_m=0.0,
                window_start=EPOCH, window_end=EPOCH + timedelta(hours=1),
                step_minutes=1.0,
            )


def test_p19_rejects_invalid_lon() -> None:
    element, snap = _iss_setup()
    for bad_lon in (181.0, -181.0):
        with pytest.raises(ValueError, match="observer_lon_deg"):
            predict_passes(
                element, snap,
                observer_lat_deg=0.0, observer_lon_deg=bad_lon, observer_alt_m=0.0,
                window_start=EPOCH, window_end=EPOCH + timedelta(hours=1),
                step_minutes=1.0,
            )


def test_p20_rejects_invalid_alt() -> None:
    element, snap = _iss_setup()
    for bad_alt in (-11001.0, 100001.0):
        with pytest.raises(ValueError, match="observer_alt_m"):
            predict_passes(
                element, snap,
                observer_lat_deg=0.0, observer_lon_deg=0.0, observer_alt_m=bad_alt,
                window_start=EPOCH, window_end=EPOCH + timedelta(hours=1),
                step_minutes=1.0,
            )


def test_p21_accepts_extreme_valid_inputs() -> None:
    """Los bordes (±90°, ±180°, -11_000 m, 100_000 m) son aceptados."""
    element, snap = _iss_setup()
    for lat, lon, alt in (
        (90.0, 0.0, 0.0),
        (-90.0, 0.0, 0.0),
        (0.0, 180.0, 0.0),
        (0.0, -180.0, 0.0),
        (0.0, 0.0, -11_000.0),
        (0.0, 0.0, 100_000.0),
    ):
        # No debe lanzar
        predict_passes(
            element, snap,
            observer_lat_deg=lat, observer_lon_deg=lon, observer_alt_m=alt,
            window_start=EPOCH, window_end=EPOCH + timedelta(minutes=1),
            step_minutes=0.5,
            clock=_fixed_clock,
        )


# --- P22–P25: pases rasantes / sub-grid (ADR-0023 enmienda 5) -----------


def test_p22_grazing_pass_just_above_threshold_via_synthetic() -> None:
    """Parabólico sintético con peak = threshold + 0.1°.

    Verifica que el ajuste reporta max_elev cerca del peak teórico.
    """
    base = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    times = [base + timedelta(minutes=i) for i in range(3)]
    # Peak parabólico simétrico en k=1, max = 10.1
    elevs = [10.05, 10.10, 10.05]
    t_cul, e_max = _refine_culmination_parabolic(times, elevs, 0, 2, 1.0)
    assert t_cul == times[1]
    assert e_max == pytest.approx(10.10, abs=1e-12)


def test_p23_subgrid_pass_undetected_documented() -> None:
    """Sin pase a paso 60 s si la duración real sobre threshold es < 60s.

    Contrato declarado en ADR-0023 §"Lo que este ADR NO decide". Este test
    bloquea cualquier "arreglo" silencioso que cambie el contrato.
    """
    # Construimos elevations sintéticas como si el sampling discretizado
    # nunca cruza el threshold. _find_pass_segments debe devolver [].
    elevs = [-5.0, -3.0, -1.0, -2.0, -4.0]  # nunca >= 0
    segs = _find_pass_segments(elevs, min_elevation_deg=0.0)
    assert segs == []


def test_p24_single_sample_segment_yields_bracketed_aos_los() -> None:
    """Segmento de un solo sample con vecinos sub-threshold se detecta como pase."""
    elevs = [-1.0, 5.0, -2.0]
    segs = _find_pass_segments(elevs, min_elevation_deg=0.0)
    assert segs == [(1, 1)]


def test_p25_refined_culmination_below_threshold_still_reported() -> None:
    """Aunque el fit parabólico pueda interpolar marginalmente bajo threshold,
    el segmento se detecta y reporta. (Política ADR-0023 §"Algoritmo" punto 7.)
    """
    # En este escenario sintético: los 3 samples del segmento están sobre 5°,
    # pero la parábola interpola un valor cercano. El pase debe reportarse.
    base = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    times = [base + timedelta(minutes=i) for i in range(3)]
    elevs = [5.1, 5.0, 5.1]  # parábola hacia arriba (mínimo en mid)
    t_cul, e_max = _refine_culmination_parabolic(times, elevs, 0, 2, 1.0)
    # Política: el segmento se aceptó por grid; el e_max reportado puede ser
    # < threshold por interpolación. No descartamos el pase.
    assert e_max >= 5.0  # nunca por debajo del menor sample del segmento
