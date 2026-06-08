"""Tests del :func:`build_claim_registry` (ADR-0035)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from orbital_sentinel.analytics.agent_contract import build_agent_input
from orbital_sentinel.analytics.bundles import build_evidence_bundle
from orbital_sentinel.analytics.claims import (
    CLAIM_LAYER_ENGINE_VERSION,
    build_claim_registry,
    compute_claim_id,
)
from orbital_sentinel.analytics.evidence import (
    EVIDENCE_TYPE_MANEUVER,
    DerivedEvidence,
    EvidenceCatalog,
    compute_evidence_id,
)
from orbital_sentinel.analytics.explanation import build_explanation_context
from orbital_sentinel.analytics.explanation_agent import generate_explanation
from orbital_sentinel.core.errors import ClaimRegistryBuilderError

EPOCH = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)
DERIVED_AT = datetime(2026, 6, 6, 12, 0, tzinfo=timezone.utc)


def _fixed_clock() -> datetime:
    return DERIVED_AT


def _make_evidence(*, detector_event_id: str = "evt", days_offset: float = 0.0) -> DerivedEvidence:
    ep = EPOCH + timedelta(days=days_offset)
    return DerivedEvidence(
        evidence_id=compute_evidence_id(
            source_detector="maneuver_detection_v01", object_id=25544,
            detector_event_id=detector_event_id, event_epoch=ep,
            analysis_engine_version="0.1.0",
        ),
        object_id=25544,
        evidence_type=EVIDENCE_TYPE_MANEUVER,
        source_detector="maneuver_detection_v01",
        detector_event_id=detector_event_id,
        event_epoch=ep,
        honesty_payload={"detection_method_name": "test"},
        analysis_engine_version="0.1.0",
    )


def _full_pipeline(*evs: DerivedEvidence):  # type: ignore[no-untyped-def]
    catalog = EvidenceCatalog.from_evidence(list(evs), derived_at=DERIVED_AT)
    ctx = build_explanation_context(catalog, object_id=25544, clock=_fixed_clock)
    bundle = build_evidence_bundle(ctx, catalog, clock=_fixed_clock)
    agent_input = build_agent_input(
        bundle, declared_consumer_class="explanation_agent_v01", clock=_fixed_clock,
    )
    artifact = generate_explanation(agent_input, clock=_fixed_clock)
    return artifact, agent_input


# --- Caso empty bundle --------------------------------------


def test_build_registry_empty_bundle() -> None:
    art, ai = _full_pipeline()
    reg = build_claim_registry(art, ai, clock=_fixed_clock)
    assert reg.n_claims == 0
    assert reg.claims == []
    assert reg.claim_to_evidence_index == {}
    assert reg.evidence_to_claim_index == {}
    assert reg.registry_emit_reason == "empty_bundle"


# --- Caso con evidencia ------------------------------------


def test_build_registry_single_evidence() -> None:
    art, ai = _full_pipeline(_make_evidence(detector_event_id="x"))
    reg = build_claim_registry(art, ai, clock=_fixed_clock)
    assert reg.n_claims == 1
    assert len(reg.claims) == 1
    claim = reg.claims[0]
    assert claim.claim_index == 0
    assert len(claim.supporting_evidence_ids) == 1
    assert reg.registry_emit_reason == "evidence_bundle"


def test_build_registry_multi_evidence() -> None:
    a = _make_evidence(detector_event_id="a", days_offset=0)
    b = _make_evidence(detector_event_id="b", days_offset=1)
    c = _make_evidence(detector_event_id="c", days_offset=2)
    art, ai = _full_pipeline(a, b, c)
    reg = build_claim_registry(art, ai, clock=_fixed_clock)
    assert reg.n_claims == 3
    indices = [c.claim_index for c in reg.claims]
    assert indices == [0, 1, 2]


def test_build_registry_id_alias_of_hash() -> None:
    """Hard invariant CLAIM-008."""
    art, ai = _full_pipeline(_make_evidence(detector_event_id="x"))
    reg = build_claim_registry(art, ai, clock=_fixed_clock)
    assert reg.registry_id == reg.registry_hash


def test_build_registry_claim_id_recomputes_correctly() -> None:
    art, ai = _full_pipeline(_make_evidence(detector_event_id="x"))
    reg = build_claim_registry(art, ai, clock=_fixed_clock)
    for claim in reg.claims:
        expected = compute_claim_id(
            source_explanation_id=claim.source_explanation_id,
            claim_index=claim.claim_index,
            supporting_evidence_ids=claim.supporting_evidence_ids,
            claim_text=claim.claim_text,
            claim_layer_engine_version=CLAIM_LAYER_ENGINE_VERSION,
        )
        assert claim.claim_id == expected


def test_build_registry_claim_text_matches_explanation_line() -> None:
    art, ai = _full_pipeline(_make_evidence(detector_event_id="x"))
    reg = build_claim_registry(art, ai, clock=_fixed_clock)
    lines = [ln for ln in art.explanation_text.split("\n") if ln.strip()]
    for claim, expected_text in zip(reg.claims, lines, strict=True):
        assert claim.claim_text == expected_text


def test_build_registry_forward_index_matches_claims() -> None:
    a = _make_evidence(detector_event_id="a", days_offset=0)
    b = _make_evidence(detector_event_id="b", days_offset=1)
    art, ai = _full_pipeline(a, b)
    reg = build_claim_registry(art, ai, clock=_fixed_clock)
    for claim in reg.claims:
        assert reg.claim_to_evidence_index[claim.claim_id] == claim.supporting_evidence_ids


def test_build_registry_reverse_index_is_transpose() -> None:
    a = _make_evidence(detector_event_id="a", days_offset=0)
    b = _make_evidence(detector_event_id="b", days_offset=1)
    art, ai = _full_pipeline(a, b)
    reg = build_claim_registry(art, ai, clock=_fixed_clock)
    # Construir traspuesta esperada
    expected: dict[str, list[str]] = {}
    for c in reg.claims:
        for ev in c.supporting_evidence_ids:
            expected.setdefault(ev, []).append(c.claim_id)
    expected_sorted = {k: sorted(v) for k, v in expected.items()}
    actual_sorted = {k: sorted(v) for k, v in reg.evidence_to_claim_index.items()}
    assert expected_sorted == actual_sorted


def test_build_registry_source_ids_propagated() -> None:
    art, ai = _full_pipeline(_make_evidence(detector_event_id="x"))
    reg = build_claim_registry(art, ai, clock=_fixed_clock)
    assert reg.source_explanation_id == art.explanation_id
    assert reg.source_bundle_id == ai.bundle.bundle_id
    assert reg.source_agent_input_id == ai.agent_input_id
    assert reg.source_model_identifier == "template_explanation_v01"


# --- Determinismo ------------------------------------------


def test_build_registry_deterministic_across_runs() -> None:
    art, ai = _full_pipeline(_make_evidence(detector_event_id="x"))
    a = build_claim_registry(art, ai, clock=_fixed_clock)
    b = build_claim_registry(art, ai, clock=_fixed_clock)
    assert a.registry_id == b.registry_id
    assert a.model_dump(mode="json") == b.model_dump(mode="json")


def test_build_registry_clock_only_affects_derived_at() -> None:
    art, ai = _full_pipeline(_make_evidence(detector_event_id="x"))

    def early() -> datetime:
        return datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)

    def late() -> datetime:
        return datetime(2027, 1, 1, 0, 0, tzinfo=timezone.utc)
    a = build_claim_registry(art, ai, clock=early)
    b = build_claim_registry(art, ai, clock=late)
    assert a.registry_id == b.registry_id
    assert a.derived_at != b.derived_at


def test_build_registry_two_explanations_distinct_ids() -> None:
    art1, ai1 = _full_pipeline(_make_evidence(detector_event_id="a"))
    art2, ai2 = _full_pipeline(
        _make_evidence(detector_event_id="a"),
        _make_evidence(detector_event_id="b", days_offset=1),
    )
    reg1 = build_claim_registry(art1, ai1, clock=_fixed_clock)
    reg2 = build_claim_registry(art2, ai2, clock=_fixed_clock)
    assert reg1.registry_id != reg2.registry_id


# --- Rechazo de inconsistencias ---------------------------


def test_build_registry_rejects_mismatched_source_bundle() -> None:
    art1, ai1 = _full_pipeline(_make_evidence(detector_event_id="x"))
    art2, ai2 = _full_pipeline(_make_evidence(detector_event_id="y"))
    # Pasar artifact de un pipeline + agent_input de otro
    with pytest.raises(ClaimRegistryBuilderError, match="source_bundle_id"):
        build_claim_registry(art1, ai2, clock=_fixed_clock)


def test_build_registry_rejects_unsupported_model_identifier() -> None:
    """Artifact con model_identifier no soportado por v0.1."""
    art, ai = _full_pipeline(_make_evidence(detector_event_id="x"))
    # Mutar el model_identifier mediante reconstrucción
    from orbital_sentinel.analytics.explanation_agent.models import (
        ExplanationGenerationMetadata,
    )
    new_metadata = ExplanationGenerationMetadata(
        model_identifier="unknown_model_vX",
        generation_method=art.generation_metadata.generation_method,
        prompt_hash=art.generation_metadata.prompt_hash,
        n_evidence_processed=art.generation_metadata.n_evidence_processed,
    )
    tampered = art.model_copy(update={"generation_metadata": new_metadata})
    with pytest.raises(ClaimRegistryBuilderError, match="Unsupported"):
        build_claim_registry(tampered, ai, clock=_fixed_clock)


# --- Indices ordenados deterministically -----------------


def test_build_registry_forward_index_keys_sorted() -> None:
    a = _make_evidence(detector_event_id="a", days_offset=0)
    b = _make_evidence(detector_event_id="b", days_offset=1)
    c = _make_evidence(detector_event_id="c", days_offset=2)
    art, ai = _full_pipeline(a, b, c)
    reg = build_claim_registry(art, ai, clock=_fixed_clock)
    keys = list(reg.claim_to_evidence_index.keys())
    assert keys == sorted(keys)


def test_build_registry_reverse_index_keys_sorted() -> None:
    a = _make_evidence(detector_event_id="a", days_offset=0)
    b = _make_evidence(detector_event_id="b", days_offset=1)
    art, ai = _full_pipeline(a, b)
    reg = build_claim_registry(art, ai, clock=_fixed_clock)
    keys = list(reg.evidence_to_claim_index.keys())
    assert keys == sorted(keys)


# --- Cobertura: 1:1 claim ↔ evidence en v0.1 -------------


def test_build_registry_each_claim_has_exactly_one_supporting_evidence_in_v01() -> None:
    a = _make_evidence(detector_event_id="a", days_offset=0)
    b = _make_evidence(detector_event_id="b", days_offset=1)
    art, ai = _full_pipeline(a, b)
    reg = build_claim_registry(art, ai, clock=_fixed_clock)
    for claim in reg.claims:
        assert len(claim.supporting_evidence_ids) == 1


def test_build_registry_n_claims_matches_referenced_evidence_ids() -> None:
    a = _make_evidence(detector_event_id="a", days_offset=0)
    b = _make_evidence(detector_event_id="b", days_offset=1)
    c = _make_evidence(detector_event_id="c", days_offset=2)
    art, ai = _full_pipeline(a, b, c)
    reg = build_claim_registry(art, ai, clock=_fixed_clock)
    assert reg.n_claims == len(art.referenced_evidence_ids)


def test_build_registry_claim_text_lines_start_with_evidence() -> None:
    a = _make_evidence(detector_event_id="a", days_offset=0)
    art, ai = _full_pipeline(a)
    reg = build_claim_registry(art, ai, clock=_fixed_clock)
    for claim in reg.claims:
        assert claim.claim_text.startswith("Evidence")
