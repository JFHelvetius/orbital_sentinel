"""Tests del repositorio de detecciones persistidas (ADR-0019 v0.4)."""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from orbital_sentinel.analytics.conjunctions import (
    PERSISTED_CONJUNCTION_SCHEMA_VERSION,
    ConjunctionDetection,
    ConjunctionDetectionsRepository,
    analyze_pairwise_conjunction,
    analyze_pairwise_screening,
    compute_detection_hash,
    verify_detections_integrity,
)
from orbital_sentinel.catalog import (
    TLESnapshot,
    TLESnapshotsRepository,
    normalize_snapshot,
)

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "tle"
DERIVED_AT = datetime(2026, 6, 3, 12, 0, tzinfo=timezone.utc)
EPOCH = datetime(2008, 9, 20, 12, 25, 40, tzinfo=timezone.utc)
PERSISTED_AT = datetime(2026, 6, 6, 0, 0, tzinfo=timezone.utc)


def _make_snapshot(name: str) -> TLESnapshot:
    text = (FIXTURES / name).read_text(encoding="ascii")
    encoded = text.encode("ascii")
    return TLESnapshot(
        content_hash=hashlib.sha256(encoded).hexdigest(),
        source="celestrak",
        dataset=name.replace(".txt", ""),
        url=f"https://example/{name}",
        fetched_at=DERIVED_AT,
        raw_text=text,
        n_bytes=len(encoded),
    )


def _iss_element_and_snapshot():
    snap = _make_snapshot("iss_vallado_2008.txt")
    [element] = normalize_snapshot(snap, derived_at=DERIVED_AT)
    return element, snap


def _multi_elements_and_snapshot():
    snap = _make_snapshot("multi_stations.txt")
    elements = normalize_snapshot(snap, derived_at=DERIVED_AT)
    return elements, snap


def _make_analysis_iss_self():
    """ConjunctionAnalysis del ISS contra sí mismo: miss ≈ 0."""
    element, snap = _iss_element_and_snapshot()
    return analyze_pairwise_conjunction(
        element, snap, element, snap,
        window_start=EPOCH,
        window_end=EPOCH + timedelta(minutes=10),
        step_minutes=2.0,
    )


# --- compute_detection_hash ----------------------------------------------


def test_hash_deterministic() -> None:
    analysis = _make_analysis_iss_self()
    h1 = compute_detection_hash(analysis)
    h2 = compute_detection_hash(analysis)
    assert h1 == h2
    assert len(h1) == 64


def test_hash_canonical_ordering_ab_eq_ba() -> None:
    """Swapping (A, B) → (B, A) en el análisis debe producir el mismo hash.

    El sort interno sobre tle_content_hash hace que el orden de los argumentos
    no afecte la identidad de la detección.
    """
    elements, snap = _multi_elements_and_snapshot()
    iss, geo = elements
    ab = analyze_pairwise_conjunction(
        iss, snap, geo, snap,
        window_start=EPOCH,
        window_end=EPOCH + timedelta(hours=2),
        step_minutes=10.0,
    )
    ba = analyze_pairwise_conjunction(
        geo, snap, iss, snap,
        window_start=EPOCH,
        window_end=EPOCH + timedelta(hours=2),
        step_minutes=10.0,
    )
    assert compute_detection_hash(ab) == compute_detection_hash(ba)


def test_hash_changes_with_window() -> None:
    element, snap = _iss_element_and_snapshot()
    a1 = analyze_pairwise_conjunction(
        element, snap, element, snap,
        window_start=EPOCH,
        window_end=EPOCH + timedelta(minutes=10),
        step_minutes=2.0,
    )
    a2 = analyze_pairwise_conjunction(
        element, snap, element, snap,
        window_start=EPOCH,
        window_end=EPOCH + timedelta(minutes=20),
        step_minutes=2.0,
    )
    assert compute_detection_hash(a1) != compute_detection_hash(a2)


def test_hash_changes_with_step() -> None:
    element, snap = _iss_element_and_snapshot()
    a1 = analyze_pairwise_conjunction(
        element, snap, element, snap,
        window_start=EPOCH, window_end=EPOCH + timedelta(minutes=10),
        step_minutes=2.0,
    )
    a2 = analyze_pairwise_conjunction(
        element, snap, element, snap,
        window_start=EPOCH, window_end=EPOCH + timedelta(minutes=10),
        step_minutes=5.0,
    )
    assert compute_detection_hash(a1) != compute_detection_hash(a2)


# --- ConjunctionDetection.from_analysis ----------------------------------


def test_from_analysis_preserves_all_fields() -> None:
    analysis = _make_analysis_iss_self()
    det = ConjunctionDetection.from_analysis(analysis, persisted_at=PERSISTED_AT)
    assert det.norad_a == analysis.norad_a
    assert det.norad_b == analysis.norad_b
    assert det.element_a_tle_content_hash == analysis.element_a_tle_content_hash
    assert det.miss_distance_km == analysis.miss_distance_km
    assert det.tca == analysis.tca
    assert det.analysis_engine_version == analysis.engine_version
    assert det.analysis_schema_version == analysis.schema_version
    assert det.persisted_at == PERSISTED_AT
    assert det.persistence_schema_version == PERSISTED_CONJUNCTION_SCHEMA_VERSION


