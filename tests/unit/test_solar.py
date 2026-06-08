"""Tests de solar geometry (ADR-0024)."""

from __future__ import annotations

import math
from datetime import datetime, timezone

import pytest

from orbital_sentinel.analytics.solar import (
    AU_KM,
    SHADOW_MODEL_NAME,
    SOLAR_GEOMETRY_ENGINE_VERSION,
    SOLAR_GEOMETRY_SCHEMA_VERSION,
    SOLAR_POSITION_MODEL_NAME,
    VALID_DATE_RANGE_ISO,
    SolarContext,
    TwilightPhase,
    is_satellite_illuminated,
    solar_context_at,
    sun_position_eci,
    twilight_darkness_rank,
)

# --- sun_position_eci ---------------------------------------------------


def test_sun_position_distance_within_au_range() -> None:
    """La distancia Tierra-Sol debe variar ~0.983-1.017 AU."""
    when = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    x, y, z = sun_position_eci(when)
    r = math.sqrt(x * x + y * y + z * z)
    assert 0.98 * AU_KM < r < 1.02 * AU_KM


def test_sun_position_perihelion_closer_than_aphelion() -> None:
    """Perihelio ~enero (r ≈ 0.983 AU), afelio ~julio (r ≈ 1.017 AU)."""
    perihelion = datetime(2024, 1, 3, 0, 0, 0, tzinfo=timezone.utc)
    aphelion = datetime(2024, 7, 4, 0, 0, 0, tzinfo=timezone.utc)
    r_peri = math.sqrt(sum(c * c for c in sun_position_eci(perihelion)))
    r_aphe = math.sqrt(sum(c * c for c in sun_position_eci(aphelion)))
    assert r_peri < r_aphe


def test_sun_position_rejects_naive_datetime() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        sun_position_eci(datetime(2024, 1, 1))


def test_sun_position_rejects_year_below_range() -> None:
    with pytest.raises(ValueError, match="rango válido"):
        sun_position_eci(datetime(1900, 1, 1, tzinfo=timezone.utc))


def test_sun_position_rejects_year_above_range() -> None:
    with pytest.raises(ValueError, match="rango válido"):
        sun_position_eci(datetime(2100, 1, 1, tzinfo=timezone.utc))


def test_sun_position_lies_near_ecliptic_plane() -> None:
    """En J2000: z/r = sin(ε)·sin(λ_ecl). Para múltiples instantes,
    z/r ∈ [-sin(23.44°), +sin(23.44°)]."""
    max_sin_obliquity = math.sin(math.radians(24.0))
    for month in (1, 4, 7, 10):
        when = datetime(2024, month, 15, 12, 0, 0, tzinfo=timezone.utc)
        x, y, z = sun_position_eci(when)
        r = math.sqrt(x * x + y * y + z * z)
        assert abs(z / r) < max_sin_obliquity


def test_sun_position_constants_have_expected_values() -> None:
    assert SOLAR_POSITION_MODEL_NAME == "vallado_2008_low_precision_v1"
    assert VALID_DATE_RANGE_ISO == "1950-01-01/2050-12-31"
    assert AU_KM == 149_597_870.7


# --- twilight classification --------------------------------------------


def test_twilight_phase_classification_for_known_elevations() -> None:
    """Boundary cases of la convención USNO."""
    # Pequeño helper: usar solar_context_at indirectamente con datetime conocido
    # produce siempre la misma fase para una elevación dada. Probamos
    # directamente el mapeo via _classify_twilight no exportado; en su lugar
    # construimos un SolarContext sintético no es viable porque la fase es
    # derivada. Usamos solar_context_at sobre el polo norte en diferentes
    # momentos del año (sol siempre arriba o abajo).
    # En el polo norte en solsticio de junio: sol siempre arriba → day.
    when_summer_pole = datetime(2024, 6, 21, 12, 0, 0, tzinfo=timezone.utc)
    ctx = solar_context_at(89.9, 0.0, 0.0, when_summer_pole)
    assert ctx.twilight_phase == TwilightPhase.DAY
    # En el polo norte en solsticio de diciembre: sol siempre abajo → night.
    when_winter_pole = datetime(2024, 12, 21, 12, 0, 0, tzinfo=timezone.utc)
    ctx2 = solar_context_at(89.9, 0.0, 0.0, when_winter_pole)
    assert ctx2.twilight_phase == TwilightPhase.NIGHT


