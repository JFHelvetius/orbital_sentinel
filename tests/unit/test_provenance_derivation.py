"""Tests de derivación automática de ExternalSourceRegistry (ADR-0042)."""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from orbital_sentinel.analytics.agent_contract import build_agent_input
from orbital_sentinel.analytics.bundles import build_evidence_bundle
from orbital_sentinel.analytics.evidence import (
    CONSUMED_SOURCE_HASHES_KEY,
    EVIDENCE_TYPE_MANEUVER,
    DerivedEvidence,
    EvidenceCatalog,
    compute_evidence_id,
)
from orbital_sentinel.analytics.explanation import build_explanation_context
from orbital_sentinel.analytics.external_sources import (
    derive_external_source_registry_for_bundle,
    verify_external_source_registry,
)
from orbital_sentinel.analytics.external_sources.provenance import _map_provider
from orbital_sentinel.catalog.orbital_elements import OrbitalElementsRepository
from orbital_sentinel.catalog.tle_snapshots import TLESnapshot, TLESnapshotsRepository
from orbital_sentinel.core.errors import ExternalSourceRegistryBuilderError
from tests.unit.test_maneuver_series import make_element

EPOCH = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)
DERIVED_AT = datetime(2026, 6, 7, 12, 0, tzinfo=timezone.utc)
FETCHED_AT = datetime(2024, 1, 1, 6, 0, tzinfo=timezone.utc)


def _clock() -> datetime:
    return DERIVED_AT


def _make_snapshot(
    *, source: str = "celestrak", dataset: str = "active",
    content_hash: str | None = None, raw_text: str = "DUMMY_TLE_PAYLOAD",
) -> TLESnapshot:
    if content_hash is None:
        content_hash = hashlib.sha256(raw_text.encode()).hexdigest()
    return TLESnapshot(
        content_hash=content_hash,
        source=source,
        dataset=dataset,
        url=f"https://example/{dataset}",
        fetched_at=FETCHED_AT,
        raw_text=raw_text,
        n_bytes=len(raw_text.encode()),
    )


def _make_evidence(
    *, object_id: int = 25544, detector_event_id: str = "evt",
    days_offset: float = 0.0, consumed: list[str] | None = None,
) -> DerivedEvidence:
    ep = EPOCH + timedelta(days=days_offset)
    honesty: dict = {"detection_method_name": "test"}
    if consumed is not None:
        # ADR-0043: provenance por-evidencia declarada en honesty_payload.
        honesty[CONSUMED_SOURCE_HASHES_KEY] = list(consumed)
    return DerivedEvidence(
        evidence_id=compute_evidence_id(
            source_detector="maneuver_detection_v01", object_id=object_id,
            detector_event_id=detector_event_id, event_epoch=ep,
            analysis_engine_version="0.1.0",
        ),
        object_id=object_id,
        evidence_type=EVIDENCE_TYPE_MANEUVER,
        source_detector="maneuver_detection_v01",
        detector_event_id=detector_event_id,
        event_epoch=ep,
        honesty_payload=honesty,
        analysis_engine_version="0.1.0",
    )


def _build_bundle(*evs: DerivedEvidence, object_id: int = 25544):  # type: ignore[no-untyped-def]
    catalog = EvidenceCatalog.from_evidence(list(evs), derived_at=DERIVED_AT)
    ctx = build_explanation_context(catalog, object_id=object_id, clock=_clock)
    return build_evidence_bundle(ctx, catalog, clock=_clock)


def _setup_repos(tmp_path: Path):  # type: ignore[no-untyped-def]
    tle_repo = TLESnapshotsRepository(tmp_path / "raw" / "tle_snapshots")
    elem_repo = OrbitalElementsRepository(tmp_path / "normalized" / "orbital_elements")
    return tle_repo, elem_repo


# --- Provider mapping --------------------------------------------------


def test_map_provider_known_sources() -> None:
    assert _map_provider("celestrak") == "celestrak"
    assert _map_provider("space_track") == "space_track"
    assert _map_provider("norad") == "norad"
    assert _map_provider("test_fixture") == "test_fixture"


def test_map_provider_unknown_falls_back_to_manual() -> None:
    assert _map_provider("some_unknown_provider") == "manual_offline_import"
    assert _map_provider("") == "manual_offline_import"


# --- Derivation: empty path -----------------------------------------


def test_derive_empty_bundle_returns_empty_registry(tmp_path: Path) -> None:
    tle_repo, elem_repo = _setup_repos(tmp_path)
    bundle = _build_bundle()
    reg = derive_external_source_registry_for_bundle(
        bundle, tle_snapshots_repo=tle_repo, orbital_elements_repo=elem_repo,
        clock=_clock,
    )
    assert reg.n_records == 0
    assert reg.registry_emit_reason == "empty_registry"
    assert reg.source_bundle_id == bundle.bundle_id


