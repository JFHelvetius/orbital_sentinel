"""Tests G1–G10 de geometría topocéntrica (ADR-0023 Fase 2)."""

from __future__ import annotations

import pytest

from orbital_sentinel.analytics.passes.geometry import (
    EARTH_RADIUS_KM,
    ecef_to_enu,
    enu_to_elevation_azimuth,
    observer_to_ecef,
)

# --- observer_to_ecef ----------------------------------------------------


def test_g1_observer_ecef_equator_zero_lon() -> None:
    """Observador en (0°, 0°, 0m) → (R, 0, 0)."""
    x, y, z = observer_to_ecef(0.0, 0.0, 0.0)
    assert x == pytest.approx(EARTH_RADIUS_KM, abs=1e-9)
    assert y == pytest.approx(0.0, abs=1e-9)
    assert z == pytest.approx(0.0, abs=1e-9)


def test_g2_observer_ecef_north_pole() -> None:
    """Observador en (90°, *, 0m) → (0, 0, R)."""
    x, y, z = observer_to_ecef(90.0, 0.0, 0.0)
    assert x == pytest.approx(0.0, abs=1e-9)
    assert y == pytest.approx(0.0, abs=1e-9)
    assert z == pytest.approx(EARTH_RADIUS_KM, abs=1e-9)


def test_g3_observer_ecef_altitude_adds_radially() -> None:
    """Observador en (0°, 0°, 1000m) → (R + 1.0, 0, 0)."""
    x, y, z = observer_to_ecef(0.0, 0.0, 1000.0)
    assert x == pytest.approx(EARTH_RADIUS_KM + 1.0, abs=1e-9)
    assert y == pytest.approx(0.0, abs=1e-9)
    assert z == pytest.approx(0.0, abs=1e-9)


# --- ecef_to_enu ---------------------------------------------------------


def test_g4_ecef_to_enu_sat_overhead() -> None:
    """Satélite directamente sobre observador → up>0, east≈0, north≈0."""
    # Observador en (0°, 0°, 0): ECEF = (R, 0, 0). Sat un poco más arriba:
    # ECEF = (R + 500, 0, 0). delta = (500, 0, 0).
    east, north, up = ecef_to_enu((500.0, 0.0, 0.0), 0.0, 0.0)
    assert east == pytest.approx(0.0, abs=1e-9)
    assert north == pytest.approx(0.0, abs=1e-9)
    assert up == pytest.approx(500.0, abs=1e-9)


def test_g5_ecef_to_enu_sat_due_north_at_horizon() -> None:
    """Sat al norte en horizonte → north>0, east≈0, up≈0.

    Observador en (0°, 0°, 0): ECEF = (R, 0, 0). Sat en eje Z+: ECEF=(0, 0, d).
    delta = (-R, 0, d). En el horizonte norte significa up=0 y north>0.
    Como sat está en eje Z, está al "norte" desde el equator en lon=0.
    """
    # Para que sea estrictamente horizonte (up=0) y north>0, basta con un
    # vector delta cuyo "up" en (φ=0, λ=0) sea 0. Up = cos φ cos λ dx +
    # cos φ sin λ dy + sin φ dz = dx en (0,0). Así dx=0 ⇒ up=0.
    east, north, up = ecef_to_enu((0.0, 0.0, 100.0), 0.0, 0.0)
    # En φ=0,λ=0: north = -sin φ cos λ dx - sin φ sin λ dy + cos φ dz = dz
    assert east == pytest.approx(0.0, abs=1e-9)
    assert north == pytest.approx(100.0, abs=1e-9)
    assert up == pytest.approx(0.0, abs=1e-9)


def test_g6_ecef_to_enu_zenith_at_pole() -> None:
    """Observador en polo norte, sat directamente arriba → up positivo."""
    # En (90°, 0°, 0): ECEF observador = (0, 0, R). Sat justo arriba:
    # ECEF = (0, 0, R+100). delta = (0, 0, 100). En polo:
    # east = -sin 0 * 0 + cos 0 * 0 = 0
    # north = -sin 90 cos 0 * 0 - sin 90 sin 0 * 0 + cos 90 * 100 = 0
    # up = cos 90 cos 0 * 0 + cos 90 sin 0 * 0 + sin 90 * 100 = 100
    east, north, up = ecef_to_enu((0.0, 0.0, 100.0), 90.0, 0.0)
    assert east == pytest.approx(0.0, abs=1e-9)
    assert north == pytest.approx(0.0, abs=1e-9)
    assert up == pytest.approx(100.0, abs=1e-9)


# --- Azimuth y elevación ------------------------------------------------


def test_g7_azimuth_convention_due_east() -> None:
    """ENU = (1, 0, 0.001) → azimuth ≈ 90° (Este), elevation ≈ 0°."""
    elev, az, rng = enu_to_elevation_azimuth(1.0, 0.0, 0.001)
    assert az == pytest.approx(90.0, abs=0.1)
    assert elev == pytest.approx(0.0, abs=0.1)
    assert rng > 0.0


def test_g8_azimuth_convention_due_south_and_west() -> None:
    """Due south → azimuth ≈ 180°. Due west → azimuth ≈ 270°."""
    _, az_south, _ = enu_to_elevation_azimuth(0.0, -1.0, 0.001)
    assert az_south == pytest.approx(180.0, abs=0.1)
    _, az_west, _ = enu_to_elevation_azimuth(-1.0, 0.0, 0.001)
    assert az_west == pytest.approx(270.0, abs=0.1)


def test_g9_elevation_zero_at_horizon() -> None:
    """ENU con up exactamente 0 → elevation_deg = 0."""
    elev, _, _ = enu_to_elevation_azimuth(3.0, 4.0, 0.0)
    assert elev == pytest.approx(0.0, abs=1e-12)


def test_g10_elevation_90_at_zenith() -> None:
    """ENU con east=north=0, up>0 → elevation_deg = 90."""
    elev, _, _ = enu_to_elevation_azimuth(0.0, 0.0, 7.0)
    assert elev == pytest.approx(90.0, abs=1e-12)


def test_enu_to_elevation_azimuth_zero_vector_is_degenerate() -> None:
    """Caso degenerado: vector nulo → (0, 0, 0)."""
    elev, az, rng = enu_to_elevation_azimuth(0.0, 0.0, 0.0)
    assert (elev, az, rng) == (0.0, 0.0, 0.0)


def test_azimuth_is_strictly_in_zero_360_range() -> None:
    """Azimuth siempre en [0, 360). Vector debido Norte → 0°."""
    _, az_north, _ = enu_to_elevation_azimuth(0.0, 1.0, 0.001)
    assert 0.0 <= az_north < 360.0
    assert az_north == pytest.approx(0.0, abs=0.1)
