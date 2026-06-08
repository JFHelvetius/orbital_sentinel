"""Posición solar analítica low-precision (ADR-0024).

Fórmula Vallado 2008 §5.1, error angular ~0.01° (~600 km en 1 UA). Bajo el
régimen SGP4 declarado en ADR-0014 (~3 km a ~1000 km range = ~0.17° angular),
es un orden de magnitud por debajo del error dominante. Sin dependencias
externas; usa ``sgp4.api.jday`` que ya pertenece al entorno declarado.

Marco: ECI ~J2000 inertial. La diferencia con TEME a esta precisión es
sub-arcsec; el output es válido para usarse como ECI o TEME en cómputos de
sombra y elevación solar.
"""

from __future__ import annotations

import math
from datetime import datetime

from sgp4.api import jday

AU_KM = 149_597_870.7
"""Unidad astronómica en kilómetros (IAU 2012)."""

SOLAR_POSITION_MODEL_NAME = "vallado_2008_low_precision_v1"
"""Identificador del modelo solar (ADR-0024)."""

VALID_DATE_RANGE_ISO = "1950-01-01/2050-12-31"
"""Rango temporal válido para la fórmula low-precision.

Fuera de este rango el error secular crece sin cota acotada. Una implementación
futura con efemérides JPL exigiría un identificador distinto.
"""

_VALID_YEAR_MIN = 1950
_VALID_YEAR_MAX = 2050


def sun_position_eci(when: datetime) -> tuple[float, float, float]:
    """Posición solar en ECI ~J2000 [km] en el instante ``when`` UTC.

    Raises:
        ValueError: si ``when`` no es tz-aware o está fuera de
            ``VALID_DATE_RANGE_ISO``.
    """
    if when.tzinfo is None:
        raise ValueError("when debe ser timezone-aware (UTC esperado).")
    if when.year < _VALID_YEAR_MIN or when.year > _VALID_YEAR_MAX:
        raise ValueError(
            f"when fuera del rango válido {VALID_DATE_RANGE_ISO}: año {when.year}"
        )

    jd_int, jd_frac = jday(
        when.year, when.month, when.day,
        when.hour, when.minute,
        when.second + when.microsecond * 1e-6,
    )
    jd = jd_int + jd_frac
    t_ut1 = (jd - 2451545.0) / 36525.0

    # Longitudes en grados, normalizadas a [0, 360)
    lambda_m_sun_deg = (280.4606184 + 36000.77005361 * t_ut1) % 360.0
    m_sun_deg = (357.5277233 + 35999.05034 * t_ut1) % 360.0

    m_sun_rad = math.radians(m_sun_deg)
    lambda_ecl_deg = (
        lambda_m_sun_deg
        + 1.914666471 * math.sin(m_sun_rad)
        + 0.019994643 * math.sin(2.0 * m_sun_rad)
    )
    lambda_ecl_rad = math.radians(lambda_ecl_deg)

    # Distancia Tierra-Sol en AU
    r_sun_au = (
        1.000140612
        - 0.016708617 * math.cos(m_sun_rad)
        - 0.000139589 * math.cos(2.0 * m_sun_rad)
    )

    # Oblicuidad de la eclíptica
    epsilon_deg = 23.439291 - 0.0130042 * t_ut1
    epsilon_rad = math.radians(epsilon_deg)

    # Posición en ECI cartesiano [AU], luego escalar a km
    x_au = r_sun_au * math.cos(lambda_ecl_rad)
    y_au = r_sun_au * math.cos(epsilon_rad) * math.sin(lambda_ecl_rad)
    z_au = r_sun_au * math.sin(epsilon_rad) * math.sin(lambda_ecl_rad)
    return x_au * AU_KM, y_au * AU_KM, z_au * AU_KM
