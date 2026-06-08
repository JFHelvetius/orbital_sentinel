"""Tests end-to-end del pipeline Raw → Normalized, sin red.

El transporte HTTP se sustituye por :class:`FakeTransport`, que falla
ruidosamente si una URL no está pre-registrada. Cualquier escape accidental
a la red durante un test se hace visible inmediatamente.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from orbital_sentinel.catalog import (
    OrbitalElementsRepository,
    TLESnapshotsRepository,
    verify_integrity,
)
from orbital_sentinel.core.errors import IngestionError, NormalizationError
from orbital_sentinel.ingestion.sources import (
    CELESTRAK_BASE_URL,
    CelesTrakSource,
    FetchCache,
)
from orbital_sentinel.orchestration import IngestPipeline, IngestResult

GROUP_URL = f"{CELESTRAK_BASE_URL}?GROUP=stations&FORMAT=tle"

MULTI_TLE = (
    b"ISS (ZARYA)\n"
    b"1 25544U 98067A   08264.51782528 -.00002182  00000-0 -11606-4 0  2927\n"
    b"2 25544  51.6416 247.4627 0006703 130.5360 325.0288 15.72125391563537\n"
    b"TEST-99999\n"
    b"1 99999U 24001A   24001.00000000  .00000000  00000-0  00000-0 0  9999\n"
    b"2 99999   0.0000   0.0000 0000000   0.0000   0.0000  1.00000000    19\n"
)


class FakeTransport:
    def __init__(self, responses: dict[str, bytes]) -> None:
        self._responses = responses
        self.calls: list[tuple[str, dict[str, str]]] = []

    def get(self, url: str, *, headers: dict[str, str], timeout: float = 30.0) -> bytes:
        self.calls.append((url, dict(headers)))
        if url not in self._responses:
            raise RuntimeError(f"URL inesperada en test: {url}")
        return self._responses[url]


class FrozenClock:
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


@pytest.fixture
def snapshots(tmp_path: Path) -> TLESnapshotsRepository:
    return TLESnapshotsRepository(tmp_path / "raw")


@pytest.fixture
def elements(tmp_path: Path) -> OrbitalElementsRepository:
    return OrbitalElementsRepository(tmp_path / "normalized")


def _make_pipeline(
    cache: FetchCache,
    snapshots: TLESnapshotsRepository,
    elements: OrbitalElementsRepository,
    *,
    payload: bytes = MULTI_TLE,
    clock: FrozenClock | None = None,
) -> tuple[IngestPipeline, FakeTransport]:
    transport = FakeTransport({GROUP_URL: payload})
    source = CelesTrakSource(cache=cache, transport=transport, clock=clock)
    pipeline = IngestPipeline(
        source=source,
        snapshots=snapshots,
        elements=elements,
        clock=clock,
    )
    return pipeline, transport


# --- Happy path -----------------------------------------------------------


def test_ingest_writes_raw_and_normalized(
    cache: FetchCache,
    snapshots: TLESnapshotsRepository,
    elements: OrbitalElementsRepository,
) -> None:
    pipeline, _ = _make_pipeline(cache, snapshots, elements)
    result = pipeline.ingest("stations")

    assert isinstance(result, IngestResult)
    assert result.snapshot_written is True
    assert result.elements_written == 2
    assert result.is_new is True
    assert snapshots.count() == 1
    assert elements.count() == 2


def test_ingest_chains_traceability(
    cache: FetchCache,
    snapshots: TLESnapshotsRepository,
    elements: OrbitalElementsRepository,
) -> None:
    """content_hash del fetcher == content_hash_source de cada Normalized."""
    pipeline, _ = _make_pipeline(cache, snapshots, elements)
    result = pipeline.ingest("stations")

    rows = elements.get_by_snapshot(result.artifact.content_hash)
    assert len(rows) == 2
    for el in rows:
        assert el.content_hash_source == result.artifact.content_hash


def test_ingest_records_snapshot_provenance_in_raw(
    cache: FetchCache,
    snapshots: TLESnapshotsRepository,
    elements: OrbitalElementsRepository,
) -> None:
    pipeline, _ = _make_pipeline(cache, snapshots, elements)
    result = pipeline.ingest("stations")

    stored = snapshots.get(result.artifact.content_hash)
    assert stored is not None
    assert stored.source == "celestrak"
    assert stored.dataset == "stations"
    assert stored.url == GROUP_URL
    assert stored.raw_text == MULTI_TLE.decode("ascii")


# --- Idempotencia ---------------------------------------------------------


def test_ingest_is_idempotent(
    cache: FetchCache,
    snapshots: TLESnapshotsRepository,
    elements: OrbitalElementsRepository,
) -> None:
    pipeline, _ = _make_pipeline(cache, snapshots, elements)
    a = pipeline.ingest("stations")
    b = pipeline.ingest("stations")

    assert a.snapshot_written is True
    assert b.snapshot_written is False
    assert b.elements_written == 0
    assert b.is_new is False
    assert snapshots.count() == 1
    assert elements.count() == 2


def test_repeated_ingest_does_not_touch_network_when_cache_warm(
    cache: FetchCache,
    snapshots: TLESnapshotsRepository,
    elements: OrbitalElementsRepository,
) -> None:
    base = datetime(2026, 6, 3, 12, 0, tzinfo=timezone.utc)
    clock = FrozenClock(base, base + timedelta(minutes=1))
    pipeline, transport = _make_pipeline(cache, snapshots, elements, clock=clock)

    pipeline.ingest("stations")
    pipeline.ingest("stations")

    assert len(transport.calls) == 1


# --- Fail-fast en normalización con Raw persistido ------------------------


def test_normalization_failure_persists_raw_anyway(
    cache: FetchCache,
    snapshots: TLESnapshotsRepository,
    elements: OrbitalElementsRepository,
) -> None:
    """TLE con checksum inválido: Raw queda, Normalized vacío, NormalizationError lanza."""
    bad = (
        b"1 25544U 98067A   08264.51782528 -.00002182  00000-0 -11606-4 0  2920\n"  # bad
        b"2 25544  51.6416 247.4627 0006703 130.5360 325.0288 15.72125391563537\n"
    )
    pipeline, _ = _make_pipeline(cache, snapshots, elements, payload=bad)

    with pytest.raises(NormalizationError):
        pipeline.ingest("stations")

    assert snapshots.count() == 1  # Raw persistido para auditoría
    assert elements.count() == 0


# --- Rechazo de bytes no ASCII --------------------------------------------


def test_ingest_rejects_non_ascii_payload(
    cache: FetchCache,
    snapshots: TLESnapshotsRepository,
    elements: OrbitalElementsRepository,
) -> None:
    payload = b"\xff\xfe non ASCII garbage \xc3\xa9\n"
    pipeline, _ = _make_pipeline(cache, snapshots, elements, payload=payload)

    with pytest.raises(IngestionError):
        pipeline.ingest("stations")
    assert snapshots.count() == 0
    assert elements.count() == 0


# --- Clock injection ------------------------------------------------------


def test_ingest_uses_clock_for_derived_at(
    cache: FetchCache,
    snapshots: TLESnapshotsRepository,
    elements: OrbitalElementsRepository,
) -> None:
    clock_time = datetime(2027, 3, 15, 10, 0, tzinfo=timezone.utc)
    pipeline, _ = _make_pipeline(
        cache, snapshots, elements, clock=FrozenClock(clock_time)
    )
    pipeline.ingest("stations")

    snapshot_hash = next(snapshots.iter_all()).content_hash
    for el in elements.get_by_snapshot(snapshot_hash):
        assert el.derived_at == clock_time


# --- Integridad end-to-end ------------------------------------------------


def test_end_to_end_passes_integrity(
    cache: FetchCache,
    snapshots: TLESnapshotsRepository,
    elements: OrbitalElementsRepository,
) -> None:
    pipeline, _ = _make_pipeline(cache, snapshots, elements)
    pipeline.ingest("stations")

    report = verify_integrity(snapshots, elements)
    assert report.has_violations is False
    assert report.orphan_elements == []
    assert report.index_gaps == []
    assert report.unnormalized_snapshots == []
