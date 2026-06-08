"""Análisis de conjunción pairwise (ADR-0016).

Pairwise puro: dos NORAD IDs específicos en una ventana temporal con grid
uniforme.

Cada resultado lleva:

* **Provenance binaria** (doble FK a Raw vía Normalized) para ambos objetos.
* **Régimen de precisión declarado** (ADR-0014 enmienda 1, mitigación de
  red-team F6 + ADR-0000 P2). El caller que ignore estos campos está
  usando mal el sistema.
* **Versioning** ADR-0010.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from datetime import datetime, timedelta, timezone

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from orbital_sentinel.analytics.conjunctions.probability import (
    COVARIANCE_BASELINE_SIGMA_KM,
    COVARIANCE_GROWTH_SIGMA_KM_PER_DAY,
    COVARIANCE_MODEL_NAME,
    PC_METHOD_NAME,
    combined_sigma_at_tca_km,
    pc_foster_fast,
)
from orbital_sentinel.catalog.orbital_elements import OrbitalElement
from orbital_sentinel.catalog.tle_snapshots import TLESnapshot
from orbital_sentinel.propagation import Sgp4Propagator

CONJUNCTION_SCHEMA_VERSION = "0.3.0"
"""SemVer del esquema de ConjunctionAnalysis (ADR-0010).

v0.2.0 (ADR-0017): añade campo ``tca_was_refined``.
v0.3.0 (ADR-0020): añade 7 campos de Pc + covarianza declarada.
"""

CONJUNCTION_ENGINE_VERSION = "0.3.0"
"""SemVer del algoritmo pairwise (ADR-0010 engine_version).

v0.2.0 (ADR-0017): refinamiento de TCA por bisección.
v0.3.0 (ADR-0020): cómputo de Pc con covarianza declarada (Foster fast).
"""

TCA_REFINEMENT_TOLERANCE_SECONDS = 1.0
"""Tolerancia de bisección para el refinamiento del TCA (ADR-0017).

