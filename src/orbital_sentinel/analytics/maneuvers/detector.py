"""Detección de maniobras v0.1 (ADR-0027).

Algoritmo: z-score sobre rates de cambio (Δ/Δt) en tres componentes
medias (mean_motion, eccentricity, inclination) contra una baseline
deslizante por ventana temporal.

Patrón ADR-0020 extendido al dominio estadístico: cada
``ManeuverEvent`` lleva sus honesty fields (método, ventana, threshold,
``is_apparent_not_confirmed=True``) declarados explícitamente.
"""

from __future__ import annotations

import statistics
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from orbital_sentinel.analytics.maneuvers.series import OrbitalElementSeries

MANEUVER_DETECTION_SCHEMA_VERSION = "0.1.0"
"""SemVer del esquema (ADR-0010)."""

MANEUVER_DETECTION_ENGINE_VERSION = "0.1.0"
"""SemVer del algoritmo (ADR-0010 engine_version)."""

DETECTION_METHOD_NAME = "element_jump_z_score_v1"
"""Identificador del método (ADR-0027)."""

BASELINE_WINDOW_DAYS_DEFAULT = 14.0
DETECTION_THRESHOLD_SIGMA_DEFAULT = 3.0
MIN_BASELINE_SAMPLES_DEFAULT = 5
SIGMA_FLOOR_DEFAULT = 1e-12

Component = Literal["mean_motion", "eccentricity", "inclination"]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


# --- Modelos -------------------------------------------------------------


class ManeuverEvent(BaseModel):
    """Salto aparente detectado en una transición entre dos OrbitalElements
    consecutivos (ADR-0027).

    Provenance: doble FK Raw→Normalized vía ``content_hash_source_before/after``
    y ``tle_content_hash_before/after``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    # --- Provenance binaria FK ---
    norad_cat_id: int
    epoch_before: AwareDatetime
    epoch_after: AwareDatetime
    tle_content_hash_before: str
    tle_content_hash_after: str
    content_hash_source_before: str
    content_hash_source_after: str

    # --- Magnitudes físicas (deltas absolutas) ---
    delta_t_days: float = Field(gt=0.0)
    delta_mean_motion_rev_day: float
    delta_eccentricity: float
    delta_inclination_deg: float

    # --- Z-scores (signados) ---
    z_score_mean_motion: float
    z_score_eccentricity: float
    z_score_inclination: float
    dominant_component: Component

    # --- Honesty (ADR-0020 pattern extendido al dominio estadístico) ---
    detection_method_name: str = Field(default=DETECTION_METHOD_NAME)
    baseline_window_days: float = Field(gt=0.0)
    detection_threshold_sigma: float = Field(gt=0.0)
    n_baseline_samples: int = Field(ge=1)
    is_apparent_not_confirmed: bool = Field(default=True)


class ManeuverDetectionResult(BaseModel):
    """Resultado completo de :func:`detect_maneuvers` (ADR-0027)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    # --- Identidad ---
    norad_cat_id: int
    series_start_epoch: AwareDatetime
    series_end_epoch: AwareDatetime

    # --- Counts auditables ---
    n_elements_in_series: int = Field(ge=2)
    n_transitions_total: int = Field(ge=1)
    n_transitions_skipped_insufficient_baseline: int = Field(ge=0)
    n_transitions_evaluated: int = Field(ge=0)
    n_events: int = Field(ge=0)

    # --- Resultado ---
    events: list[ManeuverEvent]

    # --- Configuración declarada (honesty) ---
    baseline_window_days: float = Field(gt=0.0)
    detection_threshold_sigma: float = Field(gt=0.0)
    min_baseline_samples: int = Field(ge=1)
    sigma_floor: float = Field(gt=0.0)
    detection_method_name: str = Field(default=DETECTION_METHOD_NAME)
    is_apparent_not_confirmed: bool = Field(default=True)

    # --- Versioning (ADR-0010) ---
    schema_version: str = Field(default=MANEUVER_DETECTION_SCHEMA_VERSION)
    engine_version: str = Field(default=MANEUVER_DETECTION_ENGINE_VERSION)
    derived_at: AwareDatetime


# --- Helpers internos --------------------------------------------------


def _transition_rates(
    series: OrbitalElementSeries,
) -> list[tuple[float, float, float, float]]:
    """Para cada transición i → i+1, devuelve ``(Δt_days, rate_n, rate_e, rate_ι)``."""
    rates: list[tuple[float, float, float, float]] = []
    els = series.elements
    for i in range(len(els) - 1):
        prev = els[i]
        curr = els[i + 1]
        dt_seconds = (curr.epoch_datetime - prev.epoch_datetime).total_seconds()
        dt_days = dt_seconds / 86400.0
        # OrbitalElementSeries valida epoch estrictamente creciente ⇒ dt > 0
        d_n = (curr.mean_motion - prev.mean_motion) / dt_days
        d_e = (curr.eccentricity - prev.eccentricity) / dt_days
        d_i = (curr.inclination_deg - prev.inclination_deg) / dt_days
        rates.append((dt_days, d_n, d_e, d_i))
    return rates


def _baseline_indices(
    series: OrbitalElementSeries,
    k: int,
    baseline_window_days: float,
) -> list[int]:
    """Índices j < k de transiciones cuyo epoch_j (epoch del lado izquierdo)
    está dentro de la ventana baseline a partir de epoch_k.

    Definimos epoch_j = epoch_datetime de elements[j] (lado izquierdo de la
    transición j → j+1). Es la convención más simple y la más rica en
    información reciente.
    """
    epoch_k = series.elements[k].epoch_datetime
    window = timedelta(days=baseline_window_days)
    return [
        j
        for j in range(k)
        if (epoch_k - series.elements[j].epoch_datetime) <= window
    ]


