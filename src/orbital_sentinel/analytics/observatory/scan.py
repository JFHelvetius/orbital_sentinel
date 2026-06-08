"""Observatory scan v0.1 (ADR-0025).

Agregación multi-satélite sobre un observador único en una ventana temporal,
con filtro ``useful_pass`` declarado y pre-filtro geométrico O(1) por satélite
(análogo al apogee/perigee de ADR-0018).

Composición pura sobre :func:`predict_passes` (ADR-0023) y
:func:`solar_context_at` / :func:`is_satellite_illuminated` (ADR-0024).
Cero matemática nueva; cero persistencia; cero dependencias nuevas.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from datetime import datetime, timezone

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from orbital_sentinel.analytics.passes import (
    FRAME_MODEL_NAME,
    Pass,
    predict_passes,
)
from orbital_sentinel.analytics.passes.geometry import (
    EARTH_RADIUS_KM,
)
from orbital_sentinel.analytics.solar import (
    SHADOW_MODEL_NAME,
    SOLAR_POSITION_MODEL_NAME,
    TwilightPhase,
    is_satellite_illuminated,
    solar_context_at,
    twilight_darkness_rank,
)
from orbital_sentinel.catalog.orbital_elements import OrbitalElement
from orbital_sentinel.catalog.tle_snapshots import TLESnapshot
from orbital_sentinel.propagation import GMST_MODEL_NAME, Sgp4Propagator

OBSERVATORY_SCAN_SCHEMA_VERSION = "0.1.0"
OBSERVATORY_SCAN_ENGINE_VERSION = "0.1.0"
USEFUL_PASS_FILTER_VERSION = "0.1.0"
MAX_SATELLITES_DEFAULT = 5000
EARTH_GRAVITATIONAL_PARAMETER_KM3_S2 = 398_600.4418

# Margen sobre el límite teórico de visibilidad para el pre-filtro defensivo.
_GEOMETRIC_VISIBILITY_MARGIN_DEG = 5.0


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


# --- Modelos -------------------------------------------------------------


class UsefulPassFilter(BaseModel):
    """Filtro declarado que clasifica pases como "útiles" (ADR-0025)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    require_observer_in_twilight_or_darker: bool = Field(default=True)
    minimum_twilight_phase: TwilightPhase = Field(default=TwilightPhase.CIVIL)
    require_satellite_illuminated: bool = Field(default=True)
    shadow_model: str = Field(default=SHADOW_MODEL_NAME)
    useful_pass_filter_version: str = Field(default=USEFUL_PASS_FILTER_VERSION)


class SatellitePasses(BaseModel):
    """Pases de un satélite con provenance + counts."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    norad_cat_id: int
    object_name: str | None
    element_content_hash_source: str
    element_tle_index: int
    element_tle_content_hash: str
    passes: list[Pass]
    n_passes: int = Field(ge=0)
    n_useful_passes: int = Field(ge=0)


class ObservatoryScan(BaseModel):
    """Resultado de :func:`scan_observatory` (ADR-0025)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    # --- Identity ---
    observer_lat_deg: float
    observer_lon_deg: float
    observer_alt_m: float
    window_start: AwareDatetime
    window_end: AwareDatetime
    step_minutes: float = Field(gt=0.0)
    min_elevation_deg: float

    # --- Counts auditables ---
    n_satellites_input: int = Field(ge=0)
    n_satellites_skipped_geometric: int = Field(ge=0)
    n_satellites_scanned: int = Field(ge=0)
    n_passes_total: int = Field(ge=0)
    n_useful_passes_total: int = Field(ge=0)

    # --- Per-sat ---
    satellites: list[SatellitePasses]

    # --- Honesty fields (ADR-0020 pattern) ---
    useful_pass_filter: UsefulPassFilter
    frame_model: str = Field(default=FRAME_MODEL_NAME)
    gmst_model: str = Field(default=GMST_MODEL_NAME)
    solar_position_model: str = Field(default=SOLAR_POSITION_MODEL_NAME)
    shadow_model: str = Field(default=SHADOW_MODEL_NAME)

    # --- Versioning (ADR-0010) ---
    schema_version: str = Field(default=OBSERVATORY_SCAN_SCHEMA_VERSION)
    engine_version: str = Field(default=OBSERVATORY_SCAN_ENGINE_VERSION)
    derived_at: AwareDatetime


# --- Pre-filtro geométrico O(1) ----------------------------------------


def _semi_major_axis_km(mean_motion_rev_day: float) -> float:
    """Semieje mayor desde mean motion (Kepler 3rd law)."""
    n_rad_s = mean_motion_rev_day * 2.0 * math.pi / 86400.0
    a_km: float = (EARTH_GRAVITATIONAL_PARAMETER_KM3_S2 / (n_rad_s * n_rad_s)) ** (1.0 / 3.0)
    return a_km


def is_geometrically_unreachable(
    element: OrbitalElement, observer_lat_deg: float
) -> bool:
    """Pre-filtro O(1): True si el satélite no puede alcanzar el observador
    bajo ninguna combinación de RAAN / argumento del perigeo.

    El subsatellite point alcanza latitudes |φ| ≤ inclination_deg (prógrado)
    o ≤ 180° - inclination_deg (retrógrado). Sumamos el half-cone topocéntrico
    arccos(R⊕/(R⊕+h_perigee)) + margen defensivo.
    """
    # Inclinación efectiva máxima de latitud sub-satélite
    inc = element.inclination_deg
    max_lat_sub = inc if inc <= 90.0 else 180.0 - inc

    # Altitud mínima del satélite (perigee): usar perigee para ser conservador
    a_km = _semi_major_axis_km(element.mean_motion)
    perigee_km = a_km * (1.0 - element.eccentricity)
    h_perigee_km = perigee_km - EARTH_RADIUS_KM
    if h_perigee_km <= 0.0:
        return True  # órbita decaída

    cos_half_cone = EARTH_RADIUS_KM / (EARTH_RADIUS_KM + h_perigee_km)
    cos_half_cone = max(-1.0, min(1.0, cos_half_cone))
    half_cone_deg = math.degrees(math.acos(cos_half_cone))

    threshold_deg = max_lat_sub + half_cone_deg + _GEOMETRIC_VISIBILITY_MARGIN_DEG
    return abs(observer_lat_deg) > threshold_deg


