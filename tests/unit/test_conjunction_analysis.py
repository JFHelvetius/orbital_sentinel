"""Tests del análisis de conjunción pairwise v0.1 (ADR-0016)."""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from orbital_sentinel.analytics.conjunctions import (
    CONJUNCTION_ENGINE_VERSION,
    CONJUNCTION_SCHEMA_VERSION,
    SGP4_UNCERTAINTY_BASELINE_KM,
    SGP4_UNCERTAINTY_GROWTH_KM_PER_DAY,
    TCA_REFINEMENT_TOLERANCE_SECONDS,
    ConjunctionAnalysis,
    analyze_pairwise_conjunction,
)
from orbital_sentinel.catalog import TLESnapshot, normalize_snapshot

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "tle"
DERIVED_AT = datetime(2026, 6, 3, 12, 0, tzinfo=timezone.utc)
EPOCH = datetime(2008, 9, 20, 12, 25, 40, tzinfo=timezone.utc)


def _make_snapshot_from_fixture(name: str) -> TLESnapshot:
    text = (FIXTURES / name).read_text(encoding="ascii")
    encoded = text.encode("ascii")
    return TLESnapshot(
        content_hash=hashlib.sha256(encoded).hexdigest(),
        source="celestrak",
        dataset=name.replace(".txt", ""),
        url=f"https://example/{name}",
        fetched_at=DERIVED_AT,
        raw_text=text,
        n_bytes=len(encoded),
    )


def _iss_pair():
    snap = _make_snapshot_from_fixture("iss_vallado_2008.txt")
    [element] = normalize_snapshot(snap, derived_at=DERIVED_AT)
    return element, snap


def _multi_pair():
    """Devuelve (ISS, synthetic GEO) del fixture multi_stations.txt."""
    snap = _make_snapshot_from_fixture("multi_stations.txt")
    elements = normalize_snapshot(snap, derived_at=DERIVED_AT)
    return elements, snap


# --- Resultado básico ----------------------------------------------------


def test_same_object_against_itself_yields_zero_miss() -> None:
    """A vs A con mismas líneas → distancia ≈ 0 (los vectores de estado son idénticos)."""
    element, snap = _iss_pair()
    result = analyze_pairwise_conjunction(
        element, snap, element, snap,
        window_start=EPOCH,
        window_end=EPOCH + timedelta(minutes=10),
        step_minutes=2.0,
    )
    assert result.miss_distance_km == pytest.approx(0.0, abs=1e-9)
    assert result.relative_velocity_km_s == pytest.approx(0.0, abs=1e-9)


def test_leo_vs_geo_has_large_miss_distance() -> None:
    """ISS (~400 km LEO) vs synthetic GEO (~36000 km) → miss > 30000 km."""
    elements, snap = _multi_pair()
    iss, geo = elements
    result = analyze_pairwise_conjunction(
        iss, snap, geo, snap,
        window_start=EPOCH,
        window_end=EPOCH + timedelta(hours=2),
        step_minutes=5.0,
    )
    assert result.miss_distance_km > 30000


def test_tca_within_window() -> None:
    elements, snap = _multi_pair()
    iss, geo = elements
    start = EPOCH
    end = EPOCH + timedelta(minutes=30)
    result = analyze_pairwise_conjunction(
        iss, snap, geo, snap,
        window_start=start, window_end=end, step_minutes=5.0,
    )
    assert start <= result.tca <= end


# --- Provenance doble FK (ADR-0016) --------------------------------------


def test_provenance_carries_both_chains() -> None:
    elements, snap = _multi_pair()
    iss, geo = elements
    result = analyze_pairwise_conjunction(
        iss, snap, geo, snap,
        window_start=EPOCH, window_end=EPOCH + timedelta(minutes=10),
        step_minutes=5.0,
    )
    assert result.element_a_content_hash_source == iss.content_hash_source
    assert result.element_a_tle_index == iss.tle_index
    assert result.element_a_tle_content_hash == iss.tle_content_hash
    assert result.element_b_content_hash_source == geo.content_hash_source
    assert result.element_b_tle_index == geo.tle_index
    assert result.element_b_tle_content_hash == geo.tle_content_hash
    assert result.norad_a == iss.norad_cat_id
    assert result.norad_b == geo.norad_cat_id


