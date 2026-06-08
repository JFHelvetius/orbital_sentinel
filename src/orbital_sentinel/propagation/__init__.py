"""Plano Propagation: motor SGP4 sobre la capa Normalized (ADR-0005, ADR-0014).

On-demand por defecto. No persiste. No incluye conjunciones, maniobras,
anomalías ni visualización: esos son trabajos de planos superiores.

Incluye también ``frames`` (ADR-0023): transformaciones de marco TEME→ECEF y
GMST IAU 1982. Son primitivas geométricas del propagador, consumidas tanto por
``orchestration/groundtrack.py`` como por los módulos de ``analytics/`` que
las necesiten sin acoplarse a ``orchestration/``.
"""

from orbital_sentinel.propagation.ephemeris import (
    EPHEMERIS_SCHEMA_VERSION,
    Ephemeris,
)
from orbital_sentinel.propagation.frames import (
    GMST_MODEL_NAME,
    gmst_iau_1982,
    teme_to_ecef,
)
from orbital_sentinel.propagation.propagator import Propagator
from orbital_sentinel.propagation.sgp4_propagator import (
    SGP4_PROPAGATOR_VERSION,
    Sgp4Propagator,
)

__all__ = [
    "EPHEMERIS_SCHEMA_VERSION",
    "GMST_MODEL_NAME",
    "SGP4_PROPAGATOR_VERSION",
    "Ephemeris",
    "Propagator",
    "Sgp4Propagator",
    "gmst_iau_1982",
    "teme_to_ecef",
]