# --- Derivation: single snapshot single object -----------------------


def test_derive_single_snapshot_single_object(tmp_path: Path) -> None:
    tle_repo, elem_repo = _setup_repos(tmp_path)
    snap = _make_snapshot(content_hash="a" * 64)
    tle_repo.insert(snap)
    elem = make_element(
        norad=25544, days_offset=0.0,
        content_hash_source="a" * 64, tle_index=0,
        tle_hash="1" * 64,
    )
    elem_repo.insert_many([elem])

    bundle = _build_bundle(_make_evidence(detector_event_id="x"))
    reg = derive_external_source_registry_for_bundle(
        bundle, tle_snapshots_repo=tle_repo, orbital_elements_repo=elem_repo,
        clock=_clock,
    )
    assert reg.n_records == 1
    assert reg.source_bundle_id == bundle.bundle_id
    assert reg.records[0].source_provider == "celestrak"


def test_derive_single_snapshot_passes_verifier(tmp_path: Path) -> None:
    tle_repo, elem_repo = _setup_repos(tmp_path)
    snap = _make_snapshot(content_hash="b" * 64)
    tle_repo.insert(snap)
    elem = make_element(
        norad=25544, content_hash_source="b" * 64, tle_index=0,
        tle_hash="2" * 64,
    )
    elem_repo.insert_many([elem])

    bundle = _build_bundle(_make_evidence(detector_event_id="x"))
    reg = derive_external_source_registry_for_bundle(
        bundle, tle_snapshots_repo=tle_repo, orbital_elements_repo=elem_repo,
        clock=_clock,
    )
    rpt = verify_external_source_registry(reg, bundle, clock=_clock)
    assert rpt.is_valid is True
    assert rpt.findings == []


# --- Derivation: multiple snapshots same object ----------------------


def test_derive_multiple_snapshots_same_object(tmp_path: Path) -> None:
    tle_repo, elem_repo = _setup_repos(tmp_path)
    for i, ch in enumerate(["c" * 64, "d" * 64, "e" * 64]):
        tle_repo.insert(_make_snapshot(content_hash=ch, raw_text=f"PAYLOAD_{i}"))
        elem = make_element(
            norad=25544, days_offset=float(i),
            content_hash_source=ch, tle_index=0,
            tle_hash=f"{i:064x}",
        )
        elem_repo.insert_many([elem])

    bundle = _build_bundle(_make_evidence(detector_event_id="x"))
    reg = derive_external_source_registry_for_bundle(
        bundle, tle_snapshots_repo=tle_repo, orbital_elements_repo=elem_repo,
        clock=_clock,
    )
    assert reg.n_records == 3
    rpt = verify_external_source_registry(reg, bundle, clock=_clock)
    assert rpt.is_valid is True


# --- Derivation: multiple objects multiple snapshots ----------------


def test_derive_multiple_objects(tmp_path: Path) -> None:
    tle_repo, elem_repo = _setup_repos(tmp_path)
    # NORAD 25544 → snapshot A
    tle_repo.insert(_make_snapshot(content_hash="1" * 64, raw_text="OBJ_A"))
    elem_repo.insert_many([
        make_element(
            norad=25544, content_hash_source="1" * 64, tle_index=0,
            tle_hash="a" * 64,
        ),
    ])
    # NORAD 99999 → snapshot B
    tle_repo.insert(_make_snapshot(content_hash="2" * 64, raw_text="OBJ_B"))
    elem_repo.insert_many([
        make_element(
            norad=99999, content_hash_source="2" * 64, tle_index=0,
            tle_hash="b" * 64,
        ),
    ])

    ev_a = _make_evidence(object_id=25544, detector_event_id="a")
    bundle = _build_bundle(ev_a, object_id=25544)
    reg = derive_external_source_registry_for_bundle(
        bundle, tle_snapshots_repo=tle_repo, orbital_elements_repo=elem_repo,
        clock=_clock,
    )
    # Sólo NORAD 25544 está en el bundle → 1 record
    assert reg.n_records == 1
    rpt = verify_external_source_registry(reg, bundle, clock=_clock)
    assert rpt.is_valid is True


# --- Determinismo --------------------------------------------------


