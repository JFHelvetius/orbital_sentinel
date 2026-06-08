"""Solar geometry primitives (ADR-0024)."""

from orbital_sentinel.analytics.solar.context import (
    SHADOW_MODEL_NAME,
    SOLAR_GEOMETRY_ENGINE_VERSION,
    SOLAR_GEOMETRY_SCHEMA_VERSION,
    SolarContext,
    TwilightPhase,
    is_satellite_illuminated,
    solar_context_at,
    twilight_darkness_rank,
)
from orbital_sentinel.analytics.solar.sun_position import (
    AU_KM,
    SOLAR_POSITION_MODEL_NAME,
    VALID_DATE_RANGE_ISO,
    sun_position_eci,
)

__all__ = [
    "AU_KM",
    "SHADOW_MODEL_NAME",
    "SOLAR_GEOMETRY_ENGINE_VERSION",
    "SOLAR_GEOMETRY_SCHEMA_VERSION",
    "SOLAR_POSITION_MODEL_NAME",
    "VALID_DATE_RANGE_ISO",
    "SolarContext",
    "TwilightPhase",
    "is_satellite_illuminated",
    "solar_context_at",
    "sun_position_eci",
    "twilight_darkness_rank",
]