def test_detection_hash_matches_compute_function() -> None:
    analysis = _make_analysis_iss_self()
    det = ConjunctionDetection.from_analysis(analysis, persisted_at=PERSISTED_AT)
    assert det.detection_content_hash == compute_detection_hash(analysis)


def test_detection_is_frozen() -> None:
    analysis = _make_analysis_iss_self()
    det = ConjunctionDetection.from_analysis(analysis, persisted_at=PERSISTED_AT)
    with pytest.raises(Exception):
        det.miss_distance_km = 999.0  # type: ignore[misc]


# --- ConjunctionDetectionsRepository -------------------------------------


@pytest.fixture
def repo(tmp_path: Path) -> ConjunctionDetectionsRepository:
    return ConjunctionDetectionsRepository(tmp_path / "conjunctions")


def test_count_empty(repo: ConjunctionDetectionsRepository) -> None:
    assert repo.count() == 0


def test_get_missing(repo: ConjunctionDetectionsRepository) -> None:
    assert repo.get("a" * 64) is None


def test_iter_all_empty(repo: ConjunctionDetectionsRepository) -> None:
    assert list(repo.iter_all()) == []


def test_insert_writes_and_returns_true(
    repo: ConjunctionDetectionsRepository,
) -> None:
    analysis = _make_analysis_iss_self()
    det = ConjunctionDetection.from_analysis(analysis, persisted_at=PERSISTED_AT)
    assert repo.insert(det) is True
    assert repo.count() == 1


def test_insert_idempotent_by_content_hash(
    repo: ConjunctionDetectionsRepository,
) -> None:
    """Mismo content_hash → second insert es no-op."""
    analysis = _make_analysis_iss_self()
    det = ConjunctionDetection.from_analysis(analysis, persisted_at=PERSISTED_AT)
    assert repo.insert(det) is True
    assert repo.insert(det) is False
    assert repo.count() == 1


def test_get_returns_inserted(repo: ConjunctionDetectionsRepository) -> None:
    analysis = _make_analysis_iss_self()
    det = ConjunctionDetection.from_analysis(analysis, persisted_at=PERSISTED_AT)
    repo.insert(det)
    fetched = repo.get(det.detection_content_hash)
    assert fetched is not None
    assert fetched.detection_content_hash == det.detection_content_hash
    assert fetched.miss_distance_km == det.miss_distance_km


def test_roundtrip_preserves_all_fields(
    repo: ConjunctionDetectionsRepository,
) -> None:
    analysis = _make_analysis_iss_self()
    det = ConjunctionDetection.from_analysis(analysis, persisted_at=PERSISTED_AT)
    repo.insert(det)
    fetched = repo.get(det.detection_content_hash)
    assert fetched is not None
    assert fetched.model_dump() == det.model_dump()


def test_partitioning_by_year_month(
    repo: ConjunctionDetectionsRepository,
) -> None:
    analysis = _make_analysis_iss_self()
    det = ConjunctionDetection.from_analysis(analysis, persisted_at=PERSISTED_AT)
    repo.insert(det)
    expected = (
        repo.root
        / f"year={PERSISTED_AT.year}"
        / f"month={PERSISTED_AT.month:02d}"
        / f"det_{det.detection_content_hash}.parquet"
    )
    assert expected.is_file()


def test_insert_many_counts_only_new(
    repo: ConjunctionDetectionsRepository,
) -> None:
    element, snap = _iss_element_and_snapshot()
    a1 = analyze_pairwise_conjunction(
        element, snap, element, snap,
        window_start=EPOCH, window_end=EPOCH + timedelta(minutes=10),
        step_minutes=2.0,
    )
    a2 = analyze_pairwise_conjunction(
        element, snap, element, snap,
        window_start=EPOCH, window_end=EPOCH + timedelta(minutes=15),
        step_minutes=2.0,
    )
    det_a = ConjunctionDetection.from_analysis(a1, persisted_at=PERSISTED_AT)
    det_b = ConjunctionDetection.from_analysis(a2, persisted_at=PERSISTED_AT)
    repo.insert(det_a)  # ya existe
    written = repo.insert_many([det_a, det_b])
    assert written == 1
    assert repo.count() == 2