def test_derive_deterministic(tmp_path: Path) -> None:
    tle_repo, elem_repo = _setup_repos(tmp_path)
    tle_repo.insert(_make_snapshot(content_hash="f" * 64))
    elem_repo.insert_many([
        make_element(
            norad=25544, content_hash_source="f" * 64, tle_index=0,
            tle_hash="3" * 64,
        ),
    ])
    bundle = _build_bundle(_make_evidence(detector_event_id="x"))
    r1 = derive_external_source_registry_for_bundle(
        bundle, tle_snapshots_repo=tle_repo, orbital_elements_repo=elem_repo,
        clock=_clock,
    )
    r2 = derive_external_source_registry_for_bundle(
        bundle, tle_snapshots_repo=tle_repo, orbital_elements_repo=elem_repo,
        clock=_clock,
    )
    assert r1.registry_id == r2.registry_id
    assert r1.model_dump(mode="json") == r2.model_dump(mode="json")


def test_derive_clock_only_affects_derived_at(tmp_path: Path) -> None:
    tle_repo, elem_repo = _setup_repos(tmp_path)
    tle_repo.insert(_make_snapshot(content_hash="9" * 64))
    elem_repo.insert_many([
        make_element(
            norad=25544, content_hash_source="9" * 64, tle_index=0,
            tle_hash="7" * 64,
        ),
    ])
    bundle = _build_bundle(_make_evidence(detector_event_id="x"))

    def early() -> datetime:
        return datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)

    def late() -> datetime:
        return datetime(2027, 1, 1, 0, 0, tzinfo=timezone.utc)
    r1 = derive_external_source_registry_for_bundle(
        bundle, tle_snapshots_repo=tle_repo, orbital_elements_repo=elem_repo,
        clock=early,
    )
    r2 = derive_external_source_registry_for_bundle(
        bundle, tle_snapshots_repo=tle_repo, orbital_elements_repo=elem_repo,
        clock=late,
    )
    assert r1.registry_id == r2.registry_id
    assert r1.derived_at != r2.derived_at


# --- Compatibilidad con agent_input + full chain -----------------


def test_derive_works_in_full_pipeline(tmp_path: Path) -> None:
    tle_repo, elem_repo = _setup_repos(tmp_path)
    tle_repo.insert(_make_snapshot(content_hash="0" * 64))
    elem_repo.insert_many([
        make_element(
            norad=25544, content_hash_source="0" * 64, tle_index=0,
            tle_hash="8" * 64,
        ),
    ])
    bundle = _build_bundle(_make_evidence(detector_event_id="x"))
    agent_input = build_agent_input(
        bundle, declared_consumer_class="explanation_agent_v01", clock=_clock,
    )
    # El bundle dentro de agent_input es el mismo bundle
    assert agent_input.bundle.bundle_id == bundle.bundle_id
    # Derive sobre el bundle dentro del agent input también funciona
    reg = derive_external_source_registry_for_bundle(
        agent_input.bundle,
        tle_snapshots_repo=tle_repo, orbital_elements_repo=elem_repo,
        clock=_clock,
    )
    rpt = verify_external_source_registry(reg, agent_input.bundle, clock=_clock)
    assert rpt.is_valid is True


# --- Degraded mode: snapshot missing in Raw ---------------------


def test_derive_with_missing_raw_snapshot_raises(tmp_path: Path) -> None:
    """Si el Normalized referencia un content_hash_source que no existe en Raw,
    no se puede emitir record para ese hash. Sin records pero con evidencia
    en bundle → builder rechaza."""
    tle_repo, elem_repo = _setup_repos(tmp_path)
    # NO se inserta snapshot
    elem_repo.insert_many([
        make_element(
            norad=25544, content_hash_source="abcd" * 16, tle_index=0,
            tle_hash="z" * 64,
        ),
    ])
    bundle = _build_bundle(_make_evidence(detector_event_id="x"))
    with pytest.raises(
        ExternalSourceRegistryBuilderError, match="no source records",
    ):
        derive_external_source_registry_for_bundle(
            bundle, tle_snapshots_repo=tle_repo, orbital_elements_repo=elem_repo,
            clock=_clock,
        )


# --- Determinismo crítico ante reorden de inserts -------------


# --- Granularidad por-evidencia (ADR-0043) -------------------------


def _insert_object_snapshots(tle_repo, elem_repo, hashes: list[str]) -> None:  # type: ignore[no-untyped-def]
    for i, ch in enumerate(hashes):
        tle_repo.insert(_make_snapshot(content_hash=ch, raw_text=f"PAYLOAD_{ch}"))
        elem_repo.insert_many([
            make_element(
                norad=25544, days_offset=float(i),
                content_hash_source=ch, tle_index=0, tle_hash=f"{i:064x}",
            ),
        ])