def test_twilight_darkness_rank_ordering() -> None:
    """day < civil < nautical < astronomical < night."""
    assert (
        twilight_darkness_rank(TwilightPhase.DAY)
        < twilight_darkness_rank(TwilightPhase.CIVIL)
        < twilight_darkness_rank(TwilightPhase.NAUTICAL)
        < twilight_darkness_rank(TwilightPhase.ASTRONOMICAL)
        < twilight_darkness_rank(TwilightPhase.NIGHT)
    )


# --- solar_context_at honesty fields -----------------------------------


def test_solar_context_emits_honesty_and_versioning_fields() -> None:
    when = datetime(2024, 6, 21, 12, 0, 0, tzinfo=timezone.utc)
    ctx = solar_context_at(0.0, 0.0, 0.0, when)
    assert ctx.solar_position_model == SOLAR_POSITION_MODEL_NAME
    assert ctx.shadow_model == SHADOW_MODEL_NAME
    assert ctx.atmospheric_refraction_assumed_zero is True
    assert ctx.valid_date_range_iso == VALID_DATE_RANGE_ISO
    assert ctx.schema_version == SOLAR_GEOMETRY_SCHEMA_VERSION == "0.1.0"
    assert ctx.engine_version == SOLAR_GEOMETRY_ENGINE_VERSION == "0.1.0"


def test_solar_context_rejects_invalid_observer() -> None:
    when = datetime(2024, 6, 21, 12, 0, 0, tzinfo=timezone.utc)
    with pytest.raises(ValueError, match="observer_lat_deg"):
        solar_context_at(91.0, 0.0, 0.0, when)


def test_solar_context_rejects_naive_when() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        solar_context_at(0.0, 0.0, 0.0, datetime(2024, 6, 21, 12))


def test_solar_context_sun_elevation_high_at_noon_on_equator_in_equinox() -> None:
    """Equinoccio en el ecuador a mediodía solar: elevación ≈ 90°."""
    # Equinoccio vernal aproximado: 2024-03-20.
    # Mediodía solar a lon=0: aproximado al mediodía UTC.
    when = datetime(2024, 3, 20, 12, 0, 0, tzinfo=timezone.utc)
    ctx = solar_context_at(0.0, 0.0, 0.0, when)
    assert ctx.sun_elevation_deg > 80.0
    assert ctx.twilight_phase == TwilightPhase.DAY


def test_solar_context_azimuth_in_valid_range() -> None:
    when = datetime(2024, 6, 21, 12, 0, 0, tzinfo=timezone.utc)
    ctx = solar_context_at(45.0, 30.0, 100.0, when)
    assert 0.0 <= ctx.sun_azimuth_deg < 360.0


def test_solar_context_extra_forbid() -> None:
    when = datetime(2024, 6, 21, 12, 0, 0, tzinfo=timezone.utc)
    ctx = solar_context_at(0.0, 0.0, 0.0, when)
    with pytest.raises(Exception):
        SolarContext.model_validate({**ctx.model_dump(mode="json"), "extra": 1})


# --- is_satellite_illuminated -------------------------------------------


def test_satellite_at_sun_side_is_illuminated() -> None:
    """Satélite colocado lejos en la dirección del Sol → iluminado."""
    when = datetime(2024, 3, 21, 12, 0, 0, tzinfo=timezone.utc)
    # En equinoccio a mediodía UTC, el Sol está aproximadamente a (+AU, ~0, ~0)
    # en ECI. Colocamos el satélite en ese semi-espacio.
    sat_eci = (10_000.0, 0.0, 0.0)  # apuntando hacia el Sol
    assert is_satellite_illuminated(sat_eci, when) is True


def test_satellite_in_earth_shadow_is_not_illuminated() -> None:
    """Satélite directamente detrás de la Tierra respecto al Sol → en sombra."""
    when = datetime(2024, 3, 21, 12, 0, 0, tzinfo=timezone.utc)
    # Sol aprox en +X. Sombra cilíndrica se extiende en -X. Satélite a (-7000, 0, 0).
    sat_eci = (-7000.0, 0.0, 0.0)
    assert is_satellite_illuminated(sat_eci, when) is False


def test_satellite_outside_shadow_cylinder_illuminated() -> None:
    """Satélite en lado anti-solar pero fuera del cilindro de sombra."""
    when = datetime(2024, 3, 21, 12, 0, 0, tzinfo=timezone.utc)
    # En lado anti-solar pero con offset y grande (fuera del cilindro de R⊕).
    sat_eci = (-7000.0, 10_000.0, 0.0)
    assert is_satellite_illuminated(sat_eci, when) is True


def test_is_satellite_illuminated_rejects_naive_when() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        is_satellite_illuminated((7000.0, 0.0, 0.0), datetime(2024, 1, 1, 12))