def test_find_by_norad_matches_both_sides(
    repo: ConjunctionDetectionsRepository,
) -> None:
    """find_by_norad debe encontrar detecciones donde NORAD aparezca como A o B."""
    elements, snap = _multi_elements_and_snapshot()
    iss, geo = elements
    a = analyze_pairwise_conjunction(
        iss, snap, geo, snap,
        window_start=EPOCH, window_end=EPOCH + timedelta(hours=2),
        step_minutes=10.0,
    )
    det = ConjunctionDetection.from_analysis(a, persisted_at=PERSISTED_AT)
    repo.insert(det)
    by_iss = repo.find_by_norad(25544)
    by_geo = repo.find_by_norad(99999)
    by_other = repo.find_by_norad(11111)
    assert len(by_iss) == 1
    assert len(by_geo) == 1
    assert by_other == []


def test_find_by_norad_orders_by_miss_ascending(
    repo: ConjunctionDetectionsRepository,
) -> None:
    """Múltiples detecciones del mismo NORAD se devuelven ordenadas por miss."""
    element, snap = _iss_element_and_snapshot()
    # Tres ventanas distintas → tres hashes distintos. Mismo NORAD A.
    for minutes in (10, 15, 20):
        analysis = analyze_pairwise_conjunction(
            element, snap, element, snap,
            window_start=EPOCH, window_end=EPOCH + timedelta(minutes=minutes),
            step_minutes=2.0,
        )
        det = ConjunctionDetection.from_analysis(analysis, persisted_at=PERSISTED_AT)
        repo.insert(det)
    rows = repo.find_by_norad(25544)
    misses = [r.miss_distance_km for r in rows]
    assert misses == sorted(misses)


def test_find_by_norad_respects_limit(
    repo: ConjunctionDetectionsRepository,
) -> None:
    element, snap = _iss_element_and_snapshot()
    for minutes in (10, 15, 20):
        analysis = analyze_pairwise_conjunction(
            element, snap, element, snap,
            window_start=EPOCH, window_end=EPOCH + timedelta(minutes=minutes),
            step_minutes=2.0,
        )
        det = ConjunctionDetection.from_analysis(analysis, persisted_at=PERSISTED_AT)
        repo.insert(det)
    assert repo.count() == 3
    rows = repo.find_by_norad(25544, limit=2)
    assert len(rows) == 2


# --- Integridad cross-layer ---------------------------------------------


def test_integrity_clean_when_snapshots_present(
    tmp_path: Path,
) -> None:
    snap_repo = TLESnapshotsRepository(tmp_path / "raw")
    det_repo = ConjunctionDetectionsRepository(tmp_path / "det")

    # Persistir un snapshot y una detection que lo referencia
    element, snap = _iss_element_and_snapshot()
    snap_repo.insert(snap)
    analysis = analyze_pairwise_conjunction(
        element, snap, element, snap,
        window_start=EPOCH, window_end=EPOCH + timedelta(minutes=10),
        step_minutes=2.0,
    )
    det_repo.insert(
        ConjunctionDetection.from_analysis(analysis, persisted_at=PERSISTED_AT)
    )

    report = verify_detections_integrity(snap_repo, det_repo)
    assert report.has_violations is False
    assert report.n_detections_checked == 1
    assert report.orphan_detections == []


def test_integrity_detects_orphan_after_raw_deleted(
    tmp_path: Path,
) -> None:
    """Borrar manualmente el Parquet de Raw → detection huérfana."""
    snap_repo = TLESnapshotsRepository(tmp_path / "raw")
    det_repo = ConjunctionDetectionsRepository(tmp_path / "det")

    element, snap = _iss_element_and_snapshot()
    snap_repo.insert(snap)
    analysis = analyze_pairwise_conjunction(
        element, snap, element, snap,
        window_start=EPOCH, window_end=EPOCH + timedelta(minutes=10),
        step_minutes=2.0,
    )
    det_repo.insert(
        ConjunctionDetection.from_analysis(analysis, persisted_at=PERSISTED_AT)
    )

    # Borrar el snapshot de Raw a mano (corrupción)
    for p in snap_repo.root.rglob("*.parquet"):
        p.unlink()

    report = verify_detections_integrity(snap_repo, det_repo)
    assert report.has_violations is True
    # A y B son el mismo TLE en este test → 2 orphans (uno por lado)
    assert len(report.orphan_detections) == 2
    assert {o.missing_side for o in report.orphan_detections} == {"a", "b"}


# --- Screening + persistencia integrada --------------------------------


def test_screening_persists_via_repository(
    tmp_path: Path,
) -> None:
    """Pipeline: screening → ConjunctionDetection.from_analysis → repo.insert_many."""
    repo = ConjunctionDetectionsRepository(tmp_path / "det")
    element, snap = _iss_element_and_snapshot()
    result = analyze_pairwise_screening(
        [(element, snap), (element, snap)],
        window_start=EPOCH, window_end=EPOCH + timedelta(minutes=10),
        step_minutes=2.0, threshold_km=1.0,
    )
    assert result.n_detections == 1
    detections = [
        ConjunctionDetection.from_analysis(a, persisted_at=PERSISTED_AT)
        for a in result.detections
    ]
    written = repo.insert_many(detections)
    assert written == 1
    assert repo.count() == 1