# --- Régimen de precisión declarado (ADR-0014 enmienda 1) ----------------


def test_sgp4_uncertainty_declared_in_every_result() -> None:
    """ADR-0016: cada resultado lleva el régimen de incertidumbre persistido."""
    element, snap = _iss_pair()
    result = analyze_pairwise_conjunction(
        element, snap, element, snap,
        window_start=EPOCH, window_end=EPOCH + timedelta(minutes=10),
        step_minutes=2.0,
    )
    assert result.sgp4_uncertainty_baseline_km == SGP4_UNCERTAINTY_BASELINE_KM
    assert result.sgp4_uncertainty_growth_km_per_day == SGP4_UNCERTAINTY_GROWTH_KM_PER_DAY
    assert result.tca_resolution_minutes == 2.0


def test_tca_resolution_equals_step_when_not_refinable() -> None:
    """Mismo objeto contra sí mismo: min en borde → fallback discreto."""
    element, snap = _iss_pair()
    for step in (0.5, 1.0, 10.0):
        result = analyze_pairwise_conjunction(
            element, snap, element, snap,
            window_start=EPOCH, window_end=EPOCH + timedelta(minutes=30),
            step_minutes=step,
        )
        assert result.tca_was_refined is False
        assert result.tca_resolution_minutes == step


# --- Versioning ----------------------------------------------------------


def test_engine_and_schema_versions_stamped() -> None:
    element, snap = _iss_pair()
    result = analyze_pairwise_conjunction(
        element, snap, element, snap,
        window_start=EPOCH, window_end=EPOCH + timedelta(minutes=5),
        step_minutes=1.0,
    )
    assert result.engine_version == CONJUNCTION_ENGINE_VERSION
    assert result.schema_version == CONJUNCTION_SCHEMA_VERSION


def test_n_samples_matches_grid_size() -> None:
    element, snap = _iss_pair()
    result = analyze_pairwise_conjunction(
        element, snap, element, snap,
        window_start=EPOCH, window_end=EPOCH + timedelta(minutes=10),
        step_minutes=1.0,
    )
    # [0, 1, ..., 10] minutos = 11 instantes
    assert result.n_samples == 11


# --- Determinismo --------------------------------------------------------


def test_determinism() -> None:
    """Misma entrada → bit-exactness en mismo entorno (ADR-0013)."""
    element, snap = _iss_pair()

    def clk() -> datetime:
        return DERIVED_AT

    a = analyze_pairwise_conjunction(
        element, snap, element, snap,
        window_start=EPOCH, window_end=EPOCH + timedelta(minutes=10),
        step_minutes=2.0, clock=clk,
    )
    b = analyze_pairwise_conjunction(
        element, snap, element, snap,
        window_start=EPOCH, window_end=EPOCH + timedelta(minutes=10),
        step_minutes=2.0, clock=clk,
    )
    assert a.model_dump() == b.model_dump()


# --- Validación defensiva ------------------------------------------------


def test_rejects_invalid_step_zero() -> None:
    element, snap = _iss_pair()
    with pytest.raises(ValueError, match="positivo"):
        analyze_pairwise_conjunction(
            element, snap, element, snap,
            window_start=EPOCH, window_end=EPOCH + timedelta(minutes=10),
            step_minutes=0.0,
        )


def test_rejects_invalid_step_negative() -> None:
    element, snap = _iss_pair()
    with pytest.raises(ValueError, match="positivo"):
        analyze_pairwise_conjunction(
            element, snap, element, snap,
            window_start=EPOCH, window_end=EPOCH + timedelta(minutes=10),
            step_minutes=-1.0,
        )


def test_rejects_inverted_window() -> None:
    element, snap = _iss_pair()
    with pytest.raises(ValueError, match="window_end debe ser"):
        analyze_pairwise_conjunction(
            element, snap, element, snap,
            window_start=EPOCH + timedelta(minutes=10),
            window_end=EPOCH,
            step_minutes=2.0,
        )


def test_rejects_naive_window_times() -> None:
    element, snap = _iss_pair()
    with pytest.raises(ValueError, match="timezone-aware"):
        analyze_pairwise_conjunction(
            element, snap, element, snap,
            window_start=datetime(2008, 9, 20, 12, 0),
            window_end=datetime(2008, 9, 20, 12, 10),
            step_minutes=2.0,
        )


