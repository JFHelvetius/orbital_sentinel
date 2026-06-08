"""Contexto solar para un observador (ADR-0024).

Combina :func:`sun_position_eci` con la geometría topocéntrica de
``analytics.passes.geometry`` para producir:

* :func:`solar_context_at` — sun elevation/azimuth observer-relative +
  clasificación de twilight + honesty fields.
* :func:`is_satellite_illuminated` — sombra cilíndrica terrestre.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from enum import StrEnum

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from orbital_sentinel.analytics.passes.geometry import (
    EARTH_RADIUS_KM,
    ecef_to_enu,
    enu_to_elevation_azimuth,
    observer_to_ecef,
)
from orbital_sentinel.analytics.solar.sun_position import (
    SOLAR_POSITION_MODEL_NAME,
    VALID_DATE_RANGE_ISO,
    sun_position_eci,
)
from orbital_sentinel.propagation import teme_to_ecef

SOLAR_GEOMETRY_SCHEMA_VERSION = "0.1.0"
"""SemVer del esquema ``SolarContext`` (ADR-0010)."""

SOLAR_GEOMETRY_ENGINE_VERSION = "0.1.0"
"""SemVer del motor solar (ADR-0010 engine_version)."""

SHADOW_MODEL_NAME = "cylindrical_earth_shadow_v1"
"""Identificador del modelo de sombra (ADR-0024)."""

# Rangos válidos heredados de ``predict_passes`` (ADR-0023 enmienda 3).
_OBSERVER_LAT_RANGE = (-90.0, 90.0)
_OBSERVER_LON_RANGE = (-180.0, 180.0)
_OBSERVER_ALT_RANGE_M = (-11_000.0, 100_000.0)


class TwilightPhase(StrEnum):
    """Fases de twilight según convención USNO/IAU.

    Orden de "oscuridad" creciente:
    ``day`` < ``civil`` < ``nautical`` < ``astronomical`` < ``night``.
    """

    DAY = "day"
    CIVIL = "civil"
    NAUTICAL = "nautical"
    ASTRONOMICAL = "astronomical"
    NIGHT = "night"


_TWILIGHT_DARKNESS_ORDER: dict[TwilightPhase, int] = {
    TwilightPhase.DAY: 0,
    TwilightPhase.CIVIL: 1,
    TwilightPhase.NAUTICAL: 2,
    TwilightPhase.ASTRONOMICAL: 3,
    TwilightPhase.NIGHT: 4,
}


def twilight_darkness_rank(phase: TwilightPhase) -> int:
    """Ranking entero de "oscuridad" de la fase.

    Mayor número = más oscuro. Permite comparaciones ``actual >= minimum``.
    """
    return _TWILIGHT_DARKNESS_ORDER[phase]


def _classify_twilight(sun_elevation_deg: float) -> TwilightPhase:
    """Mapea sun_elevation_deg → fase de twilight."""
    if sun_elevation_deg >= 0.0:
        return TwilightPhase.DAY
    if sun_elevation_deg >= -6.0:
        return TwilightPhase.CIVIL
    if sun_elevation_deg >= -12.0:
        return TwilightPhase.NAUTICAL
    if sun_elevation_deg >= -18.0:
        return TwilightPhase.ASTRONOMICAL
    return TwilightPhase.NIGHT


def _validate_observer(lat_deg: float, lon_deg: float, alt_m: float) -> None:
    lo, hi = _OBSERVER_LAT_RANGE
    if not (lo <= lat_deg <= hi):
        raise ValueError(
            f"observer_lat_deg fuera de rango [{lo}, {hi}]: {lat_deg}"
        )
    lo, hi = _OBSERVER_LON_RANGE
    if not (lo <= lon_deg <= hi):
        raise ValueError(
            f"observer_lon_deg fuera de rango [{lo}, {hi}]: {lon_deg}"
        )
    lo, hi = _OBSERVER_ALT_RANGE_M
    if not (lo <= alt_m <= hi):
        raise ValueError(
            f"observer_alt_m fuera de rango [{lo}, {hi}] (m): {alt_m}"
        )


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


# --- Modelo público -----------------------------------------------------


class SolarContext(BaseModel):
    """Contexto solar para un observador en un instante (ADR-0024)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    # --- Identidad ---
    when: AwareDatetime
    observer_lat_deg: float
    observer_lon_deg: float
    observer_alt_m: float

    # --- Resultado ---
    sun_elevation_deg: float
    sun_azimuth_deg: float = Field(ge=0.0, lt=360.0)
    twilight_phase: TwilightPhase

    # --- Honesty fields (ADR-0020 pattern) ---
    solar_position_model: str = Field(default=SOLAR_POSITION_MODEL_NAME)
    shadow_model: str = Field(default=SHADOW_MODEL_NAME)
    atmospheric_refraction_assumed_zero: bool = Field(default=True)
    valid_date_range_iso: str = Field(default=VALID_DATE_RANGE_ISO)

    # --- Versioning ---
    schema_version: str = Field(default=SOLAR_GEOMETRY_SCHEMA_VERSION)
    engine_version: str = Field(default=SOLAR_GEOMETRY_ENGINE_VERSION)
    derived_at: AwareDatetime


