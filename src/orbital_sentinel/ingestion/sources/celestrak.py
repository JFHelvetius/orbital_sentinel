"""Fetcher para los endpoints GP TLE de CelesTrak.

CelesTrak es una fuente pública sin autenticación (ADR-0011). Pide únicamente
un ``User-Agent`` identificable. Se respetan sus términos de servicio como
parte del cumplimiento contractual declarado en ADR-0000.

Política cache-first (ADR-0012):

* Si el índice tiene una observación para ``(source='celestrak', dataset=X)``
  dentro de ``max_age`` y el blob existe, se devuelve sin contactar la red.
* En caso contrario se invoca el transporte; los bytes y la entrada de índice
  se persisten antes de devolver el :class:`RawArtifact`.
* ``force=True`` siempre contacta el transporte; la deduplicación por hash
  hace que un fetch idéntico no reescriba el blob.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import datetime, timedelta, timezone

from orbital_sentinel import __version__
from orbital_sentinel.ingestion.sources.artifact import RawArtifact
from orbital_sentinel.ingestion.sources.cache import FetchCache
from orbital_sentinel.ingestion.sources.transport import HttpTransport, UrllibTransport

CELESTRAK_BASE_URL = "https://celestrak.org/NORAD/elements/gp.php"

DEFAULT_USER_AGENT = (
    f"orbital-sentinel/{__version__} "
    "(+https://github.com/orbital-sentinel/orbital-sentinel)"
)

DEFAULT_MAX_AGE = timedelta(hours=6)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class CelesTrakSource:
    """Fetcher de TLEs desde CelesTrak.

    Los ``dataset`` aceptados son nombres GROUP de CelesTrak (``stations``,
    ``active``, ``visual``, etc.) o el prefijo ``catnr-<id>`` para obtener
    un único satélite por NORAD ID.
    """

    name = "celestrak"

    def __init__(
        self,
        cache: FetchCache,
        transport: HttpTransport | None = None,
        *,
        user_agent: str = DEFAULT_USER_AGENT,
        max_age: timedelta = DEFAULT_MAX_AGE,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._cache = cache
        self._transport: HttpTransport = transport if transport is not None else UrllibTransport()
        self._user_agent = user_agent
        self._max_age = max_age
        self._clock: Callable[[], datetime] = clock if clock is not None else _utc_now

    def fetch(self, dataset: str, *, force: bool = False) -> RawArtifact:
        url = self._build_url(dataset)
        now = self._clock()

        if not force:
            cached = self._try_cache(dataset, now)
            if cached is not None:
                return cached

        raw_bytes = self._transport.get(
            url,
            headers={"User-Agent": self._user_agent},
            timeout=30.0,
        )
        content_hash = hashlib.sha256(raw_bytes).hexdigest()
        self._cache.put_blob(raw_bytes)
        self._cache.record(
            source=self.name,
            dataset=dataset,
            content_hash=content_hash,
            fetched_at=now,
            url=url,
        )
        return RawArtifact(
            source=self.name,
            dataset=dataset,
            url=url,
            fetched_at=now,
            raw_bytes=raw_bytes,
            content_hash=content_hash,
        )

    # --- Internos --------------------------------------------------------

    def _try_cache(self, dataset: str, now: datetime) -> RawArtifact | None:
        latest = self._cache.latest_for(self.name, dataset)
        if latest is None:
            return None
        if (now - latest.fetched_at) >= self._max_age:
            return None
        if not self._cache.has_blob(latest.content_hash):
            return None
        raw_bytes = self._cache.get_blob(latest.content_hash)
        return RawArtifact(
            source=self.name,
            dataset=dataset,
            url=latest.url,
            fetched_at=latest.fetched_at,
            raw_bytes=raw_bytes,
            content_hash=latest.content_hash,
        )

    def _build_url(self, dataset: str) -> str:
        if dataset.startswith("catnr-"):
            catnr = dataset[len("catnr-"):]
            return f"{CELESTRAK_BASE_URL}?CATNR={catnr}&FORMAT=tle"
        return f"{CELESTRAK_BASE_URL}?GROUP={dataset}&FORMAT=tle"
