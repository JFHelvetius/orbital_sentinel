"""N-to-N pairwise screening (ADR-0018).

Toma una lista de objetos ``(OrbitalElement, TLESnapshot)``, analiza todos los
pares supervivientes a un filtro previo apogeo/perigeo, y devuelve los pares
cuya miss distance esté bajo un umbral.

Reusa ``analyze_pairwise_conjunction`` como ladrillo. No introduce nueva
matemática orbital más allá del cómputo de apogeo/perigeo desde mean motion y
excentricidad.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from itertools import combinations

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from orbital_sentinel.analytics.conjunctions.analysis import (
    SGP4_UNCERTAINTY_BASELINE_KM,
    ConjunctionAnalysis,
    analyze_pairwise_conjunction,
)
from orbital_sentinel.catalog.orbital_elements import OrbitalElement
from orbital_sentinel.catalog.tle_snapshots import TLESnapshot

SCREENING_SCHEMA_VERSION = "0.1.0"
"""SemVer del esquema ``ScreeningResult`` (ADR-0018)."""

SCREENING_ENGINE_VERSION = "0.1.0"
"""SemVer del algoritmo N-to-N (ADR-0018)."""

MAX_PAIRS_DEFAULT = 5000
"""Cap defensivo: N=100 → 4 950 pairs (justo bajo el cap)."""

EARTH_GRAVITATIONAL_PARAMETER_KM3_S2 = 398600.4418
"""GM de la Tierra [km³/s²]. Constante WGS84 estándar."""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ScreeningResult(BaseModel):
    """Resultado del screening N-to-N v0.3 (ADR-0018).

    Los counts permiten auditar el flujo: total → filtrados por apogeo/perigeo
    → analizados → detecciones bajo threshold. Sin estos counts el resultado
    parecería opaco al caller (¿cuántos pares descartó el filtro?).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    # --- Parámetros declarados ---
    window_start: AwareDatetime
    window_end: AwareDatetime
    step_minutes: float = Field(gt=0)
    threshold_km: float = Field(gt=0)
    apogee_perigee_filter_enabled: bool
    refine_tca_enabled: bool

    # --- Counts auditable ---
    n_objects: int = Field(ge=0)
    n_pairs_total: int = Field(ge=0)
    n_pairs_filtered_out: int = Field(ge=0)
    n_pairs_screened: int = Field(ge=0)
    n_detections: int = Field(ge=0)

    # --- Detecciones ---
    detections: list[ConjunctionAnalysis]

    # --- Honestidad declarada (ADR-0000 P2) ---
    sgp4_uncertainty_baseline_km: float = Field(
        default=SGP4_UNCERTAINTY_BASELINE_KM
    )

    # --- Versioning (ADR-0010) ---
    schema_version: str = Field(default=SCREENING_SCHEMA_VERSION)
    engine_version: str = Field(default=SCREENING_ENGINE_VERSION)
    derived_at: AwareDatetime


