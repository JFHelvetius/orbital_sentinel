"""Features físicas observables a partir de un ``OrbitalElement`` (ADR-0028).

V0.1 solo usa información ya presente en el catálogo Normalized. No hay
nuevas fuentes de datos, no hay nuevas tablas. Las cuatro features de v0.1
son derivadas determinísticamente del propio ``OrbitalElement``:

* ``altitude_km`` — semieje mayor − R⊕ (vía Kepler 3rd law).
* ``eccentricity`` — directo del modelo.
* ``inclination_deg`` — directo del modelo.
* ``mean_motion`` — directo del modelo [rev/día].

Las features candidatas pendientes (``maneuver_frequency_count``,
``conjunction_frequency_count``) requieren agregar repositorios cross-domain
y se difieren a v0.2 con su propio ADR. Declarado en ADR-0028 §"Lo que no
decide".
"""

from __future__ import annotations

import math
from collections.abc import Sequence

from orbital_sentinel.catalog.orbital_elements import OrbitalElement

EARTH_GRAVITATIONAL_PARAMETER_KM3_S2 = 398_600.4418
EARTH_RADIUS_KM = 6371.0

AVAILABLE_FEATURES: tuple[str, ...] = (
    "altitude_km",
    "eccentricity",
    "inclination_deg",
    "mean_motion",
)
"""Tupla canónica e inmutable de features computables en v0.1."""


class UnknownFeatureError(ValueError):
    """Feature requerida no está en ``AVAILABLE_FEATURES``."""


def compute_feature(element: OrbitalElement, feature_name: str) -> float:
    """Devuelve el valor de ``feature_name`` para ``element``.

    Determinístico, sin estado, sin red. Raises ``UnknownFeatureError`` si
    ``feature_name`` no está en ``AVAILABLE_FEATURES``.
    """
    if feature_name == "altitude_km":
        return _altitude_km(element)
    if feature_name == "eccentricity":
        return element.eccentricity
    if feature_name == "inclination_deg":
        return element.inclination_deg
    if feature_name == "mean_motion":
        return element.mean_motion
    raise UnknownFeatureError(
        f"Feature desconocida: {feature_name!r}. "
        f"Disponibles: {AVAILABLE_FEATURES}"
    )


def compute_features(
    element: OrbitalElement, features: Sequence[str]
) -> dict[str, float]:
    """Computa múltiples features de un ``OrbitalElement`` en una sola pasada."""
    return {f: compute_feature(element, f) for f in features}


def _altitude_km(element: OrbitalElement) -> float:
    """Altitud media (semieje mayor − R⊕) desde mean motion vía Kepler 3rd law.

    Más estable que perigeo/apogeo individual cuando el operador quiere una
    señal escalar única por TLE.
    """
    n_rad_s = element.mean_motion * 2.0 * math.pi / 86400.0
    if n_rad_s <= 0.0:
        # Defensivo: mean_motion no físico. Devuelve 0 para que la baseline
        # absorba la anomalía como dato anómalo (no crash).
        return 0.0
    a_km: float = (
        EARTH_GRAVITATIONAL_PARAMETER_KM3_S2 / (n_rad_s * n_rad_s)
    ) ** (1.0 / 3.0)
    return a_km - EARTH_RADIUS_KM