# --- Composición principal ---------------------------------------------


def _propagate_sat_eci(
    propagator: Sgp4Propagator,
    element: OrbitalElement,
    snapshot: TLESnapshot,
    when: datetime,
) -> tuple[float, float, float]:
    """Posición del satélite en ECI ~J2000 [km] en ``when``.

    A la precisión declarada por el modelo solar (~0.01°), TEME ≈ ECI.
    """
    [eph] = propagator.propagate(element, snapshot, [when])
    return (eph.position_teme_x_km, eph.position_teme_y_km, eph.position_teme_z_km)


def _pass_is_useful(
    pass_: Pass,
    element: OrbitalElement,
    snapshot: TLESnapshot,
    observer_lat_deg: float,
    observer_lon_deg: float,
    observer_alt_m: float,
    filter_: UsefulPassFilter,
    propagator: Sgp4Propagator,
) -> bool:
    """Evalúa los criterios de ``filter_`` en el instante de culminación."""
    when = pass_.culmination_time

    if filter_.require_observer_in_twilight_or_darker:
        ctx = solar_context_at(
            observer_lat_deg, observer_lon_deg, observer_alt_m, when
        )
        actual = twilight_darkness_rank(ctx.twilight_phase)
        required = twilight_darkness_rank(filter_.minimum_twilight_phase)
        if actual < required:
            return False

    if filter_.require_satellite_illuminated:
        sat_eci = _propagate_sat_eci(propagator, element, snapshot, when)
        if not is_satellite_illuminated(sat_eci, when):
            return False

    return True


def scan_observatory(
    elements_and_snapshots: Sequence[tuple[OrbitalElement, TLESnapshot]],
    *,
    observer_lat_deg: float,
    observer_lon_deg: float,
    observer_alt_m: float,
    window_start: datetime,
    window_end: datetime,
    step_minutes: float,
    min_elevation_deg: float = 10.0,
    useful_pass_filter: UsefulPassFilter | None = None,
    max_satellites: int = MAX_SATELLITES_DEFAULT,
    clock: Callable[[], datetime] | None = None,
) -> ObservatoryScan:
    """Escanea N satélites desde un observador. Devuelve agregación con counts
    auditables, filtro útil declarado y provenance por satélite.

    Raises:
        ValueError: si ``len(elements_and_snapshots) > max_satellites`` o
            inputs inválidos.
    """
    n_input = len(elements_and_snapshots)
    if n_input > max_satellites:
        raise ValueError(
            f"n_satellites={n_input} excede max_satellites={max_satellites}"
        )

    filter_ = useful_pass_filter if useful_pass_filter is not None else UsefulPassFilter()

    propagator = Sgp4Propagator()
    satellites: list[SatellitePasses] = []
    n_skipped = 0
    n_scanned = 0
    n_passes_total = 0
    n_useful_total = 0

    # Orden estable por NORAD ascendente para determinismo del output.
    sorted_pairs = sorted(
        elements_and_snapshots, key=lambda p: p[0].norad_cat_id
    )

    for element, snapshot in sorted_pairs:
        if is_geometrically_unreachable(element, observer_lat_deg):
            n_skipped += 1
            continue
        n_scanned += 1

        prediction = predict_passes(
            element, snapshot,
            observer_lat_deg=observer_lat_deg,
            observer_lon_deg=observer_lon_deg,
            observer_alt_m=observer_alt_m,
            window_start=window_start,
            window_end=window_end,
            step_minutes=step_minutes,
            min_elevation_deg=min_elevation_deg,
            clock=clock,
        )

        n_useful = 0
        for p in prediction.passes:
            if _pass_is_useful(
                p, element, snapshot,
                observer_lat_deg, observer_lon_deg, observer_alt_m,
                filter_, propagator,
            ):
                n_useful += 1

        satellites.append(
            SatellitePasses(
                norad_cat_id=element.norad_cat_id,
                object_name=element.object_name,
                element_content_hash_source=element.content_hash_source,
                element_tle_index=element.tle_index,
                element_tle_content_hash=element.tle_content_hash,
                passes=list(prediction.passes),
                n_passes=prediction.n_passes,
                n_useful_passes=n_useful,
            )
        )
        n_passes_total += prediction.n_passes
        n_useful_total += n_useful

    derived_at = (clock or _utc_now)()
    return ObservatoryScan(
        observer_lat_deg=observer_lat_deg,
        observer_lon_deg=observer_lon_deg,
        observer_alt_m=observer_alt_m,
        window_start=window_start.astimezone(timezone.utc),
        window_end=window_end.astimezone(timezone.utc),
        step_minutes=step_minutes,
        min_elevation_deg=min_elevation_deg,
        n_satellites_input=n_input,
        n_satellites_skipped_geometric=n_skipped,
        n_satellites_scanned=n_scanned,
        n_passes_total=n_passes_total,
        n_useful_passes_total=n_useful_total,
        satellites=satellites,
        useful_pass_filter=filter_,
        derived_at=derived_at,
    )