def analyze_pairwise_screening(
    elements_with_snapshots: Sequence[tuple[OrbitalElement, TLESnapshot]],
    *,
    window_start: datetime,
    window_end: datetime,
    step_minutes: float,
    threshold_km: float,
    apogee_perigee_filter: bool = True,
    refine_tca: bool = True,
    combined_hard_body_radius_km: float = 0.0,
    max_pairs: int = MAX_PAIRS_DEFAULT,
    clock: Callable[[], datetime] | None = None,
) -> ScreeningResult:
    """N-to-N pairwise screening.

    Args:
        elements_with_snapshots: lista de pares ``(OrbitalElement, TLESnapshot)``.
            Cada snapshot debe ser el origen del element (consistencia
            verificada dentro de ``analyze_pairwise_conjunction``).
        window_start, window_end: ventana UTC inclusiva.
        step_minutes: paso de la grid uniforme.
        threshold_km: detección = ``miss < threshold_km``.
        apogee_perigee_filter: si True (default), descarta pares cuyos rangos
            de altitud no se solapan dentro de ``threshold_km``.
        refine_tca: pasado a cada ``analyze_pairwise_conjunction`` (default True).
        max_pairs: cap defensivo sobre ``n*(n-1)/2``. Excederlo lanza.
        clock: inyectable para tests deterministas.

    Returns:
        ScreeningResult con counts auditable + lista de detecciones ordenadas
        por ``miss_distance_km`` ascendente.

    Raises:
        ValueError: si threshold_km ≤ 0, step_minutes ≤ 0, window invertida,
            o ``n_pairs_total > max_pairs``.
        PropagationError: si SGP4 falla para alguno de los objetos analizados.
    """
    if threshold_km <= 0:
        raise ValueError("threshold_km debe ser positivo.")
    if step_minutes <= 0:
        raise ValueError("step_minutes debe ser positivo.")
    if window_end < window_start:
        raise ValueError("window_end debe ser >= window_start.")

    n = len(elements_with_snapshots)
    n_pairs_total = n * (n - 1) // 2
    if n_pairs_total > max_pairs:
        raise ValueError(
            f"n_pairs_total={n_pairs_total} excede max_pairs={max_pairs}. "
            f"Reduce la lista o aumenta max_pairs explícitamente."
        )

    detections: list[ConjunctionAnalysis] = []
    n_filtered = 0
    n_screened = 0

    for (elt_a, snap_a), (elt_b, snap_b) in combinations(
        elements_with_snapshots, 2
    ):
        if apogee_perigee_filter and not _possible_conjunction(
            elt_a, elt_b, threshold_km
        ):
            n_filtered += 1
            continue

        n_screened += 1
        result = analyze_pairwise_conjunction(
            elt_a, snap_a, elt_b, snap_b,
            window_start=window_start,
            window_end=window_end,
            step_minutes=step_minutes,
            refine_tca=refine_tca,
            combined_hard_body_radius_km=combined_hard_body_radius_km,
            clock=clock,
        )
        if result.miss_distance_km < threshold_km:
            detections.append(result)

    detections.sort(key=lambda c: c.miss_distance_km)

    derived_at = (clock or _utc_now)()
    return ScreeningResult(
        window_start=window_start.astimezone(timezone.utc),
        window_end=window_end.astimezone(timezone.utc),
        step_minutes=step_minutes,
        threshold_km=threshold_km,
        apogee_perigee_filter_enabled=apogee_perigee_filter,
        refine_tca_enabled=refine_tca,
        n_objects=n,
        n_pairs_total=n_pairs_total,
        n_pairs_filtered_out=n_filtered,
        n_pairs_screened=n_screened,
        n_detections=len(detections),
        detections=detections,
        derived_at=derived_at,
    )


# --- Helpers de filtrado apogeo/perigeo ---------------------------------


def _apogee_perigee_km(element: OrbitalElement) -> tuple[float, float]:
    """Distancia perigeo y apogeo desde el centro de la Tierra [km].

    Derivado de mean_motion (rev/día) y eccentricity vía Kepler:

        n_rad_s = mean_motion · 2π / 86400
        a_km    = (GM / n_rad_s²)^(1/3)
        perigee = a · (1 - e)
        apogee  = a · (1 + e)
    """
    n_rad_s = element.mean_motion * 2.0 * math.pi / 86400.0
    a_km = (EARTH_GRAVITATIONAL_PARAMETER_KM3_S2 / (n_rad_s * n_rad_s)) ** (1.0 / 3.0)
    perigee_km = a_km * (1.0 - element.eccentricity)
    apogee_km = a_km * (1.0 + element.eccentricity)
    return perigee_km, apogee_km


def _possible_conjunction(
    elt_a: OrbitalElement,
    elt_b: OrbitalElement,
    threshold_km: float,
) -> bool:
    """True si los rangos de altitud pueden acercarse a ``threshold_km`` o menos.

    No descarta pares que podrían conjuntar; solo descarta pares que es
    físicamente imposible que se acerquen dentro del threshold dado el
    régimen de altitudes.
    """
    perigee_a, apogee_a = _apogee_perigee_km(elt_a)
    perigee_b, apogee_b = _apogee_perigee_km(elt_b)
    if apogee_a + threshold_km < perigee_b:
        return False
    return not apogee_b + threshold_km < perigee_a
