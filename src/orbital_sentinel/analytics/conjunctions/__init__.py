"""Conjunction analysis (ADR-0016)."""

from orbital_sentinel.analytics.conjunctions.analysis import (
    CONJUNCTION_ENGINE_VERSION,
    CONJUNCTION_SCHEMA_VERSION,
    SGP4_UNCERTAINTY_BASELINE_KM,
    SGP4_UNCERTAINTY_GROWTH_KM_PER_DAY,
    TCA_REFINEMENT_TOLERANCE_SECONDS,
    ConjunctionAnalysis,
    analyze_pairwise_conjunction,
)
from orbital_sentinel.analytics.conjunctions.probability import (
    COVARIANCE_BASELINE_SIGMA_KM,
    COVARIANCE_GROWTH_SIGMA_KM_PER_DAY,
    COVARIANCE_MODEL_NAME,
    PC_METHOD_NAME,
    combined_sigma_at_tca_km,
    pc_foster_fast,
    sigma_tle_isotropic_km,
)
from orbital_sentinel.analytics.conjunctions.screening import (
    EARTH_GRAVITATIONAL_PARAMETER_KM3_S2,
    MAX_PAIRS_DEFAULT,
    SCREENING_ENGINE_VERSION,
    SCREENING_SCHEMA_VERSION,
    ScreeningResult,
    analyze_pairwise_screening,
)
from orbital_sentinel.analytics.conjunctions.storage import (
    PERSISTED_CONJUNCTION_SCHEMA_VERSION,
    ConjunctionDetection,
    ConjunctionDetectionError,
    ConjunctionDetectionsRepository,
    DetectionOrphan,
    DetectionsIntegrityReport,
    compute_detection_hash,
    verify_detections_integrity,
)

__all__ = [
    "CONJUNCTION_ENGINE_VERSION",
    "CONJUNCTION_SCHEMA_VERSION",
    "COVARIANCE_BASELINE_SIGMA_KM",
    "COVARIANCE_GROWTH_SIGMA_KM_PER_DAY",
    "COVARIANCE_MODEL_NAME",
    "EARTH_GRAVITATIONAL_PARAMETER_KM3_S2",
    "MAX_PAIRS_DEFAULT",
    "PC_METHOD_NAME",
    "PERSISTED_CONJUNCTION_SCHEMA_VERSION",
    "SCREENING_ENGINE_VERSION",
    "SCREENING_SCHEMA_VERSION",
    "SGP4_UNCERTAINTY_BASELINE_KM",
    "SGP4_UNCERTAINTY_GROWTH_KM_PER_DAY",
    "TCA_REFINEMENT_TOLERANCE_SECONDS",
    "ConjunctionAnalysis",
    "ConjunctionDetection",
    "ConjunctionDetectionError",
    "ConjunctionDetectionsRepository",
    "DetectionOrphan",
    "DetectionsIntegrityReport",
    "ScreeningResult",
    "analyze_pairwise_conjunction",
    "analyze_pairwise_screening",
    "combined_sigma_at_tca_km",
    "compute_detection_hash",
    "pc_foster_fast",
    "sigma_tle_isotropic_km",
    "verify_detections_integrity",
]
