"""Tests del validador de integridad ``verify_integrity``.

Cubren los invariantes I1 (referencial Normalized→Raw) e I2 (continuidad de
``tle_index``), y demuestran detección de corrupción deliberada:

* Inserción ad-hoc en Normalized sin Raw correspondiente.
* Borrado manual del Parquet de Raw tras tener Normalized.
* Inserción de batches con índices no contiguos.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

import pytest

from orbital_sentinel.catalog import (
    OrbitalElement,
    OrbitalElementsRepository,
    TLESnapshot,
    TLESnapshotsRepository,
    verify_integrity,
)

DERIVED_AT = datetime(2026, 6, 3, 12, 0, tzinfo=timezone.utc)
EPOCH = datetime(2008, 9, 20, 12, 25, 40, tzinfo=timezone.utc)


def _make_snapshot(text: str = "data", dataset: str = "stations") -> TLESnapshot:
    encoded = text.encode("ascii")
    return TLESnapshot(
        content_hash=hashlib.sha256(encoded).hexdigest(),
        source="celestrak",
        dataset=dataset,
        url=f"https://example/?GROUP={dataset}",
        fetched_at=DERIVED_AT,
        raw_text=text,
        n_bytes=len(encoded),
    )


def _make_element(
    *,
    content_hash_source: str,
    tle_index: int = 0,
    norad_cat_id: int = 25544,
    engine_version: str = "0.1.0",
) -> OrbitalElement:
    return OrbitalElement(
        content_hash_source=content_hash_source,
        tle_index=tle_index,
        tle_content_hash="b" * 64,
        object_name="ISS (ZARYA)",
        norad_cat_id=norad_cat_id,
        classification="U",
        intl_designator="98067A",
        epoch_year=2008,
        epoch_day=264.51782528,
        epoch_datetime=EPOCH,
        mean_motion_dot=0.0,
        mean_motion_ddot=0.0,
        bstar=0.0,
        ephemeris_type=0,
        element_set_number=1,
        inclination_deg=51.6,
        raan_deg=0.0,
        eccentricity=0.0,
        arg_perigee_deg=0.0,
        mean_anomaly_deg=0.0,
        mean_motion=15.0,
        rev_number=1,
        engine_version=engine_version,
        derived_at=DERIVED_AT,
    )


@pytest.fixture
def snapshots(tmp_path: Path) -> TLESnapshotsRepository:
    return TLESnapshotsRepository(tmp_path / "raw")


@pytest.fixture
def elements(tmp_path: Path) -> OrbitalElementsRepository:
    return OrbitalElementsRepository(tmp_path / "normalized")


# --- Estado limpio --------------------------------------------------------


def test_empty_state_has_no_violations(
    snapshots: TLESnapshotsRepository, elements: OrbitalElementsRepository
) -> None:
    report = verify_integrity(snapshots, elements)
    assert report.has_violations is False
    assert report.orphan_elements == []
    assert report.index_gaps == []
    assert report.unnormalized_snapshots == []


def test_clean_state_when_raw_and_normalized_consistent(
    snapshots: TLESnapshotsRepository, elements: OrbitalElementsRepository
) -> None:
    snap = _make_snapshot()
    snapshots.insert(snap)
    elements.insert_many(
        [
            _make_element(content_hash_source=snap.content_hash, tle_index=0),
            _make_element(content_hash_source=snap.content_hash, tle_index=1),
        ]
    )
    report = verify_integrity(snapshots, elements)
    assert report.has_violations is False


# --- Estado informativo: Raw sin Normalized -------------------------------


def test_only_raw_marks_unnormalized_but_not_violation(
    snapshots: TLESnapshotsRepository, elements: OrbitalElementsRepository
) -> None:
    snap = _make_snapshot()
    snapshots.insert(snap)
    report = verify_integrity(snapshots, elements)
    assert report.has_violations is False  # informativo, no violación
    assert report.unnormalized_snapshots == [snap.content_hash]


# --- I1: integridad referencial Normalized → Raw --------------------------


def test_detects_orphan_element_pointing_nowhere(
    snapshots: TLESnapshotsRepository, elements: OrbitalElementsRepository
) -> None:
    """Inserción ad-hoc en Normalized con un content_hash_source ficticio."""
    fake_hash = "f" * 64
    elements.insert_many([_make_element(content_hash_source=fake_hash, tle_index=0)])

    report = verify_integrity(snapshots, elements)
    assert report.has_violations is True
    assert len(report.orphan_elements) == 1
    assert report.orphan_elements[0].content_hash_source == fake_hash
    assert report.orphan_elements[0].tle_index == 0


def test_detects_orphan_after_manual_raw_deletion(
    snapshots: TLESnapshotsRepository, elements: OrbitalElementsRepository
) -> None:
    """Corrupción manual: borrar el Parquet de Raw tras haber persistido coherente."""
    snap = _make_snapshot()
    snapshots.insert(snap)
    elements.insert_many(
        [_make_element(content_hash_source=snap.content_hash, tle_index=0)]
    )

    for path in snapshots.root.rglob("*.parquet"):
        path.unlink()

    report = verify_integrity(snapshots, elements)
    assert report.has_violations is True
    assert report.orphan_elements[0].content_hash_source == snap.content_hash


def test_orphan_report_carries_engine_version(
    snapshots: TLESnapshotsRepository, elements: OrbitalElementsRepository
) -> None:
    fake = "f" * 64
    elements.insert_many(
        [_make_element(content_hash_source=fake, tle_index=0, engine_version="0.5.0")]
    )
    report = verify_integrity(snapshots, elements)
    assert report.orphan_elements[0].engine_version == "0.5.0"


def test_multiple_orphans_in_same_batch(
    snapshots: TLESnapshotsRepository, elements: OrbitalElementsRepository
) -> None:
    fake = "f" * 64
    elements.insert_many(
        [
            _make_element(content_hash_source=fake, tle_index=0),
            _make_element(content_hash_source=fake, tle_index=1),
        ]
    )
    report = verify_integrity(snapshots, elements)
    assert len(report.orphan_elements) == 2


# --- I2: continuidad de tle_index ----------------------------------------


def test_detects_index_gap_missing_zero(
    snapshots: TLESnapshotsRepository, elements: OrbitalElementsRepository
) -> None:
    snap = _make_snapshot()
    snapshots.insert(snap)
    elements.insert_many(
        [
            _make_element(content_hash_source=snap.content_hash, tle_index=1),
            _make_element(content_hash_source=snap.content_hash, tle_index=2),
        ]
    )

    report = verify_integrity(snapshots, elements)
    assert report.has_violations is True
    assert len(report.index_gaps) == 1
    assert 0 in report.index_gaps[0].missing_indices


def test_detects_index_gap_in_middle(
    snapshots: TLESnapshotsRepository, elements: OrbitalElementsRepository
) -> None:
    snap = _make_snapshot()
    snapshots.insert(snap)
    elements.insert_many(
        [
            _make_element(content_hash_source=snap.content_hash, tle_index=0),
            _make_element(content_hash_source=snap.content_hash, tle_index=2),
        ]
    )

    report = verify_integrity(snapshots, elements)
    assert report.has_violations is True
    assert 1 in report.index_gaps[0].missing_indices


def test_no_gap_when_indices_contiguous(
    snapshots: TLESnapshotsRepository, elements: OrbitalElementsRepository
) -> None:
    snap = _make_snapshot()
    snapshots.insert(snap)
    elements.insert_many(
        [
            _make_element(content_hash_source=snap.content_hash, tle_index=0),
            _make_element(content_hash_source=snap.content_hash, tle_index=1),
            _make_element(content_hash_source=snap.content_hash, tle_index=2),
        ]
    )
    report = verify_integrity(snapshots, elements)
    assert report.index_gaps == []


def test_index_gap_isolated_per_engine_version(
    snapshots: TLESnapshotsRepository, elements: OrbitalElementsRepository
) -> None:
    """Una versión limpia, otra con gap → solo se reporta la versión con gap."""
    snap = _make_snapshot()
    snapshots.insert(snap)
    elements.insert_many(
        [
            _make_element(
                content_hash_source=snap.content_hash, tle_index=0, engine_version="0.1.0"
            ),
            _make_element(
                content_hash_source=snap.content_hash, tle_index=1, engine_version="0.1.0"
            ),
        ]
    )
    elements.insert_many(
        [
            _make_element(
                content_hash_source=snap.content_hash, tle_index=2, engine_version="0.2.0"
            ),
        ]
    )

    report = verify_integrity(snapshots, elements)
    assert len(report.index_gaps) == 1
    gap = report.index_gaps[0]
    assert gap.engine_version == "0.2.0"
    assert 0 in gap.missing_indices


# --- Escenarios mixtos ----------------------------------------------------


def test_orphan_and_unnormalized_coexist(
    snapshots: TLESnapshotsRepository, elements: OrbitalElementsRepository
) -> None:
    snap1 = _make_snapshot(text="one", dataset="a")
    snap2 = _make_snapshot(text="two", dataset="b")
    snapshots.insert(snap1)
    snapshots.insert(snap2)

    elements.insert_many(
        [_make_element(content_hash_source=snap1.content_hash, tle_index=0)]
    )
    elements.insert_many(
        [_make_element(content_hash_source="0" * 64, tle_index=0)]
    )

    report = verify_integrity(snapshots, elements)
    assert report.has_violations is True
    assert len(report.orphan_elements) == 1
    assert snap2.content_hash in report.unnormalized_snapshots
    assert snap1.content_hash not in report.unnormalized_snapshots


def test_report_is_pydantic_frozen_violations() -> None:
    """OrphanElement e IndexGap son frozen (no se pueden mutar accidentalmente)."""
    from orbital_sentinel.catalog import IndexGap, OrphanElement

    orphan = OrphanElement(
        content_hash_source="a" * 64, tle_index=0, engine_version="0.1.0"
    )
    gap = IndexGap(
        content_hash_source="a" * 64,
        engine_version="0.1.0",
        expected_size=2,
        missing_indices=[1],
    )
    with pytest.raises(Exception):
        orphan.tle_index = 99  # type: ignore[misc]
    with pytest.raises(Exception):
        gap.expected_size = 99  # type: ignore[misc]
