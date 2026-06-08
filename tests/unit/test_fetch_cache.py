"""Tests del cache content-addressable (``FetchCache``)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from orbital_sentinel.ingestion.sources.cache import (
    CacheError,
    FetchCache,
)


@pytest.fixture
def cache_root(tmp_path: Path) -> Path:
    return tmp_path / "cache"


# --- Blobs ----------------------------------------------------------------


def test_put_blob_returns_sha256_hex(cache_root: Path) -> None:
    cache = FetchCache(cache_root)
    digest = cache.put_blob(b"hello")
    # SHA-256("hello")
    assert digest == "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"


def test_put_blob_is_idempotent(cache_root: Path) -> None:
    cache = FetchCache(cache_root)
    h1 = cache.put_blob(b"hello world")
    h2 = cache.put_blob(b"hello world")
    assert h1 == h2
    blob_files = list(cache.blobs_dir.rglob(f"{h1}.bin"))
    assert len(blob_files) == 1


def test_get_blob_roundtrip(cache_root: Path) -> None:
    cache = FetchCache(cache_root)
    h = cache.put_blob(b"payload")
    assert cache.get_blob(h) == b"payload"


def test_has_blob_returns_false_when_absent(cache_root: Path) -> None:
    cache = FetchCache(cache_root)
    assert cache.has_blob("a" * 64) is False


def test_get_blob_raises_when_absent(cache_root: Path) -> None:
    cache = FetchCache(cache_root)
    with pytest.raises(CacheError):
        cache.get_blob("a" * 64)


def test_blob_path_uses_first_two_chars(cache_root: Path) -> None:
    cache = FetchCache(cache_root)
    h = cache.put_blob(b"x")
    expected = cache.blobs_dir / h[:2] / f"{h}.bin"
    assert expected.exists()


def test_blob_path_rejects_invalid_hash(cache_root: Path) -> None:
    cache = FetchCache(cache_root)
    with pytest.raises(CacheError):
        cache.has_blob("too-short")


# --- Índice ---------------------------------------------------------------


def test_record_appends_jsonl(cache_root: Path) -> None:
    cache = FetchCache(cache_root)
    ts = datetime(2026, 6, 3, 12, 0, tzinfo=timezone.utc)
    cache.record(
        source="celestrak",
        dataset="stations",
        content_hash="a" * 64,
        fetched_at=ts,
        url="https://example.org/",
    )
    lines = cache.index_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["source"] == "celestrak"
    assert payload["dataset"] == "stations"
    assert payload["content_hash"] == "a" * 64
    assert payload["url"] == "https://example.org/"


def test_record_rejects_naive_datetime(cache_root: Path) -> None:
    cache = FetchCache(cache_root)
    with pytest.raises(CacheError):
        cache.record(
            source="x",
            dataset="y",
            content_hash="a" * 64,
            fetched_at=datetime(2026, 6, 3, 12, 0),
            url="https://example/",
        )


def test_record_converts_to_utc_in_storage(cache_root: Path) -> None:
    cache = FetchCache(cache_root)
    madrid = timezone(timedelta(hours=2))
    ts = datetime(2026, 6, 3, 14, 0, tzinfo=madrid)
    cache.record(
        source="x", dataset="y", content_hash="a" * 64,
        fetched_at=ts, url="https://example/",
    )
    payload = json.loads(cache.index_path.read_text(encoding="utf-8").strip())
    assert payload["fetched_at"].endswith("+00:00")
    assert "12:00:00" in payload["fetched_at"]


def test_latest_for_returns_most_recent(cache_root: Path) -> None:
    cache = FetchCache(cache_root)
    older = datetime(2026, 6, 3, 12, 0, tzinfo=timezone.utc)
    newer = datetime(2026, 6, 4, 12, 0, tzinfo=timezone.utc)
    cache.record(
        source="celestrak", dataset="stations",
        content_hash="b" * 64, fetched_at=older, url="https://a/",
    )
    cache.record(
        source="celestrak", dataset="stations",
        content_hash="c" * 64, fetched_at=newer, url="https://a/",
    )
    cache.record(
        source="celestrak", dataset="other",
        content_hash="d" * 64, fetched_at=newer + timedelta(hours=1),
        url="https://b/",
    )
    latest = cache.latest_for("celestrak", "stations")
    assert latest is not None
    assert latest.content_hash == "c" * 64


def test_latest_for_returns_none_when_empty(cache_root: Path) -> None:
    cache = FetchCache(cache_root)
    assert cache.latest_for("celestrak", "stations") is None


def test_latest_for_ignores_other_datasets(cache_root: Path) -> None:
    cache = FetchCache(cache_root)
    ts = datetime(2026, 6, 3, 12, 0, tzinfo=timezone.utc)
    cache.record(
        source="celestrak", dataset="active",
        content_hash="a" * 64, fetched_at=ts, url="https://a/",
    )
    assert cache.latest_for("celestrak", "stations") is None
