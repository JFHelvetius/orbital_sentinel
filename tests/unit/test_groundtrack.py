"""Tests del módulo ``groundtrack``: matemática + plotting determinista."""

from __future__ import annotations

import hashlib
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from orbital_sentinel.catalog import TLESnapshot, normalize_snapshot
from orbital_sentinel.orchestration.groundtrack import (
    EARTH_RADIUS_KM,
    GroundPoint,
    build_groundtrack,
    ecef_to_geodetic_spherical,
    ephemeris_to_ground_point,
    gmst_radians,
    plot_groundtrack,
    teme_to_ecef,
)
from orbital_sentinel.propagation import Sgp4Propagator

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "tle"
DERIVED_AT = datetime(2026, 6, 3, 12, 0, tzinfo=timezone.utc)
EPOCH = datetime(2008, 9, 20, 12, 25, 40, tzinfo=timezone.utc)


def _iss_setup():
    text = (FIXTURES / "iss_vallado_2008.txt").read_text(encoding="ascii")
    encoded = text.encode("ascii")
    snap = TLESnapshot(
        content_hash=hashlib.sha256(encoded).hexdigest(),
        source="celestrak",
        dataset="stations",
        url="https://example/",
        fetched_at=DERIVED_AT,
        raw_text=text,
        n_bytes=len(encoded),
    )
    [element] = normalize_snapshot(snap, derived_at=DERIVED_AT)
    return element, snap


# --- GMST ----------------------------------------------------------------


