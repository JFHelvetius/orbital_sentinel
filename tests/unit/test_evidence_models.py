"""Tests de los modelos del Evidence Layer (ADR-0029)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from orbital_sentinel.analytics.evidence import (
    EVIDENCE_LAYER_ENGINE_VERSION,
    EVIDENCE_LAYER_SCHEMA_VERSION,
    EVIDENCE_TYPE_MANEUVER,
    DerivedEvidence,
    EvidenceCatalog,
    compute_evidence_id,
)

DERIVED_AT = datetime(2026, 6, 6, 12, 0, tzinfo=timezone.utc)
EPOCH = datetime(2024, 1, 15, 0, 0, tzinfo=timezone.utc)


def _make_evidence(
    *,
    norad: int = 25544,
    epoch: datetime | None = None,
    detector: str = "maneuver_detection_v01",
    detector_event_id: str = "event-id-1",
    evidence_type: str = EVIDENCE_TYPE_MANEUVER,
    engine: str = "0.1.0",
) -> DerivedEvidence:
    ep = epoch or EPOCH
    return DerivedEvidence(
        evidence_id=compute_evidence_id(
            source_detector=detector, object_id=norad,
            detector_event_id=detector_event_id, event_epoch=ep,
            analysis_engine_version=engine,
        ),
        object_id=norad,
        evidence_type=evidence_type,
        source_detector=detector,
        detector_event_id=detector_event_id,
        event_epoch=ep,
        honesty_payload={"detection_method_name": "test"},
        analysis_engine_version=engine,
    )


# --- DerivedEvidence ----------------------------------------------------


def test_evidence_id_is_deterministic() -> None:
    """compute_evidence_id devuelve el mismo hash para los mismos inputs."""
    a = compute_evidence_id(
        source_detector="maneuver_detection_v01", object_id=1,
        detector_event_id="evt", event_epoch=EPOCH,
        analysis_engine_version="0.1.0",
    )
    b = compute_evidence_id(
        source_detector="maneuver_detection_v01", object_id=1,
        detector_event_id="evt", event_epoch=EPOCH,
        analysis_engine_version="0.1.0",
    )
    assert a == b
    assert len(a) == 64  # SHA-256 hex


def test_evidence_id_differs_with_different_inputs() -> None:
    a = compute_evidence_id(
        source_detector="maneuver_detection_v01", object_id=1,
        detector_event_id="evt", event_epoch=EPOCH,
        analysis_engine_version="0.1.0",
    )
    b = compute_evidence_id(
        source_detector="maneuver_detection_v01", object_id=2,
        detector_event_id="evt", event_epoch=EPOCH,
        analysis_engine_version="0.1.0",
    )
    assert a != b


def test_derived_evidence_extra_forbid() -> None:
    ev = _make_evidence()
    with pytest.raises(Exception):
        DerivedEvidence.model_validate(
            {**ev.model_dump(mode="json"), "extra_field": 1}
        )


def test_derived_evidence_is_frozen() -> None:
    ev = _make_evidence()
    with pytest.raises(Exception):
        ev.object_id = 99999  # type: ignore[misc]


def test_derived_evidence_default_is_apparent_not_confirmed_true() -> None:
    ev = _make_evidence()
    assert ev.is_apparent_not_confirmed is True


def test_derived_evidence_schema_version_default() -> None:
    ev = _make_evidence()
    assert ev.schema_version == EVIDENCE_LAYER_SCHEMA_VERSION == "0.1.0"


def test_derived_evidence_rejects_unknown_source_detector() -> None:
    with pytest.raises(Exception):
        DerivedEvidence(
            evidence_id="a" * 64,
            object_id=1,
            evidence_type=EVIDENCE_TYPE_MANEUVER,
            source_detector="not_a_real_detector",  # type: ignore[arg-type]
            detector_event_id="evt",
            event_epoch=EPOCH,
            honesty_payload={},
            analysis_engine_version="0.1.0",
        )


def test_derived_evidence_roundtrips_through_model_dump_validate() -> None:
    ev = _make_evidence()
    raw = ev.model_dump(mode="json")
    re = DerivedEvidence.model_validate(raw)
    assert re.model_dump(mode="json") == raw


# --- EvidenceCatalog ---------------------------------------------------


def test_catalog_from_evidence_empty() -> None:
    cat = EvidenceCatalog.from_evidence([], derived_at=DERIVED_AT)
    assert cat.n_evidence == 0
    assert cat.evidence == []


def test_catalog_orders_by_epoch_then_id() -> None:
    e1 = _make_evidence(epoch=EPOCH + timedelta(days=2), detector_event_id="z")
    e2 = _make_evidence(epoch=EPOCH, detector_event_id="a")
    e3 = _make_evidence(epoch=EPOCH + timedelta(days=1), detector_event_id="m")
    cat = EvidenceCatalog.from_evidence([e1, e2, e3], derived_at=DERIVED_AT)
    epochs = [ev.event_epoch for ev in cat.evidence]
    assert epochs == sorted(epochs)


def test_catalog_deduplicates_by_evidence_id() -> None:
    e = _make_evidence(detector_event_id="evt-dup")
    cat = EvidenceCatalog.from_evidence([e, e, e], derived_at=DERIVED_AT)
    assert cat.n_evidence == 1


def test_catalog_versioning_fields_present() -> None:
    cat = EvidenceCatalog.from_evidence([], derived_at=DERIVED_AT)
    assert cat.schema_version == EVIDENCE_LAYER_SCHEMA_VERSION
    assert cat.catalog_engine_version == EVIDENCE_LAYER_ENGINE_VERSION


def test_catalog_extra_forbid() -> None:
    cat = EvidenceCatalog.from_evidence([], derived_at=DERIVED_AT)
    with pytest.raises(Exception):
        EvidenceCatalog.model_validate(
            {**cat.model_dump(mode="json"), "extra": 1}
        )


def test_catalog_is_frozen() -> None:
    cat = EvidenceCatalog.from_evidence([], derived_at=DERIVED_AT)
    with pytest.raises(Exception):
        cat.n_evidence = 999  # type: ignore[misc]


def test_catalog_roundtrips_through_model_dump_validate() -> None:
    e = _make_evidence()
    cat = EvidenceCatalog.from_evidence([e], derived_at=DERIVED_AT)
    raw = cat.model_dump(mode="json")
    re = EvidenceCatalog.model_validate(raw)
    assert re.model_dump(mode="json") == raw
