"""Maneuver detection (ADR-0027)."""

from orbital_sentinel.analytics.maneuvers.detector import (
    BASELINE_WINDOW_DAYS_DEFAULT,
    DETECTION_METHOD_NAME,
    DETECTION_THRESHOLD_SIGMA_DEFAULT,
    MANEUVER_DETECTION_ENGINE_VERSION,
    MANEUVER_DETECTION_SCHEMA_VERSION,
    MIN_BASELINE_SAMPLES_DEFAULT,
    SIGMA_FLOOR_DEFAULT,
    ManeuverDetectionResult,
    ManeuverEvent,
    detect_maneuvers,
)
from orbital_sentinel.analytics.maneuvers.series import OrbitalElementSeries

__all__ = [
    "BASELINE_WINDOW_DAYS_DEFAULT",
    "DETECTION_METHOD_NAME",
    "DETECTION_THRESHOLD_SIGMA_DEFAULT",
    "MANEUVER_DETECTION_ENGINE_VERSION",
    "MANEUVER_DETECTION_SCHEMA_VERSION",
    "MIN_BASELINE_SAMPLES_DEFAULT",
    "SIGMA_FLOOR_DEFAULT",
    "ManeuverDetectionResult",
    "ManeuverEvent",
    "OrbitalElementSeries",
    "detect_maneuvers",
]
