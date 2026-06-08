"""Anomaly detection v0.1 (ADR-0028)."""

from orbital_sentinel.analytics.anomalies.analysis import (
    BASELINE_WINDOW_DAYS_DEFAULT,
    MIN_BASELINE_SAMPLES_DEFAULT,
    SIGMA_FLOOR_DEFAULT,
    THRESHOLD_SIGMA_DEFAULT,
    detect_anomalies,
)
from orbital_sentinel.analytics.anomalies.features import (
    AVAILABLE_FEATURES,
    EARTH_GRAVITATIONAL_PARAMETER_KM3_S2,
    EARTH_RADIUS_KM,
    UnknownFeatureError,
    compute_feature,
    compute_features,
)
from orbital_sentinel.analytics.anomalies.models import (
    ANOMALY_DETECTION_ENGINE_VERSION,
    ANOMALY_DETECTION_SCHEMA_VERSION,
    DETECTION_METHOD_NAME,
    AnomalyDetectionConfig,
    AnomalyDetectionResult,
    AnomalyEvent,
)

__all__ = [
    "ANOMALY_DETECTION_ENGINE_VERSION",
    "ANOMALY_DETECTION_SCHEMA_VERSION",
    "AVAILABLE_FEATURES",
    "BASELINE_WINDOW_DAYS_DEFAULT",
    "DETECTION_METHOD_NAME",
    "EARTH_GRAVITATIONAL_PARAMETER_KM3_S2",
    "EARTH_RADIUS_KM",
    "MIN_BASELINE_SAMPLES_DEFAULT",
    "SIGMA_FLOOR_DEFAULT",
    "THRESHOLD_SIGMA_DEFAULT",
    "AnomalyDetectionConfig",
    "AnomalyDetectionResult",
    "AnomalyEvent",
    "UnknownFeatureError",
    "compute_feature",
    "compute_features",
    "detect_anomalies",
]