# --- API pública --------------------------------------------------------


def solar_context_at(
    observer_lat_deg: float,
    observer_lon_deg: float,
    observer_alt_m: float,
    when: datetime,
) -> SolarContext:
    """Contexto solar (sun elevation/azimuth + twilight) para ``observer`` en ``when``."""
    _validate_observer(observer_lat_deg, observer_lon_deg, observer_alt_m)
    if when.tzinfo is None:
        raise ValueError("when debe ser timezone-aware (UTC esperado).")

    when_utc = when.astimezone(timezone.utc)

    # Posición solar en ECI ~ J2000
    sun_eci = sun_position_eci(when_utc)

    # ECI → ECEF (mismo paso que TEME → ECEF a esta precisión)
    sun_ecef = teme_to_ecef(sun_eci[0], sun_eci[1], sun_eci[2], when_utc)

    # Observador → ECEF
    obs_ecef = observer_to_ecef(observer_lat_deg, observer_lon_deg, observer_alt_m)

    # Delta sun − observer en ECEF → ENU → (elev, az)
    delta = (sun_ecef[0] - obs_ecef[0], sun_ecef[1] - obs_ecef[1], sun_ecef[2] - obs_ecef[2])
    east, north, up = ecef_to_enu(delta, observer_lat_deg, observer_lon_deg)
    elev_deg, az_deg, _ = enu_to_elevation_azimuth(east, north, up)

    return SolarContext(
        when=when_utc,
        observer_lat_deg=observer_lat_deg,
        observer_lon_deg=observer_lon_deg,
        observer_alt_m=observer_alt_m,
        sun_elevation_deg=elev_deg,
        sun_azimuth_deg=az_deg,
        twilight_phase=_classify_twilight(elev_deg),
        derived_at=_utc_now(),
    )


def is_satellite_illuminated(
    sat_position_eci_km: tuple[float, float, float],
    when: datetime,
) -> bool:
    """True si el satélite está iluminado por el Sol (sombra cilíndrica).

    Modelo cilíndrico v1: el satélite está iluminado si su posición está en el
    semi-espacio solar (sat · sun_hat > 0) o si su proyección perpendicular al
    eje Tierra-Sol excede el radio terrestre (queda fuera del cilindro de
    sombra).

    Error vs modelo cónico (umbra/penumbra real): ~10 s en entrada/salida de
    eclipse. Acotado, declarado en ``SHADOW_MODEL_NAME``.
    """
    if when.tzinfo is None:
        raise ValueError("when debe ser timezone-aware (UTC esperado).")
    sun_eci = sun_position_eci(when.astimezone(timezone.utc))
    sun_mag = math.sqrt(sun_eci[0] ** 2 + sun_eci[1] ** 2 + sun_eci[2] ** 2)
    if sun_mag == 0.0:
        return True  # caso degenerado teórico imposible
    sun_hat = (sun_eci[0] / sun_mag, sun_eci[1] / sun_mag, sun_eci[2] / sun_mag)

    sat_dot_sun = (
        sat_position_eci_km[0] * sun_hat[0]
        + sat_position_eci_km[1] * sun_hat[1]
        + sat_position_eci_km[2] * sun_hat[2]
    )
    if sat_dot_sun > 0.0:
        return True  # lado solar de la Tierra

    # Lado anti-solar: comprobar si la proyección perpendicular escapa al
    # cilindro de sombra (radio = R⊕).
    perp_x = sat_position_eci_km[0] - sat_dot_sun * sun_hat[0]
    perp_y = sat_position_eci_km[1] - sat_dot_sun * sun_hat[1]
    perp_z = sat_position_eci_km[2] - sat_dot_sun * sun_hat[2]
    perp_mag = math.sqrt(perp_x * perp_x + perp_y * perp_y + perp_z * perp_z)
    return perp_mag > EARTH_RADIUS_KM
