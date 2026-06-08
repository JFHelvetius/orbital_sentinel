"""Tests de modelos y helpers del Explanation Layer (ADR-0030)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from orbital_sentinel.analytics.explanation import (
    CANONICAL_DETECTORS_V01,
    EVIDENCE_TYPES_V01,
    EXPLANATION_LAYER_ENGINE_VERSION,
    EXPLANATION_LAYER_SCHEMA_VERSION,
    ExplanationContext,
    ExplanationDetectorSummary,
    ExplanationEvidenceReference,
    ExplanationTimeline,
    ExplanationTimelineEntry,
    compute_context_id,
    compute_payload_hash,
    compute_source_catalog_signature,
)

EPOCH = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)
DERIVED_AT = datetime(2026, 6, 6, 12, 0, tzinfo=timezone.utc)


# --- Helpers: compute_payload_hash ------------------------------------


def test_compute_payload_hash_is_deterministic() -> None:
    a = compute_payload_hash({"x": 1, "y": 2})
    b = compute_payload_hash({"x": 1, "y": 2})
    assert a == b
    assert len(a) == 64


def test_compute_payload_hash_key_order_irrelevant() -> None:
    a = compute_payload_hash({"x": 1, "y": 2})
    b = compute_payload_hash({"y": 2, "x": 1})
    assert a == b


def test_compute_payload_hash_distinct_values_distinct_hash() -> None:
    a = compute_payload_hash({"x": 1})
    b = compute_payload_hash({"x": 2})
    assert a != b


def test_compute_payload_hash_handles_nested_structures() -> None:
    a = compute_payload_hash({"nested": {"b": 2, "a": 1}, "list": [3, 1, 2]})
    b = compute_payload_hash({"list": [3, 1, 2], "nested": {"a": 1, "b": 2}})
    assert a == b


# --- Helpers: compute_source_catalog_signature ------------------------


def test_compute_source_catalog_signature_deterministic() -> None:
    a = compute_source_catalog_signature(["e1", "e2", "e3"])
    b = compute_source_catalog_signature(["e1", "e2", "e3"])
    assert a == b


def test_compute_source_catalog_signature_input_order_irrelevant() -> None:
    a = compute_source_catalog_signature(["e1", "e2", "e3"])
    b = compute_source_catalog_signature(["e3", "e1", "e2"])
    assert a == b


def test_compute_source_catalog_signature_empty_input() -> None:
    h = compute_source_catalog_signature([])
    assert len(h) == 64


# --- Helpers: compute_context_id --------------------------------------


def test_compute_context_id_is_deterministic() -> None:
    a = compute_context_id(
        object_id=25544, explanation_engine_version="0.1.0",
        source_catalog_signature="abc",
    )
    b = compute_context_id(
        object_id=25544, explanation_engine_version="0.1.0",
        source_catalog_signature="abc",
    )
    assert a == b
    assert len(a) == 64


def test_compute_context_id_changes_with_object_id() -> None:
    a = compute_context_id(
        object_id=1, explanation_engine_version="0.1.0",
        source_catalog_signature="sig",
    )
    b = compute_context_id(
        object_id=2, explanation_engine_version="0.1.0",
        source_catalog_signature="sig",
    )
    assert a != b


def test_compute_context_id_changes_with_signature() -> None:
    a = compute_context_id(
        object_id=1, explanation_engine_version="0.1.0",
        source_catalog_signature="A",
    )
    b = compute_context_id(
        object_id=1, explanation_engine_version="0.1.0",
        source_catalog_signature="B",
    )
    assert a != b


# --- Constantes canónicas --------------------------------------------


def test_canonical_detectors_v01_contains_three_detectors_alphabetical() -> None:
    assert CANONICAL_DETECTORS_V01 == (
        "anomaly_detection_v01",
        "conjunction_detection_v01",
        "maneuver_detection_v01",
    )


def test_evidence_types_v01_contains_three_types_alphabetical() -> None:
    assert EVIDENCE_TYPES_V01 == (
        "anomaly_observed",
        "conjunction_detected",
        "maneuver_jump_detected",
    )


def test_explanation_layer_versions_are_v01() -> None:
    assert EXPLANATION_LAYER_SCHEMA_VERSION == "0.1.0"
    assert EXPLANATION_LAYER_ENGINE_VERSION == "0.1.0"


# --- ExplanationEvidenceReference ------------------------------------


def _ref() -> ExplanationEvidenceReference:
    return ExplanationEvidenceReference(
        evidence_id="ev-1",
        object_id=25544,
        event_epoch=EPOCH,
        source_detector="maneuver_detection_v01",
        evidence_type="maneuver_jump_detected",
        detector_event_id="det-evt-1",
        honesty_payload_hash="h" * 64,
        analysis_engine_version="0.1.0",
    )


def test_evidence_reference_extra_forbid() -> None:
    ref = _ref()
    with pytest.raises(Exception):
        ExplanationEvidenceReference.model_validate(
            {**ref.model_dump(mode="json"), "extra": 1}
        )


def test_evidence_reference_is_frozen() -> None:
    ref = _ref()
    with pytest.raises(Exception):
        ref.object_id = 99999  # type: ignore[misc]


def test_evidence_reference_rejects_unknown_source_detector() -> None:
    with pytest.raises(Exception):
        ExplanationEvidenceReference(
            evidence_id="ev-1",
            object_id=25544,
            event_epoch=EPOCH,
            source_detector="not_real",  # type: ignore[arg-type]
            evidence_type="x",
            detector_event_id="d",
            honesty_payload_hash="h" * 64,
            analysis_engine_version="0.1.0",
        )


def test_evidence_reference_roundtrip() -> None:
    ref = _ref()
    raw = ref.model_dump(mode="json")
    re = ExplanationEvidenceReference.model_validate(raw)
    assert re.model_dump(mode="json") == raw


# --- ExplanationDetectorSummary ---------------------------------------


def _summary(*, n: int = 0) -> ExplanationDetectorSummary:
    return ExplanationDetectorSummary(
        source_detector="maneuver_detection_v01",
        n_events=n,
    )


def test_detector_summary_extra_forbid_and_frozen() -> None:
    s = _summary()
    with pytest.raises(Exception):
        ExplanationDetectorSummary.model_validate(
            {**s.model_dump(mode="json"), "extra": 1}
        )
    with pytest.raises(Exception):
        s.n_events = 99  # type: ignore[misc]


def test_detector_summary_n_events_ge_zero() -> None:
    with pytest.raises(Exception):
        ExplanationDetectorSummary(
            source_detector="maneuver_detection_v01",
            n_events=-1,
        )


def test_detector_summary_roundtrip() -> None:
    s = _summary(n=3)
    raw = s.model_dump(mode="json")
    assert ExplanationDetectorSummary.model_validate(raw).model_dump(mode="json") == raw


# --- ExplanationTimelineEntry + ExplanationTimeline -------------------


def _entry() -> ExplanationTimelineEntry:
    return ExplanationTimelineEntry(
        epoch=EPOCH,
        evidence_id="ev-1",
        source_detector="maneuver_detection_v01",
        evidence_type="maneuver_jump_detected",
        honesty_payload_hash="h" * 64,
    )


def test_timeline_entry_extra_forbid_and_frozen() -> None:
    e = _entry()
    with pytest.raises(Exception):
        ExplanationTimelineEntry.model_validate(
            {**e.model_dump(mode="json"), "extra": 1}
        )
    with pytest.raises(Exception):
        e.epoch = EPOCH  # type: ignore[misc]


def test_timeline_extra_forbid() -> None:
    t = ExplanationTimeline(entries=[], n_entries=0)
    with pytest.raises(Exception):
        ExplanationTimeline.model_validate(
            {**t.model_dump(mode="json"), "extra": 1}
        )


def test_timeline_roundtrip() -> None:
    t = ExplanationTimeline(entries=[_entry()], n_entries=1)
    raw = t.model_dump(mode="json")
    assert ExplanationTimeline.model_validate(raw).model_dump(mode="json") == raw


# --- ExplanationContext ----------------------------------------------


def _context_empty() -> ExplanationContext:
    sig = compute_source_catalog_signature([])
    return ExplanationContext(
        object_id=25544,
        context_id=compute_context_id(
            object_id=25544,
            explanation_engine_version=EXPLANATION_LAYER_ENGINE_VERSION,
            source_catalog_signature=sig,
        ),
        source_catalog_signature=sig,
        n_evidence_total=0,
        detector_summaries=[
            ExplanationDetectorSummary(source_detector=det, n_events=0)
            for det in CANONICAL_DETECTORS_V01
        ],
        timeline=ExplanationTimeline(entries=[], n_entries=0),
        evidence_references=[],
        derived_at=DERIVED_AT,
    )


def test_context_extra_forbid() -> None:
    c = _context_empty()
    with pytest.raises(Exception):
        ExplanationContext.model_validate(
            {**c.model_dump(mode="json"), "extra": 1}
        )


def test_context_is_frozen() -> None:
    c = _context_empty()
    with pytest.raises(Exception):
        c.object_id = 99999  # type: ignore[misc]


def test_context_schema_version_default() -> None:
    c = _context_empty()
    assert c.schema_version == EXPLANATION_LAYER_SCHEMA_VERSION == "0.1.0"
    assert c.explanation_engine_version == EXPLANATION_LAYER_ENGINE_VERSION == "0.1.0"


def test_context_roundtrip() -> None:
    c = _context_empty()
    raw = c.model_dump(mode="json")
    assert ExplanationContext.model_validate(raw).model_dump(mode="json") == raw


def test_context_coverage_duration_seconds_ge_zero() -> None:
    """Si se establece, debe ser >= 0 (constraint Pydantic)."""
    sig = compute_source_catalog_signature([])
    with pytest.raises(Exception):
        ExplanationContext(
            object_id=1,
            context_id="x" * 64,
            source_catalog_signature=sig,
            n_evidence_total=0,
            coverage_duration_seconds=-1.0,
            detector_summaries=[],
            timeline=ExplanationTimeline(entries=[], n_entries=0),
            evidence_references=[],
            derived_at=DERIVED_AT,
        )