Justificación: la incertidumbre física SGP4 baseline (~1-3 km en TEME) a
velocidad relativa típica (~7 km/s) implica que la resolución temporal útil
está alrededor del segundo. Refinar más fino es ruido.
"""

SGP4_UNCERTAINTY_BASELINE_KM = 3.0
"""Error típico SGP4 sobre TLE en época (ADR-0014, F6)."""

SGP4_UNCERTAINTY_GROWTH_KM_PER_DAY = 3.0
"""Crecimiento típico del error SGP4 por día desde época."""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ConjunctionAnalysis(BaseModel):
    """Resultado del análisis pairwise de conjunción entre dos objetos.

    Cada instancia es self-contained. La lista autoritativa de campos y su
    significado vive en las declaraciones del modelo a continuación.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    # --- Identidad ---
    norad_a: int = Field(description="NORAD ID del objeto A.")
    norad_b: int = Field(description="NORAD ID del objeto B.")

    # --- Provenance doble (FK Raw → Normalized → Derived) ---
    element_a_content_hash_source: str
    element_a_tle_index: int
    element_a_tle_content_hash: str
    element_b_content_hash_source: str
    element_b_tle_index: int
    element_b_tle_content_hash: str

    # --- Ventana evaluada ---
    window_start: AwareDatetime
    window_end: AwareDatetime
    step_minutes: float = Field(gt=0)
    n_samples: int = Field(ge=1, description="Instantes evaluados en la grid.")

    # --- Resultado ---
    tca: AwareDatetime = Field(
        description="Time of closest approach (discreto en la grid)."
    )
    miss_distance_km: float = Field(ge=0)
    relative_velocity_km_s: float = Field(ge=0)
    minutes_from_epoch_a_at_tca: float
    minutes_from_epoch_b_at_tca: float

    # --- Régimen de precisión declarado (ADR-0000 P2 + ADR-0014 F6) ---
    sgp4_uncertainty_baseline_km: float = Field(
        default=SGP4_UNCERTAINTY_BASELINE_KM,
        description="Error típico SGP4 en época [km].",
    )
    sgp4_uncertainty_growth_km_per_day: float = Field(
        default=SGP4_UNCERTAINTY_GROWTH_KM_PER_DAY,
        description="Crecimiento típico del error SGP4 [km/día].",
    )
    tca_resolution_minutes: float = Field(
        description=(
            "Resolución temporal del TCA. "
            "Si tca_was_refined=True: TCA_REFINEMENT_TOLERANCE_SECONDS / 60. "
            "Si tca_was_refined=False: step_minutes."
        )
    )
    tca_was_refined: bool = Field(
        default=False,
        description=(
            "True si TCA refinado por bisección (ADR-0017). "
            "False si está al borde de la ventana o el bracket es degenerado."
        ),
    )

    # --- Pc y assumption fields (ADR-0020 v1.0) ---
    pc: float = Field(
        ge=0.0,
        le=1.0,
        description=(
            "Probability of collision bajo covarianza declarada. "
            "NO interpretable sin los demás campos de covarianza."
        ),
    )
    combined_hard_body_radius_km: float = Field(
        ge=0.0,
        description="R: suma de radios físicos declarados por el caller [km].",
    )
    covariance_model_name: str = Field(
        description="Identificador del modelo de covarianza (ADR-0020)."
    )
    covariance_baseline_sigma_km: float = Field(
        ge=0.0,
        description="σ₀: 1-sigma posición en época [km].",
    )
    covariance_growth_sigma_km_per_day: float = Field(
        ge=0.0,
        description="α: crecimiento lineal de 1-sigma [km/día].",
    )
    combined_sigma_at_tca_km: float = Field(
        ge=0.0,
        description="σ resultante combinada en el TCA [km].",
    )
    pc_method: str = Field(
        description="Identificador del método de Pc usado (ADR-0020)."
    )

    # --- Versioning (ADR-0010) ---
    schema_version: str = Field(default=CONJUNCTION_SCHEMA_VERSION)
    engine_version: str = Field(default=CONJUNCTION_ENGINE_VERSION)
    derived_at: AwareDatetime


