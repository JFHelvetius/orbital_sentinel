"""Observatory scan (ADR-0025)."""

from orbital_sentinel.analytics.observatory.conflicts import (
    OVERLAP_DEFINITION_NAME,
    PassConflict,
    detect_pass_conflicts,
)
from orbital_sentinel.analytics.observatory.ranking import (
    RANKING_CRITERIA_VERSION,
    RankedPass,
    RankingCriterion,
    rank_passes,
)
from orbital_sentinel.analytics.observatory.scan import (
    EARTH_GRAVITATIONAL_PARAMETER_KM3_S2,
    MAX_SATELLITES_DEFAULT,
    OBSERVATORY_SCAN_ENGINE_VERSION,
    OBSERVATORY_SCAN_SCHEMA_VERSION,
    USEFUL_PASS_FILTER_VERSION,
    ObservatoryScan,
    SatellitePasses,
    UsefulPassFilter,
    is_geometrically_unreachable,
    scan_observatory,
)

__all__ = [
    "EARTH_GRAVITATIONAL_PARAMETER_KM3_S2",
    "MAX_SATELLITES_DEFAULT",
    "OBSERVATORY_SCAN_ENGINE_VERSION",
    "OBSERVATORY_SCAN_SCHEMA_VERSION",
    "OVERLAP_DEFINITION_NAME",
    "RANKING_CRITERIA_VERSION",
    "USEFUL_PASS_FILTER_VERSION",
    "ObservatoryScan",
    "PassConflict",
    "RankedPass",
    "RankingCriterion",
    "SatellitePasses",
    "UsefulPassFilter",
    "detect_pass_conflicts",
    "is_geometrically_unreachable",
    "rank_passes",
    "scan_observatory",
]
