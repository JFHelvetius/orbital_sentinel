"""Geometría topocéntrica observador-céntrica (ADR-0023).

Tres primitivas puras, sin estado, sin propagación. Cada una documentada por
su matemática y testeable de forma aislada por F2/F3/F4-equivalentes:

* :func:`observer_to_ecef` — geodésicas (φ, λ, h) → ECEF [km] bajo Tierra
  esférica.
* :func:`ecef_to_enu` — vector ΔECEF → topocéntrico local (east, north, up).
* :func:`enu_to_elevation_azimuth` — vector ENU → (elevation_deg,
  azimuth_deg, range_km) con convención compás (0°=N, 90°=E).

Marco de honestidad declarado por :data:`FRAME_MODEL_NAME`: el bias vs WGS84
elipsoidal (sub-km en latitudes medias, hasta ~21 km polar) queda dominado por
el régimen SGP4 (~3 km baseline, ADR-0014).
"""

from __future__ import annotations

import math

# Constante duplicada deliberadamente para respetar separación de planos
# ADR-0002: ``analytics/`` no puede importar de ``orchestration/``. El valor
# coincide bit-exacto con ``orchestration/groundtrack.EARTH_RADIUS_KM``.
EARTH_RADIUS_KM = 6371.0
"""Radio terrestre medio para conversión esférica (km)."""

FRAME_MODEL_NAME = "spherical_earth_geocentric_topocentric_v1"
"""Identificador del modelo geodésico/topocéntrico v0.1 (ADR-0023).

Encodea: Tierra esférica con ``EARTH_RADIUS_KM`` constante, altitud sumada
radialmente, latitud geodésica = geocéntrica (sub esfera), topocéntrico ENU
con azimuth desde Norte hacia Este. Una eventual implementación WGS84 exigiría
un identificador distinto (machine-readable single-source).
"""


def observer_to_ecef(
    observer_lat_deg: float,
    observer_lon_deg: float,
    observer_alt_m: float,
) -> tuple[float, float, float]:
    """Coordenadas geodésicas (φ, λ, h) → ECEF [km] bajo Tierra esférica.

    Bajo esfera, latitud geodésica = latitud geocéntrica. La altitud (metros)
    se convierte a kilómetros y se suma radialmente al radio terrestre medio.
    """
    phi = math.radians(observer_lat_deg)
    lam = math.radians(observer_lon_deg)
    r = EARTH_RADIUS_KM + observer_alt_m / 1000.0
    cos_phi = math.cos(phi)
    x = r * cos_phi * math.cos(lam)
    y = r * cos_phi * math.sin(lam)
    z = r * math.sin(phi)
    return x, y, z


def ecef_to_enu(
    delta_ecef: tuple[float, float, float],
    observer_lat_deg: float,
    observer_lon_deg: float,
) -> tuple[float, float, float]:
    """Vector ECEF (sat − observador) → topocéntrico local ENU en (φ, λ).

    Matriz de rotación estándar::

        R = [ -sin λ              cos λ              0    ]
            [ -sin φ · cos λ     -sin φ · sin λ      cos φ ]
            [  cos φ · cos λ      cos φ · sin λ      sin φ ]
    """
    phi = math.radians(observer_lat_deg)
    lam = math.radians(observer_lon_deg)
    sin_phi, cos_phi = math.sin(phi), math.cos(phi)
    sin_lam, cos_lam = math.sin(lam), math.cos(lam)
    dx, dy, dz = delta_ecef
    east = -sin_lam * dx + cos_lam * dy
    north = -sin_phi * cos_lam * dx - sin_phi * sin_lam * dy + cos_phi * dz
    up = cos_phi * cos_lam * dx + cos_phi * sin_lam * dy + sin_phi * dz
    return east, north, up


def enu_to_elevation_azimuth(
    east: float, north: float, up: float
) -> tuple[float, float, float]:
    """Vector ENU → ``(elevation_deg, azimuth_deg, range_km)``.

    Convención topocéntrica estándar:

    * ``azimuth_deg`` en ``[0, 360)``, medido desde Norte hacia Este
      (0°=N, 90°=E, 180°=S, 270°=W).
    * ``elevation_deg`` en ``[-90, 90]``.
    * ``range_km = √(east² + north² + up²)``.

    Si ``range_km == 0`` (vector nulo, caso degenerado), devuelve ``(0, 0, 0)``.
    """
    range_km = math.sqrt(east * east + north * north + up * up)
    if range_km == 0.0:
        return 0.0, 0.0, 0.0
    elevation_rad = math.asin(up / range_km)
    azimuth_rad = math.atan2(east, north)
    azimuth_deg = (math.degrees(azimuth_rad) + 360.0) % 360.0
    return math.degrees(elevation_rad), azimuth_deg, range_km
