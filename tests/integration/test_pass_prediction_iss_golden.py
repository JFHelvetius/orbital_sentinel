"""Golden master integration tests para pass prediction (ADR-0023 Fase 6).

Estado:

* ``test_iss_passes_reproducible_across_runs`` — IMPLEMENTADO. Verifica
  determinismo bit-exacto sobre ISS+CDMX.
* ``test_geo_satellite_invisible_from_high_latitude`` — SKIP. Necesita
  fixture GEO TLE (se introducirá cuando el catálogo lo soporte).
* ``test_iss_pass_over_cdmx_skyfield_golden`` — SKIP. El vector dorado
  Skyfield se genera offline; el esqueleto está preparado y comentado.
  Cuando los valores estén disponibles, basta con sustituirlos y quitar
  el ``pytest.skip``.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

from orbital_sentinel.analytics.passes import predict_passes
from orbital_sentinel.catalog import TLESnapshot, normalize_snapshot

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "tle"
EPOCH = datetime(2008, 9, 20, 12, 25, 40, tzinfo=timezone.utc)
DERIVED_AT_FIXED = datetime(2026, 6, 6, 12, 0, tzinfo=timezone.utc)
CDMX_LAT, CDMX_LON, CDMX_ALT = 19.4326, -99.1332, 2240.0


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


# --- Reproducibilidad bit-exacta ----------------------------------------


def test_iss_passes_reproducible_across_runs() -> None:
    """ISS + CDMX + ventana fija + clock fijo → dos invocaciones idénticas."""
    element, snap = _iss_setup()
    kwargs = dict(
        observer_lat_deg=CDMX_LAT,
        observer_lon_deg=CDMX_LON,
        observer_alt_m=CDMX_ALT,
        window_start=EPOCH,
        window_end=EPOCH + timedelta(hours=8),
        step_minutes=0.5,
        min_elevation_deg=10.0,
        aos_los_tolerance_seconds=1.0,
        clock=_fixed_clock,
    )
    a = predict_passes(element, snap, **kwargs)
    b = predict_passes(element, snap, **kwargs)
    assert a.model_dump(mode="json") == b.model_dump(mode="json")
    # Sanidad: si hay pases sobre CDMX en 8h, los reportamos
    if a.n_passes > 0:
        first = a.passes[0]
        assert first.aos_time <= first.culmination_time <= first.los_time


# --- GEO invisible desde alta latitud ------------------------------------


def _goes16_setup() -> tuple[object, TLESnapshot]:
    """Carga la fixture GOES-16 (NORAD 41866, GEO clásico, inc=0.02°, e≈0)."""
    text = (FIXTURES / "goes16_2017.txt").read_text(encoding="ascii")
    encoded = text.encode("ascii")
    snap = TLESnapshot(
        content_hash=hashlib.sha256(encoded).hexdigest(),
        source="celestrak",
        dataset="geo",
        url="https://example/",
        fetched_at=DERIVED_AT_FIXED,
        raw_text=text,
        n_bytes=len(encoded),
    )
    [element] = normalize_snapshot(snap, derived_at=DERIVED_AT_FIXED)
    return element, snap


def test_geo_satellite_invisible_from_high_latitude() -> None:
    """GOES-16 (GEO sobre ecuador) NO debe ser visible desde 88°N.

    Límite geométrico: a φ > arccos(R⊕/r_GEO) ≈ 81.3°, el sub-punto solar de
    cualquier GEO está por debajo del horizonte topocéntrico. A 88°N el
    threshold queda violado por ~6.7° con holgura.
    """
    element, snap = _goes16_setup()
    # Ventana corta cerca del epoch del GOES-16
    goes_epoch = element.epoch_datetime
    result = predict_passes(
        element, snap,
        observer_lat_deg=88.0, observer_lon_deg=0.0, observer_alt_m=0.0,
        window_start=goes_epoch,
        window_end=goes_epoch + timedelta(hours=24),
        step_minutes=5.0,
        min_elevation_deg=0.0,
        clock=_fixed_clock,
    )
    assert result.passes == [], (
        f"GEO debería ser invisible desde 88°N pero se reportaron "
        f"{result.n_passes} pases"
    )
    assert result.n_passes == 0


# --- Golden master Skyfield --------------------------------------------
#
# Vector dorado generado offline por scripts/generate_iss_cdmx_golden.py
# usando Skyfield + el mismo TLE de Vallado 2008. Skyfield NO es dependencia
# de runtime ni de tests; solo se usa one-shot fuera del runtime para producir
# las constantes pegadas abajo.

GOLDEN_PASSES: list[dict[str, object]] = [
    {
        "aos": datetime.fromisoformat("2008-09-21T00:18:04.762448+00:00"),
        "culmination": datetime.fromisoformat("2008-09-21T00:20:50.167747+00:00"),
        "los": datetime.fromisoformat("2008-09-21T00:23:35.702878+00:00"),
        "max_elevation_deg": 37.8096,
        "aos_azimuth_deg": 239.51,
        "culmination_azimuth_deg": 310.27,
        "los_azimuth_deg": 21.22,
    },
    {
        "aos": datetime.fromisoformat("2008-09-21T10:00:22.055224+00:00"),
        "culmination": datetime.fromisoformat("2008-09-21T10:03:02.988127+00:00"),
        "los": datetime.fromisoformat("2008-09-21T10:05:43.964200+00:00"),
        "max_elevation_deg": 35.1178,
        "aos_azimuth_deg": 301.91,
        "culmination_azimuth_deg": 233.40,
        "los_azimuth_deg": 164.82,
    },
    {
        "aos": datetime.fromisoformat("2008-09-21T23:09:28.521769+00:00"),
        "culmination": datetime.fromisoformat("2008-09-21T23:12:09.699209+00:00"),
        "los": datetime.fromisoformat("2008-09-21T23:14:50.631066+00:00"),
        "max_elevation_deg": 32.9593,
        "aos_azimuth_deg": 193.23,
        "culmination_azimuth_deg": 126.37,
        "los_azimuth_deg": 59.72,
    },
    {
        "aos": datetime.fromisoformat("2008-09-22T08:51:41.084697+00:00"),
        "culmination": datetime.fromisoformat("2008-09-22T08:54:22.313555+00:00"),
        "los": datetime.fromisoformat("2008-09-22T08:57:03.250844+00:00"),
        "max_elevation_deg": 34.6919,
        "aos_azimuth_deg": 340.76,
        "culmination_azimuth_deg": 49.49,
        "los_azimuth_deg": 118.09,
    },
]

# Tolerancias declaradas. Reflejan honestamente la diferencia entre:
# * nuestra implementación (Tierra esférica + GMST IAU 1982 + UT1≈UTC)
# * Skyfield (WGS84 elipsoidal + nutación IAU 1976/2006 + DUT1 IERS real)
# La diferencia geométrica WGS84 vs esfera a lat 19.4°N es ~0.13°, que se
# traduce a ~14 km en posición topocéntrica = ~2 s de timing. La diferencia
# nutacional añade <1s. Estas tolerancias acomodan esos sesgos sistemáticos
# sin enmascarar errores reales.
_AOS_LOS_TOLERANCE_SECONDS = 10.0
_CULMINATION_TOLERANCE_SECONDS = 5.0
_MAX_ELEVATION_TOLERANCE_DEG = 1.0
_AZIMUTH_TOLERANCE_DEG = 3.0


def _azimuth_diff(a: float, b: float) -> float:
    """Diferencia angular mínima en [0°, 180°] (wrap-around)."""
    diff = abs(a - b) % 360.0
    return diff if diff <= 180.0 else 360.0 - diff


def test_iss_pass_over_cdmx_skyfield_golden() -> None:
    """ISS × CDMX × 48 h post-epoch contra golden master Skyfield offline.

    Vector generado por ``scripts/generate_iss_cdmx_golden.py``. Tolerancias
    declaradas absorben el sesgo sistemático esfera vs WGS84 + nutación
    sin enmascarar errores reales en el algoritmo.
    """
    element, snap = _iss_setup()
    result = predict_passes(
        element, snap,
        observer_lat_deg=CDMX_LAT,
        observer_lon_deg=CDMX_LON,
        observer_alt_m=CDMX_ALT,
        window_start=EPOCH,
        window_end=EPOCH + timedelta(hours=48),
        step_minutes=0.5,
        min_elevation_deg=10.0,
        clock=_fixed_clock,
    )
    assert result.n_passes == len(GOLDEN_PASSES), (
        f"Número de pases discrepa: nuestro={result.n_passes}, golden={len(GOLDEN_PASSES)}"
    )
    for ours, gold in zip(result.passes, GOLDEN_PASSES, strict=True):
        aos_delta = abs((ours.aos_time - gold["aos"]).total_seconds())
        los_delta = abs((ours.los_time - gold["los"]).total_seconds())
        cul_delta = abs((ours.culmination_time - gold["culmination"]).total_seconds())
        assert aos_delta < _AOS_LOS_TOLERANCE_SECONDS, (
            f"AOS off by {aos_delta:.2f}s for pass at {gold['aos']}"
        )
        assert los_delta < _AOS_LOS_TOLERANCE_SECONDS, (
            f"LOS off by {los_delta:.2f}s for pass at {gold['aos']}"
        )
        assert cul_delta < _CULMINATION_TOLERANCE_SECONDS, (
            f"Culmination off by {cul_delta:.2f}s for pass at {gold['aos']}"
        )
        assert (
            abs(ours.max_elevation_deg - gold["max_elevation_deg"])
            < _MAX_ELEVATION_TOLERANCE_DEG
        )
        assert (
            _azimuth_diff(ours.aos_azimuth_deg, gold["aos_azimuth_deg"])
            < _AZIMUTH_TOLERANCE_DEG
        )
        assert (
            _azimuth_diff(ours.culmination_azimuth_deg, gold["culmination_azimuth_deg"])
            < _AZIMUTH_TOLERANCE_DEG
        )
        assert (
            _azimuth_diff(ours.los_azimuth_deg, gold["los_azimuth_deg"])
            < _AZIMUTH_TOLERANCE_DEG
        )
