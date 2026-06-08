"""Transformaciones de marcos nativas a la salida del propagador (TEME).

Extraído desde ``orchestration/groundtrack.py`` por el refactor preparatorio de
ADR-0023, sin cambio de comportamiento. Cubre dos planos en el contrato del
proyecto:

* Es la primitiva geométrica usada por ``orchestration/groundtrack.py`` para
  rendering 2D estático (Fase 1).
* Es la primitiva geométrica que ``analytics/passes/`` consumirá en la
  iteración siguiente, sin acoplar ``analytics/`` a ``orchestration/``
  (ADR-0002 enmienda 1).

Modelo GMST: IAU 1982 simplificado, asumiendo UT1 ≈ UTC. La cota IERS sobre
``|DUT1| ≤ 0.9 s`` se traduce a un error angular máximo de ~6.6e-5 rad
(~13.5 arcsec), bien por debajo del régimen SGP4 dominante declarado en
ADR-0014 (~3 km baseline). El identificador machine-readable
``GMST_MODEL_NAME`` encodea esa asunción explícitamente: una eventual
implementación con DUT1 IERS real exigiría un identificador distinto.
"""

from __future__ import annotations

import math
from datetime import datetime

from sgp4.api import jday

GMST_MODEL_NAME = "iau_1982_ut1_equals_utc_v1"
"""Identificador del modelo GMST usado (ADR-0023).

Encodea la asunción UT1 ≈ UTC formalmente acotada por IERS a ``|DUT1| ≤ 0.9 s``.
Una implementación futura que incorpore DUT1 IERS real (por ejemplo, mediante
una tabla) requerirá un identificador diferente; este string permite a los
consumidores distinguir versiones machine-readable.
"""


def gmst_iau_1982(when: datetime) -> float:
    """GMST en radianes para un ``datetime`` UTC tz-aware.

    Fórmula IAU 1982 simplificada (sin nutación), asumiendo UT1 ≈ UTC. El
    error angular es muy inferior al régimen de incertidumbre SGP4 declarado
    en ADR-0014.
    """
    if when.tzinfo is None:
        raise ValueError("when debe ser timezone-aware (UTC esperado).")
    jd_int, jd_frac = jday(
        when.year,
        when.month,
        when.day,
        when.hour,
        when.minute,
        when.second + when.microsecond * 1e-6,
    )
    jd = jd_int + jd_frac
    t = (jd - 2451545.0) / 36525.0
    gmst_deg = (
        280.46061837
        + 360.98564736629 * (jd - 2451545.0)
        + 0.000387933 * t * t
        - t * t * t / 38710000.0
    )
    gmst_deg %= 360.0
    return math.radians(gmst_deg)


def teme_to_ecef(
    x_km: float, y_km: float, z_km: float, when: datetime
) -> tuple[float, float, float]:
    """Rotación TEME → ECEF usando GMST. Sin polar motion."""
    theta = gmst_iau_1982(when)
    cos_t = math.cos(theta)
    sin_t = math.sin(theta)
    ecef_x = x_km * cos_t + y_km * sin_t
    ecef_y = -x_km * sin_t + y_km * cos_t
    return ecef_x, ecef_y, z_km
