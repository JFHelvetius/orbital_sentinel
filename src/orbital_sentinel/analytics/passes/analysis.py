"""Pass prediction v0.1 (ADR-0023).

Predicción de pases visibles de un satélite sobre un observador geográfico.
Sin red, sin persistencia, sin visualización, sin Doppler, sin iluminación
solar (ADR-0024) y sin agregación multi-satélite (ADR-0025).

Estructura del cálculo:

1. Grid uniforme de instantes ``window_start → window_end`` con paso
   ``step_minutes``.
2. Propagación SGP4 batch sobre el grid (una sola llamada al propagador).
3. Conversión TEME→ECEF→ENU→(elevation, azimuth) en cada instante usando los
   helpers de ``analytics.passes.geometry`` y ``propagation.frames``.
4. Identificación de segmentos contiguos donde ``elevation ≥ min_elevation_deg``.
5. Refinamiento AOS y LOS por bisección sobre ``f(t)=elev(t)-min_elev``
   (mismo patrón que ADR-0017 ``r·v``).
6. Refinamiento de culminación por ajuste parabólico local de 3 muestras.
7. Cómputo de azimuth en AOS / culminación / LOS (3 propagaciones extra
   por pase).

Honestidad declarada (ADR-0000 P2, ADR-0020 pattern): cada
``PassPrediction`` lleva ``frame_model``, ``gmst_model``,
``aos_los_resolution_seconds``, ``culmination_method`` y dos campos de
incertidumbre SGP4 (ADR-0014). El número de elevación nunca viaja solo.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from datetime import datetime, timedelta, timezone

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from orbital_sentinel.analytics.passes.geometry import (
    FRAME_MODEL_NAME,
    ecef_to_enu,
    enu_to_elevation_azimuth,
    observer_to_ecef,
)
from orbital_sentinel.catalog.orbital_elements import OrbitalElement
from orbital_sentinel.catalog.tle_snapshots import TLESnapshot
from orbital_sentinel.propagation import (
    GMST_MODEL_NAME,
    Sgp4Propagator,
    teme_to_ecef,
)

# --- Constantes públicas declaradas por el módulo (ADR-0010 + ADR-0023) ---

PASS_PREDICTION_SCHEMA_VERSION = "0.1.0"
"""SemVer del esquema de ``PassPrediction`` (ADR-0010)."""

PASS_PREDICTION_ENGINE_VERSION = "0.1.0"
"""SemVer del algoritmo de pass prediction (ADR-0010 engine_version)."""

CULMINATION_METHOD_NAME = "parabolic_local_fit_v1"
"""Identificador del método de refinamiento de la culminación (ADR-0023)."""

AOS_LOS_TOLERANCE_SECONDS_DEFAULT = 1.0
"""Tolerancia por defecto de la bisección AOS/LOS [s]."""

SGP4_UNCERTAINTY_BASELINE_KM = 3.0
"""Error típico SGP4 en época [km] (ADR-0014)."""

SGP4_UNCERTAINTY_GROWTH_KM_PER_DAY = 3.0
"""Crecimiento típico del error SGP4 [km/día] (ADR-0014)."""

# Cap defensivo sobre el tamaño del grid (consistente con CLI ``propagate``).
MAX_GRID_POINTS = 100_000

# Rangos válidos de coordenadas observador (ADR-0023 enmienda 3).
_OBSERVER_LAT_RANGE = (-90.0, 90.0)
_OBSERVER_LON_RANGE = (-180.0, 180.0)
_OBSERVER_ALT_RANGE_M = (-11_000.0, 100_000.0)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


# --- Modelos -------------------------------------------------------------


class Pass(BaseModel):
    """Un pase individual de un satélite sobre un observador.

    Self-contained: contiene los tres instantes clave (AOS, culminación, LOS),
    sus azimuths, la duración derivada, la elevación máxima, y los flags de
    refinamiento / pase parcial al borde de ventana.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    # --- Instantes ---
    aos_time: AwareDatetime = Field(description="Entrada al cono de visibilidad.")
    culmination_time: AwareDatetime = Field(
        description="Instante de máxima elevación (no min-range)."
    )
    los_time: AwareDatetime = Field(description="Salida del cono de visibilidad.")

    # --- Banderas ---
    aos_was_refined: bool = Field(
        description="True si AOS por bisección; False si pase parcial en borde."
    )
    los_was_refined: bool = Field(
        description="True si LOS por bisección; False si pase parcial en borde."
    )
    partial_aos: bool = Field(
        description="True si el pase ya estaba en curso al inicio de la ventana."
    )
    partial_los: bool = Field(
        description="True si el pase aún estaba en curso al final de la ventana."
    )

    # --- Magnitudes ---
    duration_seconds: float = Field(ge=0.0)
    max_elevation_deg: float
    aos_azimuth_deg: float = Field(ge=0.0, lt=360.0)
    culmination_azimuth_deg: float = Field(ge=0.0, lt=360.0)
    los_azimuth_deg: float = Field(ge=0.0, lt=360.0)