# --- Modelo Pydantic -----------------------------------------------------


def test_model_is_frozen() -> None:
    element, snap = _iss_pair()
    result = analyze_pairwise_conjunction(
        element, snap, element, snap,
        window_start=EPOCH, window_end=EPOCH, step_minutes=1.0,
    )
    with pytest.raises(Exception):
        result.miss_distance_km = 0.0  # type: ignore[misc]


# --- v0.2: refinamiento de TCA por bisección (ADR-0017) ------------------


def test_tca_is_refined_by_default_for_leo_vs_geo() -> None:
    """ISS vs GEO sintético sobre 1h: refinamiento debe activarse."""
    elements, snap = _multi_pair()
    iss, geo = elements
    result = analyze_pairwise_conjunction(
        iss, snap, geo, snap,
        window_start=EPOCH,
        window_end=EPOCH + timedelta(hours=2),
        step_minutes=5.0,
    )
    assert result.tca_was_refined is True
    assert result.tca_resolution_minutes == pytest.approx(
        TCA_REFINEMENT_TOLERANCE_SECONDS / 60.0, abs=1e-9
    )


def test_refine_tca_false_reproduces_v01_behavior() -> None:
    """refine_tca=False → tca_was_refined=False y tca_resolution_minutes=step."""
    elements, snap = _multi_pair()
    iss, geo = elements
    result = analyze_pairwise_conjunction(
        iss, snap, geo, snap,
        window_start=EPOCH,
        window_end=EPOCH + timedelta(hours=2),
        step_minutes=5.0,
        refine_tca=False,
    )
    assert result.tca_was_refined is False
    assert result.tca_resolution_minutes == 5.0


def test_refined_miss_le_discrete_miss() -> None:
    """El TCA refinado debe encontrar miss <= miss del discreto."""
    elements, snap = _multi_pair()
    iss, geo = elements
    refined = analyze_pairwise_conjunction(
        iss, snap, geo, snap,
        window_start=EPOCH, window_end=EPOCH + timedelta(hours=2),
        step_minutes=5.0, refine_tca=True,
    )
    discrete = analyze_pairwise_conjunction(
        iss, snap, geo, snap,
        window_start=EPOCH, window_end=EPOCH + timedelta(hours=2),
        step_minutes=5.0, refine_tca=False,
    )
    assert refined.miss_distance_km <= discrete.miss_distance_km + 1e-9


def test_refined_tca_within_bracket() -> None:
    """TCA refinado debe caer en [t_{k-1}, t_{k+1}] del mínimo discreto."""
    elements, snap = _multi_pair()
    iss, geo = elements
    step = 5.0
    discrete = analyze_pairwise_conjunction(
        iss, snap, geo, snap,
        window_start=EPOCH, window_end=EPOCH + timedelta(hours=1),
        step_minutes=step, refine_tca=False,
    )
    refined = analyze_pairwise_conjunction(
        iss, snap, geo, snap,
        window_start=EPOCH, window_end=EPOCH + timedelta(hours=1),
        step_minutes=step, refine_tca=True,
    )
    bracket_half = timedelta(minutes=step)
    assert refined.tca >= discrete.tca - bracket_half
    assert refined.tca <= discrete.tca + bracket_half


def test_no_refinement_when_minimum_at_window_start() -> None:
    """Si el min cae en index 0, no refinement (no hay t_{-1})."""
    # Same object → min en index 0
    element, snap = _iss_pair()
    result = analyze_pairwise_conjunction(
        element, snap, element, snap,
        window_start=EPOCH, window_end=EPOCH + timedelta(minutes=10),
        step_minutes=2.0,
    )
    assert result.tca_was_refined is False


def test_no_refinement_with_single_sample() -> None:
    """n_samples = 1 → no refinement posible."""
    element, snap = _iss_pair()
    result = analyze_pairwise_conjunction(
        element, snap, element, snap,
        window_start=EPOCH, window_end=EPOCH, step_minutes=5.0,
    )
    assert result.n_samples == 1
    assert result.tca_was_refined is False
    assert result.tca == EPOCH


def test_engine_and_schema_versions_are_v03() -> None:
    """Bump explícito a 0.3.0 por ADR-0020 (Pc + covarianza declarada)."""
    assert CONJUNCTION_ENGINE_VERSION == "0.3.0"
    assert CONJUNCTION_SCHEMA_VERSION == "0.3.0"


