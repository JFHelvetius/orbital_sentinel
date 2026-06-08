"""Plano Catalog: storage de capas raw/normalized/derived (ADR-0002, ADR-0004, ADR-0006)."""

from orbital_sentinel.catalog.integrity import (
    IndexGap,
    IntegrityReport,
    OrphanElement,
    verify_integrity,
)
from orbital_sentinel.catalog.normalizers import (
    NORMALIZER_VERSION,
    normalize_snapshot,
)
from orbital_sentinel.catalog.orbital_elements import (
    ORBITAL_ELEMENTS_SCHEMA_VERSION,
    OrbitalElement,
    OrbitalElementsError,
    OrbitalElementsRepository,
)
from orbital_sentinel.catalog.tle_snapshots import (
    TLE_SNAPSHOTS_SCHEMA_VERSION,
    CatalogError,
    TLESnapshot,
    TLESnapshotsRepository,
)

__all__ = [
    "NORMALIZER_VERSION",
    "ORBITAL_ELEMENTS_SCHEMA_VERSION",
    "TLE_SNAPSHOTS_SCHEMA_VERSION",
    "CatalogError",
    "IndexGap",
    "IntegrityReport",
    "OrbitalElement",
    "OrbitalElementsError",
    "OrbitalElementsRepository",
    "OrphanElement",
    "TLESnapshot",
    "TLESnapshotsRepository",
    "normalize_snapshot",
    "verify_integrity",
]
