"""Tests de ``analytics.anomalies.features`` (ADR-0028)."""

from __future__ import annotations

import math

import pytest

from orbital_sentinel.analytics.anomalies import (
    AVAILABLE_FEATURES,
    EARTH_RADIUS_KM,
    UnknownFeatureError,
    compute_feature,
    compute_features,
)
from tests.unit.test_maneuver_series import make_element


def test_available_features_is_canonical_tuple() -> None:
    """``AVAILABLE_FEATURES`` es tuple inmutable con exactamente 4 entradas v0.1."""
    assert AVAILABLE_FEATURES == (
        "altitude_km", "eccentricity", "inclination_deg", "mean_motion",
    )
    assert isinstance(AVAILABLE_FEATURES, tuple)


def test_compute_feature_altitude_iss_leo_in_expected_range() -> None:
    """ISS mean_motion ≈ 15.5 rev/d → altitud ~400 km."""
    el = make_element(mean_motion=15.5)
    alt = compute_feature(el, "altitude_km")
    assert 300.0 < alt < 500.0  # LEO típico ISS


def test_compute_feature_altitude_geo_in_expected_range() -> None:
    """GEO mean_motion ≈ 1.0027 rev/d → altitud ~35786 km."""
    el = make_element(mean_motion=1.00271)
    alt = compute_feature(el, "altitude_km")
    assert 35000.0 < alt < 36500.0


def test_compute_feature_altitude_non_physical_mean_motion_returns_zero() -> None:
    """Defensa: mean_motion no físico no debe crashear."""
    el = make_element(mean_motion=0.0)
    assert compute_feature(el, "altitude_km") == 0.0


def test_compute_feature_eccentricity_directly_from_element() -> None:
    el = make_element(eccentricity=0.003)
    assert compute_feature(el, "eccentricity") == 0.003


def test_compute_feature_inclination_directly_from_element() -> None:
    el = make_element(inclination=98.7)
    assert compute_feature(el, "inclination_deg") == 98.7


def test_compute_feature_mean_motion_directly_from_element() -> None:
    el = make_element(mean_motion=14.5)
    assert compute_feature(el, "mean_motion") == 14.5


def test_compute_feature_unknown_raises() -> None:
    el = make_element()
    with pytest.raises(UnknownFeatureError, match="desconocida"):
        compute_feature(el, "not_a_feature")


def test_compute_features_returns_all_requested() -> None:
    el = make_element()
    result = compute_features(el, ["altitude_km", "mean_motion"])
    assert set(result.keys()) == {"altitude_km", "mean_motion"}


def test_compute_features_default_full_set() -> None:
    el = make_element()
    result = compute_features(el, AVAILABLE_FEATURES)
    assert set(result.keys()) == set(AVAILABLE_FEATURES)


def test_compute_features_deterministic_across_calls() -> None:
    el = make_element()
    a = compute_features(el, AVAILABLE_FEATURES)
    b = compute_features(el, AVAILABLE_FEATURES)
    assert a == b


def test_compute_features_unknown_raises() -> None:
    el = make_element()
    with pytest.raises(UnknownFeatureError):
        compute_features(el, ["altitude_km", "unknown"])


def test_altitude_consistent_with_earth_radius_constant() -> None:
    """Altitud = a - R⊕. Para un sat justo en superficie (n grande), alt < 0."""
    # mean_motion altísimo → semi-major axis pequeño → altitude potentially < 0
    el = make_element(mean_motion=20.0)
    alt = compute_feature(el, "altitude_km")
    # Verifica que el valor responde monótonamente al mean_motion
    el_low = make_element(mean_motion=2.0)
    alt_low = compute_feature(el_low, "altitude_km")
    assert alt < alt_low  # mayor n → menor altitud


def test_altitude_formula_matches_kepler() -> None:
    """Verificación analítica: a = (GM/n²)^(1/3), alt = a − R⊕."""
    n_rev_day = 15.5
    el = make_element(mean_motion=n_rev_day)
    n_rad_s = n_rev_day * 2.0 * math.pi / 86400.0
    a_expected = (398_600.4418 / (n_rad_s * n_rad_s)) ** (1.0 / 3.0)
    expected_alt = a_expected - EARTH_RADIUS_KM
    assert compute_feature(el, "altitude_km") == pytest.approx(expected_alt, abs=1e-9)
