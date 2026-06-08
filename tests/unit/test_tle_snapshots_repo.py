"""Tests del repositorio ``TLESnapshotsRepository`` (capa Raw)."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

import pytest

from orbital_sentinel.catalog import (
    TLE_SNAPSHOTS_SCHEMA_VERSION,
    TLESnapshot,
    TLESnapshotsRepository,
)

SAMPLE_TEXT = (
    "ISS (ZARYA)\n"
    "1 25544U 98067A   08264.51782528 -.00002182  00000-0 -11606-4 0  2927\n"
    "2 25544  51.6416 247.4627 0006703 130.5360 325.0288 15.72125391563537\n"
)


def _make_snapshot(
    text: str = SAMPLE_TEXT,
    *,
    fetched_at: datetime | None = None,
    dataset: str = "stations",
) -> TLESnapshot:
    encoded = text.encode("ascii")
    return TLESnapshot(
        content_hash=hashlib.sha256(encoded).hexdigest(),
        source="celestrak",
        dataset=dataset,
        url=f"https://celestrak.org/NORAD/elements/gp.php?GROUP={dataset}&FORMAT=tle",
        fetched_at=fetched_at or datetime(2026, 6, 3, 12, 0, tzinfo=timezone.utc),
        raw_text=text,
        n_bytes=len(encoded),
    )


@pytest.fixture
def repo(tmp_path: Path) -> TLESnapshotsRepository:
    return TLESnapshotsRepository(tmp_path / "tle_snapshots")


# --- Vacío ----------------------------------------------------------------


def test_count_empty(repo: TLESnapshotsRepository) -> None:
    assert repo.count() == 0


def test_get_returns_none_when_empty(repo: TLESnapshotsRepository) -> None:
    assert repo.get("a" * 64) is None


def test_iter_all_yields_nothing_when_empty(repo: TLESnapshotsRepository) -> None:
    assert list(repo.iter_all()) == []


# --- Inserción ------------------------------------------------------------


def test_insert_writes_parquet(repo: TLESnapshotsRepository) -> None:
    snapshot = _make_snapshot()
    assert repo.insert(snapshot) is True
    assert repo.count() == 1


def test_insert_is_idempotent(repo: TLESnapshotsRepository) -> None:
    snapshot = _make_snapshot()
    assert repo.insert(snapshot) is True
    assert repo.insert(snapshot) is False
    assert repo.count() == 1


def test_insert_partitions_by_year_month(repo: TLESnapshotsRepository) -> None:
    snapshot = _make_snapshot(
        fetched_at=datetime(2027, 3, 15, 10, 30, tzinfo=timezone.utc),
    )
    repo.insert(snapshot)
    expected = (
        repo.root
        / "year=2027"
        / "month=03"
        / f"snap_{snapshot.content_hash}.parquet"
    )
    assert expected.is_file()


# --- Lectura --------------------------------------------------------------


def test_get_returns_inserted_snapshot(repo: TLESnapshotsRepository) -> None:
    snapshot = _make_snapshot()
    repo.insert(snapshot)
    retrieved = repo.get(snapshot.content_hash)
    assert retrieved is not None
    assert retrieved.content_hash == snapshot.content_hash
    assert retrieved.source == snapshot.source
    assert retrieved.dataset == snapshot.dataset
    assert retrieved.url == snapshot.url
    assert retrieved.raw_text == snapshot.raw_text
    assert retrieved.n_bytes == snapshot.n_bytes
    assert retrieved.schema_version == TLE_SNAPSHOTS_SCHEMA_VERSION
    assert retrieved.fetched_at == snapshot.fetched_at


def test_get_returns_none_for_unknown_hash(repo: TLESnapshotsRepository) -> None:
    repo.insert(_make_snapshot())
    assert repo.get("a" * 64) is None


def test_iter_all_returns_all_inserted(repo: TLESnapshotsRepository) -> None:
    s1 = _make_snapshot(text="payload one\n", dataset="a")
    s2 = _make_snapshot(text="payload two\n", dataset="b")
    repo.insert(s1)
    repo.insert(s2)
    hashes = {s.content_hash for s in repo.iter_all()}
    assert hashes == {s1.content_hash, s2.content_hash}


# --- Schema / inmutabilidad -----------------------------------------------


def test_schema_version_default_is_semver() -> None:
    snapshot = _make_snapshot()
    parts = snapshot.schema_version.split(".")
    assert len(parts) == 3
    assert all(p.isdigit() for p in parts)


def test_snapshot_is_frozen() -> None:
    snapshot = _make_snapshot()
    with pytest.raises(Exception):  # ValidationError o equivalente
        snapshot.source = "other"  # type: ignore[misc]


def test_insert_preserves_tz_through_parquet(repo: TLESnapshotsRepository) -> None:
    """fetched_at en otra zona horaria se almacena como UTC y se devuelve igual."""
    from datetime import timedelta as _td
    madrid = timezone(_td(hours=2))
    ts = datetime(2026, 6, 3, 14, 0, tzinfo=madrid)
    snapshot = _make_snapshot(fetched_at=ts)
    repo.insert(snapshot)
    retrieved = repo.get(snapshot.content_hash)
    assert retrieved is not None
    assert retrieved.fetched_at == ts  # mismo instante absoluto
