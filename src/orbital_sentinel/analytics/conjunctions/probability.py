"""Cálculo de probabilidad de colisión (Pc) bajo covarianza declarada (ADR-0020).

Fundamental: este módulo nunca devuelve un Pc sin las assumption fields que
lo contextualizan. El número Pc en aislamiento es deshonesto; con su contexto
(modelo de covarianza, σ resultante, método, R) es honesto.

Modelo de covarianza por defecto: `tle_isotropic_spherical_v1`.

    σ(Δt_min) = σ₀ + α · |Δt_min| / 1440
    σ_combined²(TCA) = σ_a²(Δt_a) + σ_b²(Δt_b)

con σ₀ = 1 km, α = 1 km/día. Asunción declarada, NO covarianza medida.

Método Pc por defecto: Foster (1992) fast approximation para covarianza
isotropic spherical.

    Pc ≈ (R² / 2σ²) · exp(-d² / 2σ²)

Válida cuando R << σ (típicamente R/σ < 0.01 para satélites en LEO+).
"""

from __future__ import annotations

import math

COVARIANCE_MODEL_NAME = "tle_isotropic_spherical_v1"
"""Identificador del modelo de covarianza por defecto (ADR-0020)."""

COVARIANCE_BASELINE_SIGMA_KM = 1.0
"""1-sigma posición en la época del TLE [km]. Asunción declarada."""

COVARIANCE_GROWTH_SIGMA_KM_PER_DAY = 1.0
"""Crecimiento lineal de 1-sigma [km/día]. Asunción declarada."""

PC_METHOD_NAME = "foster_1992_fast_approximation"
"""Identificador del método de Pc por defecto (ADR-0020)."""


def sigma_tle_isotropic_km(minutes_from_epoch_abs: float) -> float:
    """1-sigma posición [km] para un TLE propagado ``|Δt|`` minutos desde su epoch.

    σ(Δt) = σ₀ + α · |Δt_days|

    Modelo isotropic spherical (ADR-0020). NO es la covarianza real medida;
    es una asunción defensible dentro del rango de Vallado 2008.
    """
    delta_days = minutes_from_epoch_abs / 1440.0
    return COVARIANCE_BASELINE_SIGMA_KM + COVARIANCE_GROWTH_SIGMA_KM_PER_DAY * delta_days


def combined_sigma_at_tca_km(
    minutes_from_epoch_a: float, minutes_from_epoch_b: float
) -> float:
    """Sigma combinada en TCA: ``sqrt(σ_a² + σ_b²)`` (independencia asumida)."""
    sa = sigma_tle_isotropic_km(abs(minutes_from_epoch_a))
    sb = sigma_tle_isotropic_km(abs(minutes_from_epoch_b))
    return math.sqrt(sa * sa + sb * sb)


def pc_foster_fast(
    miss_distance_km: float,
    combined_sigma_km: float,
    combined_hard_body_radius_km: float,
) -> float:
    """Probabilidad de colisión por aproximación rápida de Foster 1992.

    Para covarianza isotropic spherical:

        Pc ≈ (R² / 2σ²) · exp(-d² / 2σ²)

    donde ``R`` es el radio combinado de hard-body, ``σ`` el sigma combinado
    posicional en el TCA y ``d`` la miss distance.

    Edge cases:
    - ``R = 0`` (default): Pc = 0. Objetos puntuales no colisionan.
    - ``σ = 0``: degenerado. Determinista: Pc = 1 si d ≤ R, else 0.
    - Resultado siempre en ``[0, 1]``.

    La aproximación es válida cuando ``R << σ`` (típicamente R/σ < 0.01).
    El sistema no lanza si R/σ > 0.1; el caller debe interpretar con
    escepticismo adicional.
    """
    if combined_hard_body_radius_km <= 0.0:
        return 0.0
    if combined_sigma_km <= 0.0:
        return 1.0 if miss_distance_km <= combined_hard_body_radius_km else 0.0

    sigma2 = combined_sigma_km * combined_sigma_km
    r2 = combined_hard_body_radius_km * combined_hard_body_radius_km
    d2 = miss_distance_km * miss_distance_km

    pc = (r2 / (2.0 * sigma2)) * math.exp(-d2 / (2.0 * sigma2))
    # Por construcción matemática Pc puede exceder 1 si R > σ; aquí es
    # mínimo (raro), pero por defensa clampeamos.
    return min(pc, 1.0)