def test_gmst_at_j2000_close_to_known_value() -> None:
    """En J2000 (2000-01-01T12:00:00 UTC, ~TT), GMST debe ser ~280.46° (= ~4.895 rad)."""
    j2000 = datetime(2000, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    gmst = gmst_radians(j2000)
    assert math.degrees(gmst) == pytest.approx(280.46061837, abs=0.5)


def test_gmst_rejects_naive_datetime() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        gmst_radians(datetime(2008, 9, 20, 12, 0, 0))


def test_gmst_periodic_over_one_sidereal_day() -> None:
    """GMST debe ser ~igual cada ~23h 56min 4s (día sideral)."""
    t1 = datetime(2008, 9, 20, 0, 0, 0, tzinfo=timezone.utc)
    sidereal_day = timedelta(hours=23, minutes=56, seconds=4)
    t2 = t1 + sidereal_day
    diff_rad = (gmst_radians(t2) - gmst_radians(t1)) % (2 * math.pi)
    # diff debe estar cerca de 0 o 2π
    err = min(diff_rad, 2 * math.pi - diff_rad)
    assert err < math.radians(0.1)


# --- TEME → ECEF + spherical lat/lon -------------------------------------


def test_ecef_to_geodetic_at_north_pole() -> None:
    lat, lon, alt = ecef_to_geodetic_spherical(0.0, 0.0, EARTH_RADIUS_KM + 400.0)
    assert lat == pytest.approx(90.0, abs=1e-6)
    assert alt == pytest.approx(400.0, abs=1e-6)


def test_ecef_to_geodetic_at_equator_greenwich() -> None:
    lat, lon, alt = ecef_to_geodetic_spherical(EARTH_RADIUS_KM + 400.0, 0.0, 0.0)
    assert lat == pytest.approx(0.0, abs=1e-6)
    assert lon == pytest.approx(0.0, abs=1e-6)
    assert alt == pytest.approx(400.0, abs=1e-6)


def test_ecef_to_geodetic_at_equator_180() -> None:
    lat, lon, alt = ecef_to_geodetic_spherical(-(EARTH_RADIUS_KM + 400.0), 0.0, 0.0)
    assert lat == pytest.approx(0.0, abs=1e-6)
    assert abs(abs(lon) - 180.0) < 1e-6  # ±180 ambos válidos


def test_teme_to_ecef_preserves_z() -> None:
    """La rotación TEME→ECEF es alrededor del eje Z; Z no cambia."""
    when = datetime(2008, 9, 20, 12, 0, 0, tzinfo=timezone.utc)
    _, _, z = teme_to_ecef(1000.0, 2000.0, 3000.0, when)
    assert z == 3000.0


def test_teme_to_ecef_preserves_norm() -> None:
    when = datetime(2008, 9, 20, 12, 0, 0, tzinfo=timezone.utc)
    x, y, z = 4000.0, -5000.0, 2000.0
    norm_in = math.sqrt(x * x + y * y + z * z)
    rx, ry, rz = teme_to_ecef(x, y, z, when)
    norm_out = math.sqrt(rx * rx + ry * ry + rz * rz)
    assert norm_out == pytest.approx(norm_in, rel=1e-12)


# --- Ephemeris → GroundPoint ---------------------------------------------


def test_ground_point_for_iss_in_expected_lat_range() -> None:
    """ISS inclinación = 51.6°; latitud debe estar en [-52, 52]."""
    element, snap = _iss_setup()
    [eph] = Sgp4Propagator().propagate(element, snap, [EPOCH])
    point = ephemeris_to_ground_point(eph)
    assert -52.0 < point.latitude_deg < 52.0
    assert -180.0 <= point.longitude_deg <= 180.0
    assert 300.0 < point.altitude_km < 500.0  # ISS ~400 km LEO


def test_ground_point_carries_sgp4_error_code() -> None:
    element, snap = _iss_setup()
    [eph] = Sgp4Propagator().propagate(element, snap, [EPOCH])
    point = ephemeris_to_ground_point(eph)
    assert point.sgp4_error_code == 0


def test_build_groundtrack_returns_one_point_per_ephemeris() -> None:
    element, snap = _iss_setup()
    times = [EPOCH + timedelta(minutes=i) for i in range(5)]
    ephem = Sgp4Propagator().propagate(element, snap, times)
    points = build_groundtrack(ephem)
    assert len(points) == 5
    assert all(isinstance(p, GroundPoint) for p in points)


# --- plot_groundtrack ----------------------------------------------------

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def test_plot_writes_valid_png(tmp_path: Path) -> None:
    element, snap = _iss_setup()
    times = [EPOCH + timedelta(minutes=i * 5) for i in range(20)]
    ephem = Sgp4Propagator().propagate(element, snap, times)

    out = tmp_path / "groundtrack.png"
    written = plot_groundtrack(ephem, out, title="ISS test")
    assert written.exists()
    assert written.suffix == ".png"
    data = written.read_bytes()
    assert data.startswith(PNG_MAGIC)
    assert len(data) > 1024  # PNG no trivial


def test_plot_dimensions_match_request(tmp_path: Path) -> None:
    element, snap = _iss_setup()
    ephem = Sgp4Propagator().propagate(element, snap, [EPOCH])
    out = tmp_path / "small.png"
    plot_groundtrack(ephem, out, width_px=800, height_px=400)
    data = out.read_bytes()
    # Cabecera IHDR a partir del byte 8: 4 bytes longitud + 4 bytes "IHDR"
    # + 4 bytes width + 4 bytes height.
    # Posiciones: PNG_MAGIC(8) + length(4) + type(4) = byte 16 → width
    width = int.from_bytes(data[16:20], "big")
    height = int.from_bytes(data[20:24], "big")
    assert width == 800
    assert height == 400


def test_plot_raises_on_empty_ephemerides(tmp_path: Path) -> None:
    out = tmp_path / "empty.png"
    with pytest.raises(ValueError, match="No hay ephemerides"):
        plot_groundtrack([], out)


def test_plot_creates_parent_directory(tmp_path: Path) -> None:
    element, snap = _iss_setup()
    ephem = Sgp4Propagator().propagate(element, snap, [EPOCH])
    out = tmp_path / "nested" / "sub" / "track.png"
    plot_groundtrack(ephem, out)
    assert out.exists()


def test_plot_same_input_produces_same_dimensions(tmp_path: Path) -> None:
    """Dos llamadas con misma entrada producen PNGs del mismo tamaño."""
    element, snap = _iss_setup()
    times = [EPOCH + timedelta(minutes=i) for i in range(10)]
    ephem = Sgp4Propagator().propagate(element, snap, times)
    a = tmp_path / "a.png"
    b = tmp_path / "b.png"
    plot_groundtrack(ephem, a, title="t")
    plot_groundtrack(ephem, b, title="t")
    da = a.read_bytes()
    db = b.read_bytes()
    # Dimensiones idénticas
    assert da[16:24] == db[16:24]
    # Tamaño similar (heurístico, matplotlib puede variar metadata < 1KB)
    assert abs(len(da) - len(db)) < 1024
