"""Tests del módulo de probabilidad de colisión (ADR-0020 Pc v1.0)."""

from __future__ import annotations

import math

import pytest

from orbital_sentinel.analytics.conjunctions import (
    COVARIANCE_BASELINE_SIGMA_KM,
    COVARIANCE_GROWTH_SIGMA_KM_PER_DAY,
    COVARIANCE_MODEL_NAME,
    PC_METHOD_NAME,
    combined_sigma_at_tca_km,
    pc_foster_fast,
    sigma_tle_isotropic_km,
)

# --- sigma_tle_isotropic_km ----------------------------------------------


def test_sigma_at_epoch_is_baseline() -> None:
    """En Δt = 0 → σ = σ₀."""
    assert sigma_tle_isotropic_km(0.0) == COVARIANCE_BASELINE_SIGMA_KM


def test_sigma_grows_one_km_per_day() -> None:
    """A 1 día (1440 min) σ = σ₀ + α·1 día = 2.0 km con defaults."""
    expected = COVARIANCE_BASELINE_SIGMA_KM + COVARIANCE_GROWTH_SIGMA_KM_PER_DAY
    assert sigma_tle_isotropic_km(1440.0) == pytest.approx(expected)


def test_sigma_grows_two_km_per_two_days() -> None:
    """A 2 días σ = σ₀ + 2α = 3.0 km."""
    expected = COVARIANCE_BASELINE_SIGMA_KM + 2 * COVARIANCE_GROWTH_SIGMA_KM_PER_DAY
    assert sigma_tle_isotropic_km(2 * 1440.0) == pytest.approx(expected)


def test_sigma_linearly_proportional_to_minutes() -> None:
    """Linealidad: σ(2·t) - σ(0) = 2·(σ(t) - σ(0))."""
    base = sigma_tle_isotropic_km(0.0)
    s1 = sigma_tle_isotropic_km(60.0) - base
    s2 = sigma_tle_isotropic_km(120.0) - base
    assert s2 == pytest.approx(2 * s1)


# --- combined_sigma_at_tca_km --------------------------------------------


def test_combined_sigma_at_epoch_is_sqrt_2() -> None:
    """Dos objetos en sus respectivos epochs → σ = √(σ₀² + σ₀²) = σ₀·√2."""
    expected = COVARIANCE_BASELINE_SIGMA_KM * math.sqrt(2.0)
    assert combined_sigma_at_tca_km(0.0, 0.0) == pytest.approx(expected)


def test_combined_sigma_uses_absolute_minutes() -> None:
    """σ(Δt) usa |Δt|; pasado y futuro contribuyen igual."""
    pos = combined_sigma_at_tca_km(60.0, 60.0)
    neg = combined_sigma_at_tca_km(-60.0, -60.0)
    mix = combined_sigma_at_tca_km(60.0, -60.0)
    assert pos == pytest.approx(neg)
    assert pos == pytest.approx(mix)


def test_combined_sigma_grows_with_distance_from_epoch() -> None:
    """Lejos del epoch combinado > cerca del epoch combinado."""
    near = combined_sigma_at_tca_km(0.0, 0.0)
    far = combined_sigma_at_tca_km(1440.0, 1440.0)
    assert far > near


# --- pc_foster_fast: edge cases ------------------------------------------


def test_pc_zero_when_radius_zero() -> None:
    """ADR-0020: R = 0 (default) → Pc = 0."""
    assert pc_foster_fast(miss_distance_km=0.0, combined_sigma_km=1.0,
                          combined_hard_body_radius_km=0.0) == 0.0
    assert pc_foster_fast(miss_distance_km=5.0, combined_sigma_km=1.0,
                          combined_hard_body_radius_km=0.0) == 0.0


def test_pc_deterministic_when_sigma_zero_and_miss_le_radius() -> None:
    """σ = 0 + d ≤ R → Pc = 1 (caso determinista)."""
    assert pc_foster_fast(0.0, 0.0, 1.0) == 1.0
    assert pc_foster_fast(1.0, 0.0, 1.0) == 1.0


def test_pc_zero_when_sigma_zero_and_miss_gt_radius() -> None:
    """σ = 0 + d > R → Pc = 0 (objetos no se tocan)."""
    assert pc_foster_fast(2.0, 0.0, 1.0) == 0.0


def test_pc_in_range_zero_to_one() -> None:
    """Pc ∈ [0, 1] en cualquier caso razonable."""
    samples = [
        (0.0, 1.0, 0.01),
        (1.0, 1.0, 0.01),
        (5.0, 1.0, 0.01),
        (100.0, 10.0, 0.5),
    ]
    for d, sigma, r in samples:
        pc = pc_foster_fast(d, sigma, r)
        assert 0.0 <= pc <= 1.0


# --- pc_foster_fast: monotonía ------------------------------------------


def test_pc_decreases_with_miss_distance() -> None:
    """A más miss, menor Pc (fórmula exp(-d²/2σ²))."""
    pc_close = pc_foster_fast(0.1, 1.0, 0.01)
    pc_mid = pc_foster_fast(1.0, 1.0, 0.01)
    pc_far = pc_foster_fast(5.0, 1.0, 0.01)
    assert pc_close > pc_mid > pc_far


def test_pc_increases_with_radius_squared() -> None:
    """Pc ∝ R²: 2R debe dar Pc · 4."""
    pc_r1 = pc_foster_fast(1.0, 1.0, 0.01)
    pc_r2 = pc_foster_fast(1.0, 1.0, 0.02)
    assert pc_r2 == pytest.approx(pc_r1 * 4.0, rel=1e-6)


def test_pc_decreases_with_sigma() -> None:
    """Mayor σ → menor Pc para mismo d > 0 (más incertidumbre, menos densidad en TCA)."""
    pc_small_sigma = pc_foster_fast(1.0, 0.5, 0.01)
    pc_large_sigma = pc_foster_fast(1.0, 5.0, 0.01)
    assert pc_small_sigma > pc_large_sigma


def test_pc_max_at_zero_miss() -> None:
    """Pc máximo en d=0: Pc(0) = R²/2σ²."""
    pc_max = pc_foster_fast(0.0, 1.0, 0.01)
    expected = (0.01 ** 2) / (2.0 * 1.0 ** 2)
    assert pc_max == pytest.approx(expected, rel=1e-9)


def test_pc_at_one_sigma() -> None:
    """A d = σ: Pc = R²/2σ² · exp(-1/2) ≈ 0.6065 · R²/2σ²."""
    sigma = 1.0
    r = 0.01
    pc = pc_foster_fast(sigma, sigma, r)
    expected = (r ** 2) / (2.0 * sigma ** 2) * math.exp(-0.5)
    assert pc == pytest.approx(expected, rel=1e-9)


# --- Constantes ----------------------------------------------------------


def test_covariance_model_name_is_v1() -> None:
    assert COVARIANCE_MODEL_NAME == "tle_isotropic_spherical_v1"


def test_pc_method_name_is_foster_fast() -> None:
    assert PC_METHOD_NAME == "foster_1992_fast_approximation"


def test_baseline_sigma_is_one_km() -> None:
    assert COVARIANCE_BASELINE_SIGMA_KM == 1.0


def test_growth_rate_is_one_km_per_day() -> None:
    assert COVARIANCE_GROWTH_SIGMA_KM_PER_DAY == 1.0