def test_refinement_is_deterministic() -> None:
    """Refinamiento determinista: misma entrada → misma TCA refinada."""
    elements, snap = _multi_pair()
    iss, geo = elements

    def clk():
        return DERIVED_AT

    a = analyze_pairwise_conjunction(
        iss, snap, geo, snap,
        window_start=EPOCH, window_end=EPOCH + timedelta(hours=2),
        step_minutes=5.0, clock=clk,
    )
    b = analyze_pairwise_conjunction(
        iss, snap, geo, snap,
        window_start=EPOCH, window_end=EPOCH + timedelta(hours=2),
        step_minutes=5.0, clock=clk,
    )
    assert a.model_dump() == b.model_dump()


# --- v1.0: Pc bajo covarianza declarada (ADR-0020) ------------------------


def test_pc_zero_when_no_radius_declared() -> None:
    """Default: radio combinado = 0 → Pc = 0 (honestidad ADR-0020)."""
    elements, snap = _multi_pair()
    iss, geo = elements
    result = analyze_pairwise_conjunction(
        iss, snap, geo, snap,
        window_start=EPOCH, window_end=EPOCH + timedelta(hours=2),
        step_minutes=10.0,
    )
    assert result.pc == 0.0
    assert result.combined_hard_body_radius_km == 0.0


def test_pc_positive_when_radius_declared_and_miss_finite() -> None:
    """Con R declarado, Pc > 0 (aunque pueda ser muy pequeño)."""
    element, snap = _iss_pair()
    result = analyze_pairwise_conjunction(
        element, snap, element, snap,
        window_start=EPOCH, window_end=EPOCH + timedelta(minutes=10),
        step_minutes=2.0,
        combined_hard_body_radius_km=0.01,  # 10 metros combinados
    )
    # Para mismo objeto: miss ≈ 0 y R > 0 → Pc > 0
    assert result.pc > 0
    assert result.pc <= 1.0


def test_pc_in_unit_interval() -> None:
    """Pc siempre en [0, 1]."""
    elements, snap = _multi_pair()
    iss, geo = elements
    for r_km in (0.0, 0.001, 0.01, 0.1):
        result = analyze_pairwise_conjunction(
            iss, snap, geo, snap,
            window_start=EPOCH, window_end=EPOCH + timedelta(hours=2),
            step_minutes=10.0,
            combined_hard_body_radius_km=r_km,
        )
        assert 0.0 <= result.pc <= 1.0


def test_assumption_fields_persisted() -> None:
    """ADR-0020 P2: cada resultado lleva las assumption fields."""
    element, snap = _iss_pair()
    result = analyze_pairwise_conjunction(
        element, snap, element, snap,
        window_start=EPOCH, window_end=EPOCH + timedelta(minutes=10),
        step_minutes=2.0,
        combined_hard_body_radius_km=0.005,
    )
    assert result.covariance_model_name == "tle_isotropic_spherical_v1"
    assert result.covariance_baseline_sigma_km == 1.0
    assert result.covariance_growth_sigma_km_per_day == 1.0
    assert result.combined_sigma_at_tca_km > 0
    assert result.pc_method == "foster_1992_fast_approximation"


def test_combined_sigma_reflects_distance_from_epoch() -> None:
    """combined_sigma debe ser mayor en una ventana lejana del epoch."""
    element, snap = _iss_pair()
    near = analyze_pairwise_conjunction(
        element, snap, element, snap,
        window_start=EPOCH, window_end=EPOCH + timedelta(minutes=10),
        step_minutes=2.0,
    )
    far = analyze_pairwise_conjunction(
        element, snap, element, snap,
        window_start=EPOCH + timedelta(days=1),
        window_end=EPOCH + timedelta(days=1, minutes=10),
        step_minutes=2.0,
    )
    assert far.combined_sigma_at_tca_km > near.combined_sigma_at_tca_km


def test_model_rejects_extra_fields() -> None:
    element, snap = _iss_pair()
    result = analyze_pairwise_conjunction(
        element, snap, element, snap,
        window_start=EPOCH, window_end=EPOCH, step_minutes=1.0,
    )
    with pytest.raises(Exception):
        ConjunctionAnalysis.model_validate({**result.model_dump(), "extra": 0})
