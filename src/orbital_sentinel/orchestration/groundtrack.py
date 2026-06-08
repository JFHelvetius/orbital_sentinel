"""Conversión TEME → lat/lon y plot 2D estático de groundtracks.

Cubre el requisito de "visualización" de Fase 1 según ADR-0000. **No es Cesium**:
ADR-0008 reserva Cesium para visualización 3D interactiva en Fase 2+. Este
módulo entrega 2D estático (PNG), determinista bajo entorno declarado
(ADR-0013), sin display, sin JS, sin servidor.

Conversiones implementadas:

* GMST (Greenwich Mean Sidereal Time) por la fórmula IAU 1982 simplificada.
* TEME → ECEF por rotación alrededor del eje Z usando GMST (sin polar motion).
* ECEF → lat/lon **esférica** (no WGS84). El error vs WGS84 elipsoidal es
  sub-km, **muy por debajo** del régimen de incertidumbre SGP4 (~1–3 km en
  época, ~1–3 km/día). ADR-0000 P2: el caption del plot documenta ambos.

El módulo importa `matplotlib` perezosamente para que el resto del paquete
funcione sin el extra ``viz`` instalado.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import NamedTuple

from orbital_sentinel.propagation.ephemeris import Ephemeris
from orbital_sentinel.propagation.frames import gmst_iau_1982, teme_to_ecef

# Alias histórico preservado para compatibilidad de imports previos al refactor
# preparatorio de ADR-0023. Resuelve al mismo callable canónico.
gmst_radians = gmst_iau_1982

EARTH_RADIUS_KM = 6371.0
"""Radio terrestre medio para conversión esférica ECEF → lat/lon."""

UNCERTAINTY_CAPTION = (
    "SGP4 uncertainty ~1-3 km at epoch, growing ~1-3 km/day. "
    "Spherical lat/lon (sub-km error vs WGS84). "
    "Antimeridian crossings rendered as segment breaks."
)


class GroundPoint(NamedTuple):
    """Punto sub-satélite en un instante UTC.

    ``altitude_km`` está calculado vs radio terrestre medio (esférico).
    El error vs WGS84 elipsoidal es < 1 km en general.
    """

    evaluation_time: datetime
    latitude_deg: float
    longitude_deg: float
    altitude_km: float
    sgp4_error_code: int


# --- Conversiones astronómicas -------------------------------------------
#
# ``gmst_iau_1982`` y ``teme_to_ecef`` viven en ``propagation/frames.py`` desde
# el refactor preparatorio de ADR-0023; se importan arriba. ``gmst_radians``
# se preserva como alias para no romper consumidores anteriores.


def ecef_to_geodetic_spherical(
    x_km: float, y_km: float, z_km: float
) -> tuple[float, float, float]:
    """ECEF → ``(lat_deg, lon_deg, alt_km)`` esférica."""
    r = math.sqrt(x_km * x_km + y_km * y_km + z_km * z_km)
    lat = math.degrees(math.asin(z_km / r))
    lon = math.degrees(math.atan2(y_km, x_km))
    # Normalizar a [-180, 180]
    if lon > 180.0:
        lon -= 360.0
    elif lon < -180.0:
        lon += 360.0
    alt = r - EARTH_RADIUS_KM
    return lat, lon, alt


def ephemeris_to_ground_point(e: Ephemeris) -> GroundPoint:
    """Convierte una :class:`Ephemeris` en un :class:`GroundPoint`."""
    ecef_x, ecef_y, ecef_z = teme_to_ecef(
        e.position_teme_x_km,
        e.position_teme_y_km,
        e.position_teme_z_km,
        e.evaluation_time,
    )
    lat, lon, alt = ecef_to_geodetic_spherical(ecef_x, ecef_y, ecef_z)
    return GroundPoint(
        evaluation_time=e.evaluation_time,
        latitude_deg=lat,
        longitude_deg=lon,
        altitude_km=alt,
        sgp4_error_code=e.sgp4_error_code,
    )


def build_groundtrack(ephemerides: Sequence[Ephemeris]) -> list[GroundPoint]:
    """Convierte una secuencia de :class:`Ephemeris` a :class:`GroundPoint`."""
    return [ephemeris_to_ground_point(e) for e in ephemerides]


# --- Plot ----------------------------------------------------------------


def _split_segments(points: Sequence[GroundPoint]) -> list[tuple[list[float], list[float]]]:
    """Divide la traza en segmentos cuando cruza el antimeridiano (|Δlon| > 180)."""
    segments: list[tuple[list[float], list[float]]] = [([], [])]
    prev_lon: float | None = None
    for p in points:
        if prev_lon is not None and abs(p.longitude_deg - prev_lon) > 180:
            segments.append(([], []))
        segments[-1][0].append(p.longitude_deg)
        segments[-1][1].append(p.latitude_deg)
        prev_lon = p.longitude_deg
    return segments


def plot_groundtrack(
    ephemerides: Sequence[Ephemeris],
    output_path: Path | str,
    *,
    title: str | None = None,
    width_px: int = 1200,
    height_px: int = 600,
) -> Path:
    """Renderiza el groundtrack a un PNG en ``output_path``.

    Args:
        ephemerides: secuencia de :class:`Ephemeris` (e.g., salida de
            :class:`Sgp4Propagator.propagate`).
        output_path: ruta de salida del PNG.
        title: título opcional del plot.
        width_px / height_px: dimensiones del PNG.

    Returns:
        Ruta absoluta del PNG escrito.

    Raises:
        ImportError: si ``matplotlib`` no está instalado.
        ValueError: si ``ephemerides`` está vacío.
    """
    try:
        import matplotlib
    except ImportError as exc:
        raise ImportError(
            "matplotlib no está instalado. Instala el extra 'viz':\n"
            "    pip install -e \".[viz]\""
        ) from exc

    matplotlib.use("Agg", force=True)
    import matplotlib.pyplot as plt

    points = build_groundtrack(ephemerides)
    if not points:
        raise ValueError("No hay ephemerides para plotear.")

    segments = _split_segments(points)

    fig = plt.figure(figsize=(width_px / 100, height_px / 100), dpi=100)
    ax = fig.add_subplot(111)
    for lons, lats in segments:
        if lons:
            ax.plot(lons, lats, color="#1f77b4", linewidth=1.2)
    ax.scatter(
        [points[0].longitude_deg], [points[0].latitude_deg],
        color="#2ca02c", s=40, marker="o", zorder=5, label="start",
    )
    ax.scatter(
        [points[-1].longitude_deg], [points[-1].latitude_deg],
        color="#d62728", s=40, marker="s", zorder=5, label="end",
    )

    ax.set_xlim(-180, 180)
    ax.set_ylim(-90, 90)
    ax.set_xticks(range(-180, 181, 30))
    ax.set_yticks(range(-90, 91, 30))
    ax.grid(True, linestyle="--", alpha=0.4)
    ax.set_xlabel("Longitude [deg]")
    ax.set_ylabel("Latitude [deg]")
    ax.set_aspect("equal")
    ax.legend(loc="upper right", fontsize=8)

    if title:
        ax.set_title(title, fontsize=10)
    fig.text(
        0.5, 0.01, UNCERTAINTY_CAPTION,
        ha="center", fontsize=7, color="#555555",
    )

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(
        out,
        format="png",
        dpi=100,
        metadata={"Software": "orbital-sentinel"},
    )
    plt.close(fig)
    return out.resolve()
