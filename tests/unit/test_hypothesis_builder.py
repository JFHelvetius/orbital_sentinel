"""Tests del :func:`build_hypothesis_registry` (ADR-0036)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from orbital_sentinel.analytics.agent_contract import build_agent_input
from orbital_sentinel.analytics.bundles import build_evidence_bundle
from orbital_sentinel.analytics.claims import build_claim_registry
from orbital_sentinel.analytics.evidence import (
    EVIDENCE_TYPE_ANOMALY,
    EVIDENCE_TYPE_MANEUVER,
    DerivedEvidence,
    EvidenceCatalog,
    compute_evidence_id,
)
from orbital_sentinel.analytics.evidence.models import SourceDetector
from orbital_sentinel.analytics.explanation import build_explanation_context
from orbital_sentinel.analytics.explanation_agent import generate_explanation
from orbital_sentinel.analytics.hypotheses import (
    HYPOTHESIS_MODEL_IDENTIFIER_V1,
    build_hypothesis_registry,
)
from orbital_sentinel.core.errors import HypothesisRegistryBuilderError

EPOCH = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)
DERIVED_AT = datetime(2026, 6, 7, 12, 0, tzinfo=timezone.utc)


def _fixed_clock() -> datetime:
    return DERIVED_AT


def _make_evidence(
    *, detector_event_id: str = "evt", days_offset: float = 0.0,
    evidence_type: str = EVIDENCE_TYPE_MANEUVER, object_id: int = 25544,
) -> DerivedEvidence:
    ep = EPOCH + timedelta(days=days_offset)
    detector: SourceDetector = (
        "maneuver_detection_v01" if evidence_type == EVIDENCE_TYPE_MANEUVER
        else "anomaly_detection_v01"
    )
    return DerivedEvidence(
        evidence_id=compute_evidence_id(
            source_detector=detector, object_id=object_id,
            detector_event_id=detector_event_id, event_epoch=ep,
            analysis_engine_version="0.1.0",
        ),
        object_id=object_id,
        evidence_type=evidence_type,
        source_detector=detector,
        detector_event_id=detector_event_id,
        event_epoch=ep,
        honesty_payload={"detection_method_name": "test"},
        analysis_engine_version="0.1.0",
    )


def _full_pipeline(*evs: DerivedEvidence, object_id: int = 25544):  # type: ignore[no-untyped-def]
    catalog = EvidenceCatalog.from_evidence(list(evs), derived_at=DERIVED_AT)
    ctx = build_explanation_context(catalog, object_id=object_id, clock=_fixed_clock)
    bundle = build_evidence_bundle(ctx, catalog, clock=_fixed_clock)
    agent_input = build_agent_input(
        bundle, declared_consumer_class="explanation_agent_v01", clock=_fixed_clock,
    )
    artifact = generate_explanation(agent_input, clock=_fixed_clock)
    claim_registry = build_claim_registry(artifact, agent_input, clock=_fixed_clock)
    return claim_registry, agent_input


# --- Caso vacío ---------------------------------------------


def test_build_hypothesis_registry_empty_claim_registry() -> None:
    cr, ai = _full_pipeline()
    reg = build_hypothesis_registry(cr, ai, clock=_fixed_clock)
    assert reg.n_hypotheses == 0
    assert reg.hypotheses == []
    assert reg.registry_emit_reason == "empty_claim_registry"


# --- Caso con un solo grupo ---------------------------------


def test_build_hypothesis_registry_single_evidence_type_groups_to_one() -> None:
    a = _make_evidence(detector_event_id="a", days_offset=0)
    b = _make_evidence(detector_event_id="b", days_offset=1)
    c = _make_evidence(detector_event_id="c", days_offset=2)
    cr, ai = _full_pipeline(a, b, c)
    reg = build_hypothesis_registry(cr, ai, clock=_fixed_clock)
    assert reg.n_hypotheses == 1
    assert reg.hypotheses[0].grouping_key == f"25544|{EVIDENCE_TYPE_MANEUVER}"
    assert len(reg.hypotheses[0].supporting_claim_ids) == 3


def test_build_hypothesis_registry_multi_evidence_type_groups_to_many() -> None:
    a = _make_evidence(
        detector_event_id="a", days_offset=0, evidence_type=EVIDENCE_TYPE_MANEUVER,
    )
    b = _make_evidence(
        detector_event_id="b", days_offset=1, evidence_type=EVIDENCE_TYPE_ANOMALY,
    )
    cr, ai = _full_pipeline(a, b)
    reg = build_hypothesis_registry(cr, ai, clock=_fixed_clock)
    assert reg.n_hypotheses == 2
    keys = sorted(h.grouping_key for h in reg.hypotheses)
    assert keys == sorted([
        f"25544|{EVIDENCE_TYPE_MANEUVER}",
        f"25544|{EVIDENCE_TYPE_ANOMALY}",
    ])


# --- Invariantes hard ----------------------------------------


def test_build_hypothesis_registry_id_alias_of_hash() -> None:
    a = _make_evidence(detector_event_id="a")
    cr, ai = _full_pipeline(a)
    reg = build_hypothesis_registry(cr, ai, clock=_fixed_clock)
    assert reg.registry_id == reg.registry_hash


def test_build_hypothesis_registry_uses_canonical_model_identifier() -> None:
    a = _make_evidence(detector_event_id="a")
    cr, ai = _full_pipeline(a)
    reg = build_hypothesis_registry(cr, ai, clock=_fixed_clock)
    assert reg.source_model_identifier == HYPOTHESIS_MODEL_IDENTIFIER_V1


def test_build_hypothesis_registry_source_ids_propagated() -> None:
    a = _make_evidence(detector_event_id="a")
    cr, ai = _full_pipeline(a)
    reg = build_hypothesis_registry(cr, ai, clock=_fixed_clock)
    assert reg.source_claim_registry_id == cr.registry_id
    assert reg.source_bundle_id == ai.bundle.bundle_id
    assert reg.source_agent_input_id == ai.agent_input_id


def test_build_hypothesis_registry_forward_index_matches() -> None:
    a = _make_evidence(detector_event_id="a", days_offset=0)
    b = _make_evidence(detector_event_id="b", days_offset=1)
    cr, ai = _full_pipeline(a, b)
    reg = build_hypothesis_registry(cr, ai, clock=_fixed_clock)
    for h in reg.hypotheses:
        assert reg.hypothesis_to_claim_index[h.hypothesis_id] == h.supporting_claim_ids


def test_build_hypothesis_registry_reverse_index_is_transpose() -> None:
    a = _make_evidence(
        detector_event_id="a", days_offset=0, evidence_type=EVIDENCE_TYPE_MANEUVER,
    )
    b = _make_evidence(
        detector_event_id="b", days_offset=1, evidence_type=EVIDENCE_TYPE_ANOMALY,
    )
    cr, ai = _full_pipeline(a, b)
    reg = build_hypothesis_registry(cr, ai, clock=_fixed_clock)
    expected: dict[str, list[str]] = {}
    for h in reg.hypotheses:
        for cid in h.supporting_claim_ids:
            expected.setdefault(cid, []).append(h.hypothesis_id)
    expected_sorted = {k: sorted(v) for k, v in expected.items()}
    actual_sorted = {k: sorted(v) for k, v in reg.claim_to_hypothesis_index.items()}
    assert expected_sorted == actual_sorted


# --- Determinismo -------------------------------------------


def test_build_hypothesis_registry_deterministic() -> None:
    a = _make_evidence(detector_event_id="a")
    cr, ai = _full_pipeline(a)
    r1 = build_hypothesis_registry(cr, ai, clock=_fixed_clock)
    r2 = build_hypothesis_registry(cr, ai, clock=_fixed_clock)
    assert r1.registry_id == r2.registry_id
    assert r1.model_dump(mode="json") == r2.model_dump(mode="json")


def test_build_hypothesis_registry_clock_only_affects_derived_at() -> None:
    a = _make_evidence(detector_event_id="a")
    cr, ai = _full_pipeline(a)

    def early() -> datetime:
        return datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)

    def late() -> datetime:
        return datetime(2027, 1, 1, 0, 0, tzinfo=timezone.utc)
    r1 = build_hypothesis_registry(cr, ai, clock=early)
    r2 = build_hypothesis_registry(cr, ai, clock=late)
    assert r1.registry_id == r2.registry_id
    assert r1.derived_at != r2.derived_at


def test_build_hypothesis_registry_two_pipelines_distinct_ids() -> None:
    cr1, ai1 = _full_pipeline(_make_evidence(detector_event_id="a"))
    cr2, ai2 = _full_pipeline(
        _make_evidence(detector_event_id="a"),
        _make_evidence(detector_event_id="b", days_offset=1),
    )
    r1 = build_hypothesis_registry(cr1, ai1, clock=_fixed_clock)
    r2 = build_hypothesis_registry(cr2, ai2, clock=_fixed_clock)
    assert r1.registry_id != r2.registry_id


# --- Rechazo de inconsistencias -----------------------------


def test_build_hypothesis_registry_rejects_mismatched_bundle() -> None:
    cr1, _ = _full_pipeline(_make_evidence(detector_event_id="a"))
    _, ai2 = _full_pipeline(_make_evidence(detector_event_id="b"))
    with pytest.raises(HypothesisRegistryBuilderError, match="bundle_id"):
        build_hypothesis_registry(cr1, ai2, clock=_fixed_clock)


# --- Label template -----------------------------------------


def test_build_hypothesis_registry_label_follows_template() -> None:
    a = _make_evidence(detector_event_id="a")
    cr, ai = _full_pipeline(a)
    reg = build_hypothesis_registry(cr, ai, clock=_fixed_clock)
    assert reg.hypotheses[0].hypothesis_label.startswith("Object 25544 exhibits ")


def test_build_hypothesis_registry_label_plural_correct() -> None:
    a = _make_evidence(detector_event_id="a", days_offset=0)
    b = _make_evidence(detector_event_id="b", days_offset=1)
    cr, ai = _full_pipeline(a, b)
    reg = build_hypothesis_registry(cr, ai, clock=_fixed_clock)
    label = reg.hypotheses[0].hypothesis_label
    assert "2 claims" in label
