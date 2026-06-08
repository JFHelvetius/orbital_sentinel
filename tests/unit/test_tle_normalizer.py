"""Tests del normalizador Raw → Normalized."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

import pytest

from orbital_sentinel.catalog import TLESnapshot
from orbital_sentinel.catalog.normalizers import (
    NORMALIZER_VERSION,
    normalize_snapshot,
    tle_epoch_to_datetime,
)
from orbital_sentinel.catalog.orbital_elements import (
    ORBITAL_ELEMENTS_SCHEMA_VERSION,
)
from orbital_sentinel.core.errors import NormalizationError
from orbital_sentinel.ingestion.parsers.tle import parse_tle

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "tle"

DERIVED_AT = datetime(2026, 6, 3, 12, 0, tzinfo=timezone.utc)


def _make_snapshot(text: str, dataset: str = "stations") -> TLESnapshot:
    encoded = text.encode("ascii")
    return TLESnapshot(
        content_hash=hashlib.sha256(encoded).hexdigest(),
        source="celestrak",
        dataset=dataset,
        url=f"https://celestrak.org/NORAD/elements/gp.php?GROUP={dataset}&FORMAT=tle",
        fetched_at=DERIVED_AT,
        raw_text=text,
        n_bytes=len(encoded),
    )


# --- tle_epoch_to_datetime ------------------------------------------------


def test_epoch_day_1_is_jan_1_midnight() -> None:
    assert tle_epoch_to_datetime(2024, 1.0) == datetime(
        2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc
    )


def test_epoch_canonical_iss_2008() -> None:
    """ISS Vallado: 2008 day 264.51782528 → 2008-09-20 ~12:25:40 UTC."""
    result = tle_epoch_to_datetime(2008, 264.51782528)
    assert result.year == 2008
    assert result.month == 9
    assert result.day == 20
    expected_seconds_into_day = 0.51782528 * 86400
    actual_seconds_into_day = (
        result.hour * 3600
        + result.minute * 60
        + result.second
        + result.microsecond / 1e6
    )
    assert actual_seconds_into_day == pytest.approx(expected_seconds_into_day, abs=1e-3)


def test_epoch_leap_year_day_366() -> None:
    assert tle_epoch_to_datetime(2008, 366.0) == datetime(
        2008, 12, 31, 0, 0, 0, tzinfo=timezone.utc
    )


def test_epoch_non_leap_year_day_365() -> None:
    assert tle_epoch_to_datetime(2007, 365.0) == datetime(
        2007, 12, 31, 0, 0, 0, tzinfo=timezone.utc
    )


def test_epoch_returns_utc_tzaware() -> None:
    result = tle_epoch_to_datetime(2024, 100.5)
    assert result.tzinfo is timezone.utc


# --- normalize_snapshot — happy path --------------------------------------


def test_normalizes_single_tle_to_one_element() -> None:
    text = (FIXTURES / "iss_vallado_2008.txt").read_text(encoding="ascii")
    snap = _make_snapshot(text)
    elements = normalize_snapshot(snap, derived_at=DERIVED_AT)
    assert len(elements) == 1


def test_normalizes_multi_tle_snapshot_to_n_elements() -> None:
    text = (FIXTURES / "multi_stations.txt").read_text(encoding="ascii")
    snap = _make_snapshot(text)
    elements = normalize_snapshot(snap, derived_at=DERIVED_AT)
    assert len(elements) == 2
    assert elements[0].norad_cat_id == 25544
    assert elements[1].norad_cat_id == 99999


# --- Trazabilidad ---------------------------------------------------------


def test_element_carries_content_hash_source() -> None:
    text = (FIXTURES / "iss_vallado_2008.txt").read_text(encoding="ascii")
    snap = _make_snapshot(text)
    [element] = normalize_snapshot(snap, derived_at=DERIVED_AT)
    assert element.content_hash_source == snap.content_hash


def test_element_tle_index_in_order() -> None:
    text = (FIXTURES / "multi_stations.txt").read_text(encoding="ascii")
    snap = _make_snapshot(text)
    elements = normalize_snapshot(snap, derived_at=DERIVED_AT)
    assert [el.tle_index for el in elements] == [0, 1]


def test_element_tle_content_hash_matches_parser() -> None:
    """tle_content_hash debe igualar exactamente el hash producido por parse_tle."""
    block = (
        "1 25544U 98067A   08264.51782528 -.00002182  00000-0 -11606-4 0  2927\n"
        "2 25544  51.6416 247.4627 0006703 130.5360 325.0288 15.72125391563537"
    )
    parsed = parse_tle(block)

    text = (FIXTURES / "iss_vallado_2008.txt").read_text(encoding="ascii")
    snap = _make_snapshot(text)
    [element] = normalize_snapshot(snap, derived_at=DERIVED_AT)
    assert element.tle_content_hash == parsed.content_hash


def test_element_tle_content_hash_invariant_to_name_line() -> None:
    """Snapshots con y sin línea de nombre producen el mismo tle_content_hash."""
    text_with = (FIXTURES / "iss_vallado_2008.txt").read_text(encoding="ascii")
    text_without = (FIXTURES / "iss_vallado_2008_no_name.txt").read_text(encoding="ascii")
    [a] = normalize_snapshot(_make_snapshot(text_with), derived_at=DERIVED_AT)
    [b] = normalize_snapshot(_make_snapshot(text_without), derived_at=DERIVED_AT)
    assert a.tle_content_hash == b.tle_content_hash


# --- Epoch derivado -------------------------------------------------------


def test_element_epoch_datetime_computed() -> None:
    text = (FIXTURES / "iss_vallado_2008.txt").read_text(encoding="ascii")
    snap = _make_snapshot(text)
    [element] = normalize_snapshot(snap, derived_at=DERIVED_AT)
    assert element.epoch_datetime.year == 2008
    assert element.epoch_datetime.month == 9
    assert element.epoch_datetime.day == 20
    assert element.epoch_datetime.tzinfo is timezone.utc


# --- Versioning -----------------------------------------------------------


def test_element_engine_version_default() -> None:
    text = (FIXTURES / "iss_vallado_2008.txt").read_text(encoding="ascii")
    [element] = normalize_snapshot(_make_snapshot(text), derived_at=DERIVED_AT)
    assert element.engine_version == NORMALIZER_VERSION


def test_element_engine_version_explicit_override() -> None:
    text = (FIXTURES / "iss_vallado_2008.txt").read_text(encoding="ascii")
    [element] = normalize_snapshot(
        _make_snapshot(text), derived_at=DERIVED_AT, engine_version="0.99.99"
    )
    assert element.engine_version == "0.99.99"


def test_element_schema_version() -> None:
    text = (FIXTURES / "iss_vallado_2008.txt").read_text(encoding="ascii")
    [element] = normalize_snapshot(_make_snapshot(text), derived_at=DERIVED_AT)
    assert element.schema_version == ORBITAL_ELEMENTS_SCHEMA_VERSION


def test_element_derived_at_recorded() -> None:
    text = (FIXTURES / "iss_vallado_2008.txt").read_text(encoding="ascii")
    [element] = normalize_snapshot(_make_snapshot(text), derived_at=DERIVED_AT)
    assert element.derived_at == DERIVED_AT


def test_element_derived_at_converted_to_utc() -> None:
    """derived_at en otra TZ se almacena como UTC equivalente."""
    from datetime import timedelta
    madrid = timezone(timedelta(hours=2))
    ts = datetime(2026, 6, 3, 14, 0, tzinfo=madrid)
    text = (FIXTURES / "iss_vallado_2008.txt").read_text(encoding="ascii")
    [element] = normalize_snapshot(_make_snapshot(text), derived_at=ts)
    assert element.derived_at == ts  # mismo instante absoluto
    assert element.derived_at.utcoffset().total_seconds() == 0


# --- Object name ----------------------------------------------------------


def test_element_object_name_from_three_line_tle() -> None:
    text = (FIXTURES / "iss_vallado_2008.txt").read_text(encoding="ascii")
    [element] = normalize_snapshot(_make_snapshot(text), derived_at=DERIVED_AT)
    assert element.object_name == "ISS (ZARYA)"


def test_element_object_name_none_when_no_name_line() -> None:
    text = (FIXTURES / "iss_vallado_2008_no_name.txt").read_text(encoding="ascii")
    [element] = normalize_snapshot(_make_snapshot(text), derived_at=DERIVED_AT)
    assert element.object_name is None


# --- Pureza / determinismo ------------------------------------------------


def test_normalizer_is_pure_deterministic() -> None:
    """Misma entrada → misma salida bit-idéntica (ADR-0006 reproducibilidad)."""
    text = (FIXTURES / "multi_stations.txt").read_text(encoding="ascii")
    snap = _make_snapshot(text)
    a = normalize_snapshot(snap, derived_at=DERIVED_AT)
    b = normalize_snapshot(snap, derived_at=DERIVED_AT)
    assert [el.model_dump() for el in a] == [el.model_dump() for el in b]


# --- Errores --------------------------------------------------------------


def test_normalizer_raises_on_malformed_block() -> None:
    """Si el snapshot tiene un TLE con checksum inválido, normalize lanza."""
    bad = (
        "1 25544U 98067A   08264.51782528 -.00002182  00000-0 -11606-4 0  2920\n"
        "2 25544  51.6416 247.4627 0006703 130.5360 325.0288 15.72125391563537\n"
    )
    with pytest.raises(NormalizationError):
        normalize_snapshot(_make_snapshot(bad), derived_at=DERIVED_AT)


def test_normalizer_rejects_naive_derived_at() -> None:
    text = (FIXTURES / "iss_vallado_2008.txt").read_text(encoding="ascii")
    with pytest.raises(NormalizationError):
        normalize_snapshot(_make_snapshot(text), derived_at=datetime(2026, 6, 3, 12, 0))


def test_normalizer_propagates_context_in_error() -> None:
    """El mensaje del error incluye el índice del bloque y prefijo del hash."""
    valid_iss = (
        "1 25544U 98067A   08264.51782528 -.00002182  00000-0 -11606-4 0  2927\n"
        "2 25544  51.6416 247.4627 0006703 130.5360 325.0288 15.72125391563537\n"
    )
    bad_second = (
        "1 99999U 24001A   24001.00000000  .00000000  00000-0  00000-0 0  9990\n"
        "2 99999   0.0000   0.0000 0000000   0.0000   0.0000  1.00000000    19\n"
    )
    snap = _make_snapshot(valid_iss + bad_second)
    with pytest.raises(NormalizationError) as exc_info:
        normalize_snapshot(snap, derived_at=DERIVED_AT)
    msg = str(exc_info.value)
    assert "índice 1" in msg
    assert snap.content_hash[:12] in msg