class PassPrediction(BaseModel):
    """Resultado completo de :func:`predict_passes` para una invocación.

    Lleva identidad observador + satélite, provenance binaria FK Raw→Normalized,
    ventana, lista de pases, y los campos de honestidad declarados por ADR-0023
    (frame, GMST, resoluciones, método de culminación, incertidumbre SGP4) +
    versioning ADR-0010.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    # --- Identidad ---
    norad_cat_id: int = Field(description="NORAD ID del objeto.")
    observer_lat_deg: float
    observer_lon_deg: float
    observer_alt_m: float

    # --- Provenance (FK Raw → Normalized → Derived) ---
    element_content_hash_source: str
    element_tle_index: int
    element_tle_content_hash: str

    # --- Ventana ---
    window_start: AwareDatetime
    window_end: AwareDatetime
    step_minutes: float = Field(gt=0.0)
    min_elevation_deg: float

    # --- Resultado ---
    passes: list[Pass]
    n_passes: int = Field(ge=0)

    # --- Régimen de precisión declarado (ADR-0000 P2 + ADR-0020 pattern) ---
    frame_model: str = Field(default=FRAME_MODEL_NAME)
    gmst_model: str = Field(default=GMST_MODEL_NAME)
    aos_los_resolution_seconds: float = Field(gt=0.0)
    culmination_method: str = Field(default=CULMINATION_METHOD_NAME)
    sgp4_uncertainty_baseline_km: float = Field(default=SGP4_UNCERTAINTY_BASELINE_KM)
    sgp4_uncertainty_growth_km_per_day: float = Field(
        default=SGP4_UNCERTAINTY_GROWTH_KM_PER_DAY
    )

    # --- Versioning (ADR-0010) ---
    schema_version: str = Field(default=PASS_PREDICTION_SCHEMA_VERSION)
    engine_version: str = Field(default=PASS_PREDICTION_ENGINE_VERSION)
    derived_at: AwareDatetime


# --- API pública ---------------------------------------------------------


def predict_passes(
    element: OrbitalElement,
    snapshot: TLESnapshot,
    *,
    observer_lat_deg: float,
    observer_lon_deg: float,
    observer_alt_m: float,
    window_start: datetime,
    window_end: datetime,
    step_minutes: float,
    min_elevation_deg: float = 0.0,
    aos_los_tolerance_seconds: float = AOS_LOS_TOLERANCE_SECONDS_DEFAULT,
    clock: Callable[[], datetime] | None = None,
) -> PassPrediction:
    """Predice pases de ``element`` sobre el observador en ``[window_start, window_end]``.

    Raises:
        ValueError: si los argumentos están fuera de rango (ADR-0023 enmienda 3),
            si la ventana es inválida, o si excede ``MAX_GRID_POINTS``.
        PropagationError: si SGP4 falla.
    """
    _validate_observer(observer_lat_deg, observer_lon_deg, observer_alt_m)
    _validate_window(window_start, window_end, step_minutes)
    if aos_los_tolerance_seconds <= 0:
        raise ValueError("aos_los_tolerance_seconds debe ser positivo.")

    window_start_utc = window_start.astimezone(timezone.utc)
    window_end_utc = window_end.astimezone(timezone.utc)

    obs_ecef = observer_to_ecef(observer_lat_deg, observer_lon_deg, observer_alt_m)
    times = _build_times(window_start_utc, window_end_utc, step_minutes)
    if not times:
        raise ValueError("La ventana no genera ningún instante (vacía).")
    if len(times) > MAX_GRID_POINTS:
        raise ValueError(
            f"La ventana solicitada produce {len(times)} puntos "
            f"(máximo {MAX_GRID_POINTS}). Reduce ventana o aumenta step_minutes."
        )

    propagator = Sgp4Propagator()
    elevations = _propagate_elevations(
        propagator, element, snapshot, times,
        observer_lat_deg, observer_lon_deg, obs_ecef,
    )

    segments = _find_pass_segments(elevations, min_elevation_deg)

    n_times = len(times)
    passes_list: list[Pass] = []
    for k_start, k_end in segments:
        # --- AOS ---
        if k_start == 0:
            aos_time = times[0]
            aos_was_refined = False
            partial_aos = True
        else:
            aos_time = _refine_aos_bisection(
                propagator, element, snapshot,
                observer_lat_deg, observer_lon_deg, obs_ecef,
                times[k_start - 1], times[k_start],
                min_elevation_deg, aos_los_tolerance_seconds,
            )
            aos_was_refined = True
            partial_aos = False

        # --- LOS ---
        if k_end == n_times - 1:
            los_time = times[-1]
            los_was_refined = False
            partial_los = True
        else:
            los_time = _refine_los_bisection(
                propagator, element, snapshot,
                observer_lat_deg, observer_lon_deg, obs_ecef,
                times[k_end], times[k_end + 1],
                min_elevation_deg, aos_los_tolerance_seconds,
            )
            los_was_refined = True
            partial_los = False

        # --- Culminación ---
        culmination_time, max_elev = _refine_culmination_parabolic(
            times, elevations, k_start, k_end, step_minutes,
        )

        # --- Azimuths en AOS, culminación, LOS ---
        aos_az = _azimuth_at(
            propagator, element, snapshot,
            observer_lat_deg, observer_lon_deg, obs_ecef, aos_time,
        )
        cul_az = _azimuth_at(
            propagator, element, snapshot,
            observer_lat_deg, observer_lon_deg, obs_ecef, culmination_time,
        )
        los_az = _azimuth_at(
            propagator, element, snapshot,
            observer_lat_deg, observer_lon_deg, obs_ecef, los_time,
        )

        duration_seconds = (los_time - aos_time).total_seconds()
        duration_seconds = max(duration_seconds, 0.0)  # defensa contra ruido numérico

        passes_list.append(
            Pass(
                aos_time=aos_time,
                culmination_time=culmination_time,
                los_time=los_time,
                aos_was_refined=aos_was_refined,
                los_was_refined=los_was_refined,
                partial_aos=partial_aos,
                partial_los=partial_los,
                duration_seconds=duration_seconds,
                max_elevation_deg=max_elev,
                aos_azimuth_deg=aos_az,
                culmination_azimuth_deg=cul_az,
                los_azimuth_deg=los_az,
            )
        )

    derived_at = (clock or _utc_now)()
    return PassPrediction(
        norad_cat_id=element.norad_cat_id,
        observer_lat_deg=observer_lat_deg,
        observer_lon_deg=observer_lon_deg,
        observer_alt_m=observer_alt_m,
        element_content_hash_source=element.content_hash_source,
        element_tle_index=element.tle_index,
        element_tle_content_hash=element.tle_content_hash,
        window_start=window_start_utc,
        window_end=window_end_utc,
        step_minutes=step_minutes,
        min_elevation_deg=min_elevation_deg,
        passes=passes_list,
        n_passes=len(passes_list),
        aos_los_resolution_seconds=aos_los_tolerance_seconds,
        derived_at=derived_at,
    )


# --- Validaciones --------------------------------------------------------


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


def _validate_window(
    window_start: datetime, window_end: datetime, step_minutes: float
) -> None:
    if window_start.tzinfo is None or window_end.tzinfo is None:
        raise ValueError(
            "window_start y window_end deben ser timezone-aware."
        )
    if step_minutes <= 0:
        raise ValueError("step_minutes debe ser positivo.")
    if window_end < window_start:
        raise ValueError("window_end debe ser >= window_start.")


# --- Grid temporal -------------------------------------------------------


def _build_times(
    start: datetime, end: datetime, step_minutes: float
) -> list[datetime]:
    """Grid uniforme inclusiva (mismo patrón que conjunctions.analysis)."""
    times: list[datetime] = []
    step = timedelta(minutes=step_minutes)
    t = start
    while t <= end:
        times.append(t)
        t += step
    return times


# --- Helpers internos (mencionados por el plan ADR-0023) -----------------


def _propagate_elevations(
    propagator: Sgp4Propagator,
    element: OrbitalElement,
    snapshot: TLESnapshot,
    times: list[datetime],
    observer_lat_deg: float,
    observer_lon_deg: float,
    obs_ecef: tuple[float, float, float],
) -> list[float]:
    """Batch propagation → lista de elevaciones topocéntricas en grados."""
    ephemerides = propagator.propagate(element, snapshot, times)
    elevations: list[float] = []
    for e in ephemerides:
        ecef = teme_to_ecef(
            e.position_teme_x_km,
            e.position_teme_y_km,
            e.position_teme_z_km,
            e.evaluation_time,
        )
        delta = (
            ecef[0] - obs_ecef[0],
            ecef[1] - obs_ecef[1],
            ecef[2] - obs_ecef[2],
        )
        east, north, up = ecef_to_enu(delta, observer_lat_deg, observer_lon_deg)
        elev_deg, _, _ = enu_to_elevation_azimuth(east, north, up)
        elevations.append(elev_deg)
    return elevations


def _find_pass_segments(
    elevations: list[float], min_elevation_deg: float
) -> list[tuple[int, int]]:
    """Identifica segmentos contiguos donde ``elev[i] >= min_elevation_deg``.

    Devuelve lista de ``(k_start, k_end)`` inclusiva.
    """
    segments: list[tuple[int, int]] = []
    seg_start = -1
    for i, elev in enumerate(elevations):
        above = elev >= min_elevation_deg
        if above and seg_start == -1:
            seg_start = i
        elif not above and seg_start != -1:
            segments.append((seg_start, i - 1))
            seg_start = -1
    if seg_start != -1:
        segments.append((seg_start, len(elevations) - 1))
    return segments


def _elevation_at(
    propagator: Sgp4Propagator,
    element: OrbitalElement,
    snapshot: TLESnapshot,
    observer_lat_deg: float,
    observer_lon_deg: float,
    obs_ecef: tuple[float, float, float],
    t: datetime,
) -> float:
    """Una sola evaluación SGP4 + transformación topo → elevation_deg."""
    [eph] = propagator.propagate(element, snapshot, [t])
    ecef = teme_to_ecef(
        eph.position_teme_x_km,
        eph.position_teme_y_km,
        eph.position_teme_z_km,
        eph.evaluation_time,
    )
    delta = (
        ecef[0] - obs_ecef[0],
        ecef[1] - obs_ecef[1],
        ecef[2] - obs_ecef[2],
    )
    east, north, up = ecef_to_enu(delta, observer_lat_deg, observer_lon_deg)
    elev_deg, _, _ = enu_to_elevation_azimuth(east, north, up)
    return elev_deg


def _refine_aos_bisection(
    propagator: Sgp4Propagator,
    element: OrbitalElement,
    snapshot: TLESnapshot,
    observer_lat_deg: float,
    observer_lon_deg: float,
    obs_ecef: tuple[float, float, float],
    t_left: datetime,
    t_right: datetime,
    min_elevation_deg: float,
    tolerance_seconds: float,
) -> datetime:
    """Bisección AOS: ``f(t_left) < 0, f(t_right) >= 0`` (cruce ascendente)."""
    tolerance = timedelta(seconds=tolerance_seconds)
    while (t_right - t_left) > tolerance:
        t_mid = t_left + (t_right - t_left) / 2
        elev_mid = _elevation_at(
            propagator, element, snapshot,
            observer_lat_deg, observer_lon_deg, obs_ecef, t_mid,
        )
        if elev_mid - min_elevation_deg >= 0.0:
            t_right = t_mid
        else:
            t_left = t_mid
    return t_left + (t_right - t_left) / 2


def _refine_los_bisection(
    propagator: Sgp4Propagator,
    element: OrbitalElement,
    snapshot: TLESnapshot,
    observer_lat_deg: float,
    observer_lon_deg: float,
    obs_ecef: tuple[float, float, float],
    t_left: datetime,
    t_right: datetime,
    min_elevation_deg: float,
    tolerance_seconds: float,
) -> datetime:
    """Bisección LOS: ``f(t_left) >= 0, f(t_right) < 0`` (cruce descendente)."""
    tolerance = timedelta(seconds=tolerance_seconds)
    while (t_right - t_left) > tolerance:
        t_mid = t_left + (t_right - t_left) / 2
        elev_mid = _elevation_at(
            propagator, element, snapshot,
            observer_lat_deg, observer_lon_deg, obs_ecef, t_mid,
        )
        if elev_mid - min_elevation_deg >= 0.0:
            t_left = t_mid
        else:
            t_right = t_mid
    return t_left + (t_right - t_left) / 2


def _refine_culmination_parabolic(
    times: list[datetime],
    elevations: list[float],
    k_start: int,
    k_end: int,
    step_minutes: float,
) -> tuple[datetime, float]:
    """Ajuste parabólico local de 3 muestras sobre el máximo discreto.

    Si ``k_max`` está en el borde de la grid completa, fallback a TCA discreto.
    Si el denominador del fit es ~0 (curvatura plana), fallback a discreto.
    """
    k_max = k_start
    e_at_max = elevations[k_start]
    for k in range(k_start + 1, k_end + 1):
        if elevations[k] > e_at_max:
            e_at_max = elevations[k]
            k_max = k

    if k_max == 0 or k_max == len(elevations) - 1:
        return times[k_max], elevations[k_max]

    e_left = elevations[k_max - 1]
    e_mid = elevations[k_max]
    e_right = elevations[k_max + 1]
    denom = e_left - 2.0 * e_mid + e_right
    if math.fabs(denom) < 1e-12:
        return times[k_max], e_mid

    delta = 0.5 * (e_left - e_right) / denom
    culmination_time = times[k_max] + timedelta(minutes=step_minutes * delta)
    max_elev = e_mid - 0.125 * (e_left - e_right) * (e_left - e_right) / denom
    return culmination_time, max_elev


def _azimuth_at(
    propagator: Sgp4Propagator,
    element: OrbitalElement,
    snapshot: TLESnapshot,
    observer_lat_deg: float,
    observer_lon_deg: float,
    obs_ecef: tuple[float, float, float],
    t: datetime,
) -> float:
    """Una sola evaluación SGP4 + topo → azimuth_deg."""
    [eph] = propagator.propagate(element, snapshot, [t])
    ecef = teme_to_ecef(
        eph.position_teme_x_km,
        eph.position_teme_y_km,
        eph.position_teme_z_km,
        eph.evaluation_time,
    )
    delta = (
        ecef[0] - obs_ecef[0],
        ecef[1] - obs_ecef[1],
        ecef[2] - obs_ecef[2],
    )
    east, north, up = ecef_to_enu(delta, observer_lat_deg, observer_lon_deg)
    _, az_deg, _ = enu_to_elevation_azimuth(east, north, up)
    return az_deg