def analyze_pairwise_conjunction(
    element_a: OrbitalElement,
    snapshot_a: TLESnapshot,
    element_b: OrbitalElement,
    snapshot_b: TLESnapshot,
    *,
    window_start: datetime,
    window_end: datetime,
    step_minutes: float,
    refine_tca: bool = True,
    refinement_tolerance_seconds: float = TCA_REFINEMENT_TOLERANCE_SECONDS,
    combined_hard_body_radius_km: float = 0.0,
    clock: Callable[[], datetime] | None = None,
) -> ConjunctionAnalysis:
    """Encuentra el TCA de mínima distancia entre dos objetos.

    Args:
        element_a, snapshot_a: par Normalized + Raw del objeto A.
        element_b, snapshot_b: par Normalized + Raw del objeto B.
        window_start, window_end: ventana UTC tz-aware, inclusiva.
        step_minutes: paso de la grid uniforme (> 0).
        refine_tca: si True (default), refina TCA por bisección sobre
            f(t) = (r_a - r_b) · (v_a - v_b) en el bracket
            [t_{k-1}, t_{k+1}] alrededor del mínimo discreto (ADR-0017).
        refinement_tolerance_seconds: tolerancia de la bisección en segundos.
            Default ``TCA_REFINEMENT_TOLERANCE_SECONDS``.
        clock: inyectable para tests deterministas.

    Returns:
        ConjunctionAnalysis con TCA (refinado o discreto), miss distance,
        velocidad relativa, régimen de precisión declarado y ``tca_was_refined``.

    Raises:
        ValueError: si ``step_minutes`` ≤ 0 o ``window_end < window_start``.
        PropagationError: si SGP4 falla para alguno de los dos objetos.
    """
    if step_minutes <= 0:
        raise ValueError("step_minutes debe ser positivo.")
    if window_end < window_start:
        raise ValueError("window_end debe ser >= window_start.")

    times = _build_times(window_start, window_end, step_minutes)
    if not times:
        raise ValueError("La ventana no genera ningún instante (vacía).")

    propagator = Sgp4Propagator()
    ephem_a = propagator.propagate(element_a, snapshot_a, times)
    ephem_b = propagator.propagate(element_b, snapshot_b, times)

    min_d2 = math.inf
    min_idx = 0
    for i in range(len(times)):
        dx = ephem_a[i].position_teme_x_km - ephem_b[i].position_teme_x_km
        dy = ephem_a[i].position_teme_y_km - ephem_b[i].position_teme_y_km
        dz = ephem_a[i].position_teme_z_km - ephem_b[i].position_teme_z_km
        d2 = dx * dx + dy * dy + dz * dz
        if d2 < min_d2:
            min_d2 = d2
            min_idx = i

    # --- Refinamiento de TCA (ADR-0017) ---
    tca_was_refined = False
    refined_tca: datetime | None = None
    if (
        refine_tca
        and 0 < min_idx < len(times) - 1
    ):
        refined_tca = _refine_tca_bisection(
            propagator,
            element_a, snapshot_a, element_b, snapshot_b,
            t_left=times[min_idx - 1],
            t_right=times[min_idx + 1],
            tolerance_seconds=refinement_tolerance_seconds,
        )
        tca_was_refined = refined_tca is not None

    if tca_was_refined and refined_tca is not None:
        # Reevaluar a TCA refinado para obtener miss y velocidad exactos
        [e_a_tca] = propagator.propagate(element_a, snapshot_a, [refined_tca])
        [e_b_tca] = propagator.propagate(element_b, snapshot_b, [refined_tca])
        tca = refined_tca
        tca_resolution_minutes = refinement_tolerance_seconds / 60.0
    else:
        e_a_tca = ephem_a[min_idx]
        e_b_tca = ephem_b[min_idx]
        tca = times[min_idx]
        tca_resolution_minutes = step_minutes

    dx = e_a_tca.position_teme_x_km - e_b_tca.position_teme_x_km
    dy = e_a_tca.position_teme_y_km - e_b_tca.position_teme_y_km
    dz = e_a_tca.position_teme_z_km - e_b_tca.position_teme_z_km
    miss = math.sqrt(dx * dx + dy * dy + dz * dz)
    rvx = e_a_tca.velocity_teme_x_km_s - e_b_tca.velocity_teme_x_km_s
    rvy = e_a_tca.velocity_teme_y_km_s - e_b_tca.velocity_teme_y_km_s
    rvz = e_a_tca.velocity_teme_z_km_s - e_b_tca.velocity_teme_z_km_s
    rel_v = math.sqrt(rvx * rvx + rvy * rvy + rvz * rvz)

    derived_at = (clock or _utc_now)()

    # Pc bajo covarianza declarada (ADR-0020 v1.0).
    sigma_combined = combined_sigma_at_tca_km(
        e_a_tca.minutes_from_epoch,
        e_b_tca.minutes_from_epoch,
    )
    pc_value = pc_foster_fast(
        miss_distance_km=miss,
        combined_sigma_km=sigma_combined,
        combined_hard_body_radius_km=combined_hard_body_radius_km,
    )

    return ConjunctionAnalysis(
        norad_a=element_a.norad_cat_id,
        norad_b=element_b.norad_cat_id,
        element_a_content_hash_source=element_a.content_hash_source,
        element_a_tle_index=element_a.tle_index,
        element_a_tle_content_hash=element_a.tle_content_hash,
        element_b_content_hash_source=element_b.content_hash_source,
        element_b_tle_index=element_b.tle_index,
        element_b_tle_content_hash=element_b.tle_content_hash,
        window_start=window_start.astimezone(timezone.utc),
        window_end=window_end.astimezone(timezone.utc),
        step_minutes=step_minutes,
        n_samples=len(times),
        tca=tca,
        miss_distance_km=miss,
        relative_velocity_km_s=rel_v,
        minutes_from_epoch_a_at_tca=e_a_tca.minutes_from_epoch,
        minutes_from_epoch_b_at_tca=e_b_tca.minutes_from_epoch,
        tca_resolution_minutes=tca_resolution_minutes,
        tca_was_refined=tca_was_refined,
        pc=pc_value,
        combined_hard_body_radius_km=combined_hard_body_radius_km,
        covariance_model_name=COVARIANCE_MODEL_NAME,
        covariance_baseline_sigma_km=COVARIANCE_BASELINE_SIGMA_KM,
        covariance_growth_sigma_km_per_day=COVARIANCE_GROWTH_SIGMA_KM_PER_DAY,
        combined_sigma_at_tca_km=sigma_combined,
        pc_method=PC_METHOD_NAME,
        derived_at=derived_at,
    )


