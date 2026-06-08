"""Detector de anomalías v0.1 (ADR-0028).

Comparación de feature value vs baseline de valores recientes del MISMO
objeto. Z-score, threshold, σ_floor. Sin ML, sin RNG, sin wall clock, sin
clasificación.

Reusa exactamente el patrón estadístico de ADR-0027 (maneuver detection):

    signal → baseline → deviation score → apparent observation
                                          → operator interpretation
"""

from __future__ import annotations

import statistics
from collections.abc import Callable, Sequence
from datetime import datetime, timezone

from orbital_sentinel.analytics.anomalies.features import (
    AVAILABLE_FEATURES,
    UnknownFeatureError,
    compute_feature,
)
from orbital_sentinel.analytics.anomalies.models import (
    ANOMALY_DETECTION_ENGINE_VERSION,
    ANOMALY_DETECTION_SCHEMA_VERSION,
    DETECTION_METHOD_NAME,
    AnomalyDetectionConfig,
    AnomalyDetectionResult,
    AnomalyEvent,
)
from orbital_sentinel.analytics.maneuvers.series import OrbitalElementSeries

# --- Defaults (ADR-0028) -------------------------------------------------

BASELINE_WINDOW_DAYS_DEFAULT = 14.0
THRESHOLD_SIGMA_DEFAULT = 3.0
MIN_BASELINE_SAMPLES_DEFAULT = 5
SIGMA_FLOOR_DEFAULT = 1e-12


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _resolve_object_id(object_name: str | None, norad_cat_id: int) -> str:
    if object_name is not None and object_name.strip():
        return object_name
    return f"NORAD-{norad_cat_id}"


def detect_anomalies(
    series: OrbitalElementSeries,
    *,
    features: Sequence[str] = AVAILABLE_FEATURES,
    baseline_window_days: float = BASELINE_WINDOW_DAYS_DEFAULT,
    threshold_sigma: float = THRESHOLD_SIGMA_DEFAULT,
    min_baseline_samples: int = MIN_BASELINE_SAMPLES_DEFAULT,
    sigma_floor: float = SIGMA_FLOOR_DEFAULT,
    clock: Callable[[], datetime] | None = None,
) -> AnomalyDetectionResult:
    """Detecta desviaciones aparentes de cada feature respecto a baseline.

    Args:
        series: ``OrbitalElementSeries`` (ADR-0027) ya validada.
        features: subconjunto de ``AVAILABLE_FEATURES``. Default: todas.
        baseline_window_days: ventana temporal hacia atrás de la baseline.
        threshold_sigma: umbral de detección en σ.
        min_baseline_samples: mínimo de muestras (≥2) para evaluar.
        sigma_floor: cota inferior de σ (evita inf en baseline uniforme).
        clock: inyectable para tests deterministas.

    Returns:
        ``AnomalyDetectionResult`` con counts, eventos y configuración
        declarada.

    Raises:
        ValueError: parámetros fuera de rango o features vacías/desconocidas.
    """
    if baseline_window_days <= 0:
        raise ValueError("baseline_window_days debe ser > 0")
    if threshold_sigma <= 0:
        raise ValueError("threshold_sigma debe ser > 0")
    if min_baseline_samples < 2:
        raise ValueError("min_baseline_samples debe ser ≥ 2 (stdev requiere ≥ 2)")
    if sigma_floor <= 0:
        raise ValueError("sigma_floor debe ser > 0")
    if not features:
        raise ValueError("features no puede estar vacío")
    for f in features:
        if f not in AVAILABLE_FEATURES:
            raise UnknownFeatureError(
                f"Feature desconocida: {f!r}. Disponibles: {AVAILABLE_FEATURES}"
            )

    feature_list = tuple(features)

    # Precompute matrix de feature values (deterministic, single pass).
    feature_values: dict[str, list[float]] = {f: [] for f in feature_list}
    for el in series.elements:
        for f in feature_list:
            feature_values[f].append(compute_feature(el, f))

    events: list[AnomalyEvent] = []
    n_evaluated = 0
    n_skipped = 0

    n_elements = len(series.elements)
    for k in range(n_elements):
        el = series.elements[k]
        # Baseline: índices j < k cuyo epoch_j esté en (epoch_k − W, epoch_k]
        baseline_idx: list[int] = []
        epoch_k = el.epoch_datetime
        for j in range(k):
            delta_days = (
                epoch_k - series.elements[j].epoch_datetime
            ).total_seconds() / 86400.0
            if delta_days <= baseline_window_days:
                baseline_idx.append(j)

        if len(baseline_idx) < min_baseline_samples:
            n_skipped += len(feature_list)
            continue

        for f in feature_list:
            n_evaluated += 1
            baseline = [feature_values[f][j] for j in baseline_idx]
            mu = statistics.mean(baseline)
            sigma = statistics.stdev(baseline)
            sigma_safe = sigma if sigma > sigma_floor else sigma_floor
            observed = feature_values[f][k]
            z = (observed - mu) / sigma_safe

            if abs(z) > threshold_sigma:
                events.append(
                    AnomalyEvent(
                        object_id=_resolve_object_id(el.object_name, el.norad_cat_id),
                        norad_cat_id=el.norad_cat_id,
                        epoch_datetime=epoch_k,
                        feature_name=f,
                        observed_value=observed,
                        baseline_mean=mu,
                        baseline_stddev=sigma,
                        anomaly_score=z,
                        baseline_window_days=baseline_window_days,
                        threshold_sigma=threshold_sigma,
                        n_baseline_samples=len(baseline_idx),
                    )
                )

    # Ordenamiento determinístico: (epoch ascendente, feature_name alfabético).
    events.sort(key=lambda ev: (ev.epoch_datetime, ev.feature_name))

    derived_at = (clock or _utc_now)()
    head = series.elements[0]
    config = AnomalyDetectionConfig(
        features_used=list(feature_list),
        baseline_window_days=baseline_window_days,
        threshold_sigma=threshold_sigma,
        min_baseline_samples=min_baseline_samples,
        sigma_floor=sigma_floor,
        detection_method_name=DETECTION_METHOD_NAME,
    )
    return AnomalyDetectionResult(
        norad_cat_id=series.norad_cat_id,
        object_id=_resolve_object_id(head.object_name, series.norad_cat_id),
        series_start_epoch=series.series_start_epoch,
        series_end_epoch=series.series_end_epoch,
        total_objects_analyzed=1,
        total_anomalies_found=len(events),
        total_evaluations=n_evaluated,
        total_evaluations_skipped_insufficient_baseline=n_skipped,
        configuration_used=config,
        events=events,
        derived_at=derived_at,
        schema_version=ANOMALY_DETECTION_SCHEMA_VERSION,
        analysis_engine_version=ANOMALY_DETECTION_ENGINE_VERSION,
    )
