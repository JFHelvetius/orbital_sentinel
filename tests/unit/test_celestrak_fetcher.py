"""Tests del fetcher CelesTrak con transporte fake (sin red)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from orbital_sentinel.ingestion.sources import (
    CELESTRAK_BASE_URL,
    DEFAULT_USER_AGENT,
    CelesTrakSource,
    FetchCache,
    RawArtifact,
)

SAMPLE_TLE = (
    b"ISS (ZARYA)\n"
    b"1 25544U 98067A   08264.51782528 -.00002182  00000-0 -11606-4 0  2927\n"
    b"2 25544  51.6416 247.4627 0006703 130.5360 325.0288 15.72125391563537\n"
)


class FakeTransport:
    """Transport HTTP fake. Falla si una URL no está pre-registrada."""

    def __init__(self, responses: dict[str, bytes]) -> None:
        self._responses = responses
        self.calls: list[tuple[str, dict[str, str]]] = []

    def get(self, url: str, *, headers: dict[str, str], timeout: float = 30.0) -> bytes:
        self.calls.append((url, dict(headers)))
        if url not in self._responses:
            raise RuntimeError(f"URL inesperada en test: {url}")
        return self._responses[url]


class FrozenClock:
    """Reloj con secuencia de tiempos. Si solo hay uno, lo repite."""

    def __init__(self, *times: datetime) -> None:
        if not times:
            raise ValueError("se requiere al menos un timestamp")
        self._times = list(times)

    def __call__(self) -> datetime:
        if len(self._times) == 1:
            return self._times[0]
        return self._times.pop(0)


@pytest.fixture
def cache(tmp_path: Path) -> FetchCache:
    return FetchCache(tmp_path / "cache")


GROUP_URL = f"{CELESTRAK_BASE_URL}?GROUP=stations&FORMAT=tle"
CATNR_URL = f"{CELESTRAK_BASE_URL}?CATNR=25544&FORMAT=tle"


def test_fetch_hits_transport_when_cache_empty(cache: FetchCache) -> None:
    transport = FakeTransport({GROUP_URL: SAMPLE_TLE})
    clock = FrozenClock(datetime(2026, 6, 3, 12, 0, tzinfo=timezone.utc))

    source = CelesTrakSource(cache=cache, transport=transport, clock=clock)
    artifact = source.fetch("stations")

    assert isinstance(artifact, RawArtifact)
    assert artifact.source == "celestrak"
    assert artifact.dataset == "stations"
    assert artifact.url == GROUP_URL
    assert artifact.raw_bytes == SAMPLE_TLE
    assert len(transport.calls) == 1


def test_fetch_uses_cache_when_recent(cache: FetchCache) -> None:
    transport = FakeTransport({GROUP_URL: SAMPLE_TLE})
    base = datetime(2026, 6, 3, 12, 0, tzinfo=timezone.utc)
    clock = FrozenClock(base, base + timedelta(hours=1))

    source = CelesTrakSource(cache=cache, transport=transport, clock=clock)
    a = source.fetch("stations")
    b = source.fetch("stations")

    assert a.content_hash == b.content_hash
    assert len(transport.calls) == 1


def test_fetch_uses_transport_when_cache_stale(cache: FetchCache) -> None:
    transport = FakeTransport({GROUP_URL: SAMPLE_TLE})
    base = datetime(2026, 6, 3, 12, 0, tzinfo=timezone.utc)
    clock = FrozenClock(base, base + timedelta(hours=12))

    source = CelesTrakSource(
        cache=cache, transport=transport, clock=clock,
        max_age=timedelta(hours=6),
    )
    source.fetch("stations")
    source.fetch("stations")

    assert len(transport.calls) == 2


def test_fetch_force_always_hits_transport(cache: FetchCache) -> None:
    transport = FakeTransport({GROUP_URL: SAMPLE_TLE})
    base = datetime(2026, 6, 3, 12, 0, tzinfo=timezone.utc)
    clock = FrozenClock(base, base + timedelta(minutes=1))

    source = CelesTrakSource(cache=cache, transport=transport, clock=clock)
    source.fetch("stations")
    source.fetch("stations", force=True)

    assert len(transport.calls) == 2


def test_fetch_sends_user_agent_header(cache: FetchCache) -> None:
    transport = FakeTransport({GROUP_URL: SAMPLE_TLE})
    source = CelesTrakSource(cache=cache, transport=transport)
    source.fetch("stations")
    _, headers = transport.calls[0]
    assert headers.get("User-Agent") == DEFAULT_USER_AGENT


def test_fetch_builds_group_url(cache: FetchCache) -> None:
    transport = FakeTransport({GROUP_URL: SAMPLE_TLE})
    source = CelesTrakSource(cache=cache, transport=transport)
    artifact = source.fetch("stations")
    assert artifact.url == GROUP_URL


def test_fetch_builds_catnr_url_for_catnr_prefix(cache: FetchCache) -> None:
    transport = FakeTransport({CATNR_URL: SAMPLE_TLE})
    source = CelesTrakSource(cache=cache, transport=transport)
    artifact = source.fetch("catnr-25544")
    assert artifact.url == CATNR_URL


def test_fetch_persists_bytes_in_cache(cache: FetchCache) -> None:
    transport = FakeTransport({GROUP_URL: SAMPLE_TLE})
    source = CelesTrakSource(cache=cache, transport=transport)
    artifact = source.fetch("stations")
    assert cache.has_blob(artifact.content_hash)
    assert cache.get_blob(artifact.content_hash) == SAMPLE_TLE


def test_fetch_records_index_entry(cache: FetchCache) -> None:
    transport = FakeTransport({GROUP_URL: SAMPLE_TLE})
    source = CelesTrakSource(cache=cache, transport=transport)
    artifact = source.fetch("stations")
    latest = cache.latest_for("celestrak", "stations")
    assert latest is not None
    assert latest.content_hash == artifact.content_hash
    assert latest.url == GROUP_URL


def test_fetch_refetches_when_blob_missing(cache: FetchCache) -> None:
    """Si el índice apunta a un blob borrado manualmente, el fetcher vuelve a la red."""
    transport = FakeTransport({GROUP_URL: SAMPLE_TLE})
    base = datetime(2026, 6, 3, 12, 0, tzinfo=timezone.utc)
    clock = FrozenClock(base, base + timedelta(minutes=1))

    source = CelesTrakSource(cache=cache, transport=transport, clock=clock)
    artifact = source.fetch("stations")

    blob_path = cache.blobs_dir / artifact.content_hash[:2] / f"{artifact.content_hash}.bin"
    blob_path.unlink()

    artifact2 = source.fetch("stations")
    assert artifact2.content_hash == artifact.content_hash
    assert len(transport.calls) == 2


def test_fetch_dedup_when_content_unchanged(cache: FetchCache) -> None:
    """Force=True re-descarga, pero si los bytes son idénticos no se duplica el blob."""
    transport = FakeTransport({GROUP_URL: SAMPLE_TLE})
    base = datetime(2026, 6, 3, 12, 0, tzinfo=timezone.utc)
    clock = FrozenClock(base, base + timedelta(minutes=1))

    source = CelesTrakSource(cache=cache, transport=transport, clock=clock)
    a = source.fetch("stations")
    b = source.fetch("stations", force=True)

    assert a.content_hash == b.content_hash
    blobs = list(cache.blobs_dir.rglob("*.bin"))
    assert len(blobs) == 1