def test_derive_per_evidence_uses_declared_subset(tmp_path: Path) -> None:
    """Evidencia que declara consumed_source_hashes ⊂ hashes-del-objeto:
    el registry solo incluye los records consumidos, NO todos los del objeto."""
    tle_repo, elem_repo = _setup_repos(tmp_path)
    h1, h2, h3 = "c" * 64, "d" * 64, "e" * 64
    _insert_object_snapshots(tle_repo, elem_repo, [h1, h2, h3])

    # La evidencia consumió solo h1 y h3 (no h2).
    ev = _make_evidence(detector_event_id="x", consumed=[h1, h3])
    bundle = _build_bundle(ev)
    reg = derive_external_source_registry_for_bundle(
        bundle, tle_snapshots_repo=tle_repo, orbital_elements_repo=elem_repo,
        clock=_clock,
    )
    # Precisión: 2 records (h1, h3), NO 3 — h2 no sustenta esta evidencia.
    assert reg.n_records == 2
    payload_hashes = {r.source_payload_hash for r in reg.records}
    assert payload_hashes == {h1, h3}
    assert h2 not in payload_hashes
    rpt = verify_external_source_registry(reg, bundle, clock=_clock)
    assert rpt.is_valid is True


def test_derive_fallback_per_object_when_no_consumed(tmp_path: Path) -> None:
    """Evidencia SIN consumed_source_hashes (pre-0043) cae al path por-objeto
    de ADR-0042: incluye los 3 records del objeto. Backward-compatible."""
    tle_repo, elem_repo = _setup_repos(tmp_path)
    _insert_object_snapshots(tle_repo, elem_repo, ["c" * 64, "d" * 64, "e" * 64])
    ev = _make_evidence(detector_event_id="x")  # sin consumed
    bundle = _build_bundle(ev)
    reg = derive_external_source_registry_for_bundle(
        bundle, tle_snapshots_repo=tle_repo, orbital_elements_repo=elem_repo,
        clock=_clock,
    )
    assert reg.n_records == 3
    rpt = verify_external_source_registry(reg, bundle, clock=_clock)
    assert rpt.is_valid is True


def test_derive_per_evidence_independent_of_orbital_elements_repo(tmp_path: Path) -> None:
    """Con consumed declarado, la derivación va directa a Raw y no depende del
    repo de elements (no necesita find_all_by_norad_id)."""
    tle_repo, _elem_repo = _setup_repos(tmp_path)
    h1 = "c" * 64
    tle_repo.insert(_make_snapshot(content_hash=h1, raw_text="P1"))
    # elem_repo deliberadamente vacío.
    empty_elem_repo = OrbitalElementsRepository(tmp_path / "empty" / "orbital_elements")
    ev = _make_evidence(detector_event_id="x", consumed=[h1])
    bundle = _build_bundle(ev)
    reg = derive_external_source_registry_for_bundle(
        bundle, tle_snapshots_repo=tle_repo, orbital_elements_repo=empty_elem_repo,
        clock=_clock,
    )
    assert reg.n_records == 1
    assert reg.records[0].source_payload_hash == h1


def test_derive_independent_of_insertion_order(tmp_path: Path) -> None:
    """Insertar snapshots/elements en orden distinto NO cambia el registry_id."""
    tle_repo_a, elem_repo_a = _setup_repos(tmp_path / "a")
    tle_repo_b, elem_repo_b = _setup_repos(tmp_path / "b")
    snap1 = _make_snapshot(content_hash="aa" * 32, raw_text="P1")
    snap2 = _make_snapshot(content_hash="bb" * 32, raw_text="P2")
    elem1 = make_element(
        norad=25544, days_offset=0.0, content_hash_source="aa" * 32,
        tle_index=0, tle_hash="11" * 32,
    )
    elem2 = make_element(
        norad=25544, days_offset=1.0, content_hash_source="bb" * 32,
        tle_index=0, tle_hash="22" * 32,
    )
    # Orden 1: snap1 then snap2
    tle_repo_a.insert(snap1)
    tle_repo_a.insert(snap2)
    elem_repo_a.insert_many([elem1])
    elem_repo_a.insert_many([elem2])
    # Orden 2: snap2 then snap1
    tle_repo_b.insert(snap2)
    tle_repo_b.insert(snap1)
    elem_repo_b.insert_many([elem2])
    elem_repo_b.insert_many([elem1])

    bundle = _build_bundle(_make_evidence(detector_event_id="x"))
    r1 = derive_external_source_registry_for_bundle(
        bundle, tle_snapshots_repo=tle_repo_a, orbital_elements_repo=elem_repo_a,
        clock=_clock,
    )
    r2 = derive_external_source_registry_for_bundle(
        bundle, tle_snapshots_repo=tle_repo_b, orbital_elements_repo=elem_repo_b,
        clock=_clock,
    )
    assert r1.registry_id == r2.registry_id