def _z_score(value: float, baseline: list[float], sigma_floor: float) -> float:
    """Z-score con cota inferior en σ para evitar inf en baseline uniforme."""
    if len(baseline) < 2:
        # statistics.stdev requiere ≥ 2; este caso solo ocurre en
        # invocaciones donde el caller no respetó min_baseline_samples ≥ 2.
        # Defensivo: devolver 0.0 (sin discriminación posible).
        return 0.0
    mu = statistics.mean(baseline)
    sigma = statistics.stdev(baseline)
    sigma_safe = sigma if sigma > sigma_floor else sigma_floor
    return (value - mu) / sigma_safe


# --- API pública -------------------------------------------------------


def detect_maneuvers(
    series: OrbitalElementSeries,
    *,
    baseline_window_days: float = BASELINE_WINDOW_DAYS_DEFAULT,
    detection_threshold_sigma: float = DETECTION_THRESHOLD_SIGMA_DEFAULT,
    min_baseline_samples: int = MIN_BASELINE_SAMPLES_DEFAULT,
    sigma_floor: float = SIGMA_FLOOR_DEFAULT,
    clock: Callable[[], datetime] | None = None,
) -> ManeuverDetectionResult:
    """Detecta saltos aparentes en elementos medios via z-score (ADR-0027).

    Args:
        series: ``OrbitalElementSeries`` ya validada.
        baseline_window_days: ventana temporal hacia atrás para la baseline.
        detection_threshold_sigma: umbral de detección en σ.
        min_baseline_samples: número mínimo de muestras en baseline para
            evaluar una transición. Transiciones con menos se cuentan en
            ``n_transitions_skipped_insufficient_baseline``.
        sigma_floor: cota inferior para σ del baseline (evita inf en
            baseline perfectamente uniforme).
        clock: inyectable para tests deterministas.

    Returns:
        ``ManeuverDetectionResult`` con counts auditables, lista de
        eventos y honesty fields declarados.

    Raises:
        ValueError: si los parámetros están fuera de rango.
    """
    if baseline_window_days <= 0:
        raise ValueError("baseline_window_days debe ser > 0")
    if detection_threshold_sigma <= 0:
        raise ValueError("detection_threshold_sigma debe ser > 0")
    if min_baseline_samples < 2:
        raise ValueError("min_baseline_samples debe ser ≥ 2 (stdev requiere ≥ 2)")
    if sigma_floor <= 0:
        raise ValueError("sigma_floor debe ser > 0")

    rates = _transition_rates(series)
    n_transitions = len(rates)

    events: list[ManeuverEvent] = []
    n_skipped = 0
    n_evaluated = 0

    for k in range(n_transitions):
        baseline_idx = _baseline_indices(series, k, baseline_window_days)
        if len(baseline_idx) < min_baseline_samples:
            n_skipped += 1
            continue
        n_evaluated += 1

        baseline_n = [rates[j][1] for j in baseline_idx]
        baseline_e = [rates[j][2] for j in baseline_idx]
        baseline_i = [rates[j][3] for j in baseline_idx]

        dt_k, rate_n_k, rate_e_k, rate_i_k = rates[k]

        z_n = _z_score(rate_n_k, baseline_n, sigma_floor)
        z_e = _z_score(rate_e_k, baseline_e, sigma_floor)
        z_i = _z_score(rate_i_k, baseline_i, sigma_floor)

        abs_z = (abs(z_n), abs(z_e), abs(z_i))
        z_max = max(abs_z)
        if z_max <= detection_threshold_sigma:
            continue

        if abs_z[0] >= abs_z[1] and abs_z[0] >= abs_z[2]:
            dominant: Component = "mean_motion"
        elif abs_z[1] >= abs_z[2]:
            dominant = "eccentricity"
        else:
            dominant = "inclination"

        prev_el = series.elements[k]
        next_el = series.elements[k + 1]
        events.append(
            ManeuverEvent(
                norad_cat_id=series.norad_cat_id,
                epoch_before=prev_el.epoch_datetime,
                epoch_after=next_el.epoch_datetime,
                tle_content_hash_before=prev_el.tle_content_hash,
                tle_content_hash_after=next_el.tle_content_hash,
                content_hash_source_before=prev_el.content_hash_source,
                content_hash_source_after=next_el.content_hash_source,
                delta_t_days=dt_k,
                delta_mean_motion_rev_day=next_el.mean_motion - prev_el.mean_motion,
                delta_eccentricity=next_el.eccentricity - prev_el.eccentricity,
                delta_inclination_deg=next_el.inclination_deg - prev_el.inclination_deg,
                z_score_mean_motion=z_n,
                z_score_eccentricity=z_e,
                z_score_inclination=z_i,
                dominant_component=dominant,
                baseline_window_days=baseline_window_days,
                detection_threshold_sigma=detection_threshold_sigma,
                n_baseline_samples=len(baseline_idx),
            )
        )

    derived_at = (clock or _utc_now)()
    return ManeuverDetectionResult(
        norad_cat_id=series.norad_cat_id,
        series_start_epoch=series.series_start_epoch,
        series_end_epoch=series.series_end_epoch,
        n_elements_in_series=series.n_elements,
        n_transitions_total=n_transitions,
        n_transitions_skipped_insufficient_baseline=n_skipped,
        n_transitions_evaluated=n_evaluated,
        n_events=len(events),
        events=events,
        baseline_window_days=baseline_window_days,
        detection_threshold_sigma=detection_threshold_sigma,
        min_baseline_samples=min_baseline_samples,
        sigma_floor=sigma_floor,
        derived_at=derived_at,
    )
