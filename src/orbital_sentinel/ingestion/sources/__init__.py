"""Fetchers de fuentes externas (ADR-0011, ADR-0012)."""

from orbital_sentinel.ingestion.sources.artifact import RawArtifact, Source
from orbital_sentinel.ingestion.sources.cache import (
    CacheError,
    CacheIndexEntry,
    FetchCache,
)
from orbital_sentinel.ingestion.sources.celestrak import (
    CELESTRAK_BASE_URL,
    DEFAULT_MAX_AGE,
    DEFAULT_USER_AGENT,
    CelesTrakSource,
)
from orbital_sentinel.ingestion.sources.transport import (
    HttpTransport,
    TransportError,
    UrllibTransport,
)

__all__ = [
    "CELESTRAK_BASE_URL",
    "DEFAULT_MAX_AGE",
    "DEFAULT_USER_AGENT",
    "CacheError",
    "CacheIndexEntry",
    "CelesTrakSource",
    "FetchCache",
    "HttpTransport",
    "RawArtifact",
    "Source",
    "TransportError",
    "UrllibTransport",
]