def _f_relative_dot(
    propagator: Sgp4Propagator,
    element_a: OrbitalElement,
    snapshot_a: TLESnapshot,
    element_b: OrbitalElement,
    snapshot_b: TLESnapshot,
    t: datetime,
) -> float:
    """Evalúa f(t) = (r_a - r_b) · (v_a - v_b) en TEME [km²/s].

    f cambia de signo de negativo (aproximándose) a positivo (alejándose) en el
    TCA. Su cero define el closest approach.
    """
    [e_a] = propagator.propagate(element_a, snapshot_a, [t])
    [e_b] = propagator.propagate(element_b, snapshot_b, [t])
    rx = e_a.position_teme_x_km - e_b.position_teme_x_km
    ry = e_a.position_teme_y_km - e_b.position_teme_y_km
    rz = e_a.position_teme_z_km - e_b.position_teme_z_km
    vx = e_a.velocity_teme_x_km_s - e_b.velocity_teme_x_km_s
    vy = e_a.velocity_teme_y_km_s - e_b.velocity_teme_y_km_s
    vz = e_a.velocity_teme_z_km_s - e_b.velocity_teme_z_km_s
    return rx * vx + ry * vy + rz * vz


def _refine_tca_bisection(
    propagator: Sgp4Propagator,
    element_a: OrbitalElement,
    snapshot_a: TLESnapshot,
    element_b: OrbitalElement,
    snapshot_b: TLESnapshot,
    *,
    t_left: datetime,
    t_right: datetime,
    tolerance_seconds: float,
) -> datetime | None:
    """Bisección sobre f(t) = (r·v) en ``[t_left, t_right]`` hasta ``tolerance_seconds``.

    Devuelve el TCA refinado, o ``None`` si f no cambia de signo en el bracket
    (caso degenerado: fallback al discreto en el caller).
    """
    f_left = _f_relative_dot(propagator, element_a, snapshot_a, element_b, snapshot_b, t_left)
    f_right = _f_relative_dot(propagator, element_a, snapshot_a, element_b, snapshot_b, t_right)
    if f_left * f_right > 0:
        return None

    tolerance = timedelta(seconds=tolerance_seconds)
    while (t_right - t_left) > tolerance:
        t_mid = t_left + (t_right - t_left) / 2
        f_mid = _f_relative_dot(
            propagator, element_a, snapshot_a, element_b, snapshot_b, t_mid
        )
        if f_left * f_mid <= 0:
            t_right = t_mid
            f_right = f_mid
        else:
            t_left = t_mid
            f_left = f_mid

    return t_left + (t_right - t_left) / 2


def _build_times(
    start: datetime, end: datetime, step_minutes: float
) -> list[datetime]:
    """Grid uniforme inclusiva de instantes UTC."""
    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError("window_start y window_end deben ser timezone-aware.")
    start = start.astimezone(timezone.utc)
    end = end.astimezone(timezone.utc)
    times: list[datetime] = []
    step = timedelta(minutes=step_minutes)
    t = start
    while t <= end:
        times.append(t)
        t += step
    return times
