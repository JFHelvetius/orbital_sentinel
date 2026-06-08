"""Tests del Evidence Chain Layer (ADR-0037)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from orbital_sentinel.analytics.agent_contract import build_agent_input
from orbital_sentinel.analytics.bundles import build_evidence_bundle
from orbital_sentinel.analytics.claims import build_claim_registry
from orbital_sentinel.analytics.evidence import (
    EVIDENCE_TYPE_MANEUVER,
    DerivedEvidence,
    EvidenceCatalog,
    compute_evidence_id,
)
from orbital_sentinel.analytics.evidence_chains import (
    CANONICAL_CHAIN_ORDER,
    ChainVerificationReport,
    build_evidence_chain,
    verify_evidence_chain,
)
from orbital_sentinel.analytics.explanation import build_explanation_context
from orbital_sentinel.analytics.explanation_agent import generate_explanation
from orbital_sentinel.analytics.hypotheses import build_hypothesis_registry
from orbital_sentinel.core.errors import EvidenceChainBuilderError

EPOCH = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)
DERIVED_AT = datetime(2026, 6, 7, 12, 0, tzinfo=timezone.utc)


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
    cr = build_claim_registry(artifact, agent_input, clock=_fixed_clock)
    hr = build_hypothesis_registry(cr, agent_input, clock=_fixed_clock)
    return hr, cr, artifact, agent_input


# --- Build empty / full -------------------------------------


def test_build_evidence_chain_empty() -> None:
    hr, cr, art, ai = _full_pipeline()
    chain = build_evidence_chain(hr, cr, art, ai, clock=_fixed_clock)
    assert chain.chain_emit_reason == "empty_chain"
    assert chain.n_nodes == 0
    assert chain.raw_evidence_ids == []


def test_build_evidence_chain_full() -> None:
    hr, cr, art, ai = _full_pipeline(_make_evidence(detector_event_id="x"))
    chain = build_evidence_chain(hr, cr, art, ai, clock=_fixed_clock)
    assert chain.chain_emit_reason == "full_chain"
    assert chain.n_nodes == len(CANONICAL_CHAIN_ORDER)
    assert [n.link_type for n in chain.nodes] == list(CANONICAL_CHAIN_ORDER)


def test_build_evidence_chain_id_alias_of_hash() -> None:
    hr, cr, art, ai = _full_pipeline(_make_evidence(detector_event_id="x"))
    chain = build_evidence_chain(hr, cr, art, ai, clock=_fixed_clock)
    assert chain.chain_id == chain.chain_hash


def test_build_evidence_chain_upstream_links_correct() -> None:
    hr, cr, art, ai = _full_pipeline(_make_evidence(detector_event_id="x"))
    chain = build_evidence_chain(hr, cr, art, ai, clock=_fixed_clock)
    assert chain.nodes[0].upstream_link_id == ""
    for i in range(1, len(chain.nodes)):
        assert chain.nodes[i].upstream_link_id == chain.nodes[i - 1].link_id


def test_build_evidence_chain_links_bind_to_real_ids() -> None:
    hr, cr, art, ai = _full_pipeline(_make_evidence(detector_event_id="x"))
    chain = build_evidence_chain(hr, cr, art, ai, clock=_fixed_clock)
    assert chain.nodes[1].link_id == ai.bundle.bundle_id
    assert chain.nodes[2].link_id == ai.agent_input_id
    assert chain.nodes[3].link_id == art.explanation_id
    assert chain.nodes[4].link_id == cr.registry_id
    assert chain.nodes[5].link_id == hr.registry_id


# --- Reproducibilidad ---------------------------------------


def test_build_evidence_chain_deterministic() -> None:
    hr, cr, art, ai = _full_pipeline(_make_evidence(detector_event_id="x"))
    c1 = build_evidence_chain(hr, cr, art, ai, clock=_fixed_clock)
    c2 = build_evidence_chain(hr, cr, art, ai, clock=_fixed_clock)
    assert c1.chain_id == c2.chain_id
    assert c1.model_dump(mode="json") == c2.model_dump(mode="json")


def test_build_evidence_chain_clock_only_affects_derived_at() -> None:
    hr, cr, art, ai = _full_pipeline(_make_evidence(detector_event_id="x"))

    def early() -> datetime:
        return datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)

    def late() -> datetime:
        return datetime(2027, 1, 1, 0, 0, tzinfo=timezone.utc)
    c1 = build_evidence_chain(hr, cr, art, ai, clock=early)
    c2 = build_evidence_chain(hr, cr, art, ai, clock=late)
    assert c1.chain_id == c2.chain_id
    assert c1.derived_at != c2.derived_at


# --- Rechazo -----------------------------------------------


def test_build_evidence_chain_rejects_swapped_inputs() -> None:
    hr1, cr1, art1, ai1 = _full_pipeline(_make_evidence(detector_event_id="x"))
    _, cr2, _, _ = _full_pipeline(_make_evidence(detector_event_id="y"))
    with pytest.raises(EvidenceChainBuilderError):
        build_evidence_chain(hr1, cr2, art1, ai1, clock=_fixed_clock)


# --- Verifier valid path ------------------------------------


def test_verify_evidence_chain_valid_empty() -> None:
    hr, cr, art, ai = _full_pipeline()
    chain = build_evidence_chain(hr, cr, art, ai, clock=_fixed_clock)
    rpt = verify_evidence_chain(chain, hr, cr, art, ai, clock=_fixed_clock)
    assert rpt.is_valid is True
    assert rpt.findings == []


def test_verify_evidence_chain_valid_full() -> None:
    hr, cr, art, ai = _full_pipeline(_make_evidence(detector_event_id="x"))
    chain = build_evidence_chain(hr, cr, art, ai, clock=_fixed_clock)
    rpt = verify_evidence_chain(chain, hr, cr, art, ai, clock=_fixed_clock)
    assert rpt.is_valid is True
    assert rpt.findings == []
    assert rpt.n_nodes_verified == len(CANONICAL_CHAIN_ORDER)


def test_verify_all_checks_pass() -> None:
    hr, cr, art, ai = _full_pipeline(_make_evidence(detector_event_id="x"))
    chain = build_evidence_chain(hr, cr, art, ai, clock=_fixed_clock)
    rpt = verify_evidence_chain(chain, hr, cr, art, ai, clock=_fixed_clock)
    assert rpt.chain_id_is_alias_of_chain_hash is True
    assert rpt.all_node_hashes_recompute_correctly is True
    assert rpt.chain_order_canonical is True
    assert rpt.all_links_consistent is True
    assert rpt.raw_evidence_ids_match_bundle is True
    assert rpt.chain_layer_engine_version_consistent is True


# --- Swap detection ----------------------------------------


def test_verify_detects_swapped_bundle() -> None:
    hr1, cr1, art1, ai1 = _full_pipeline(_make_evidence(detector_event_id="x"))
    _, _, _, ai2 = _full_pipeline(_make_evidence(detector_event_id="y"))
    chain = build_evidence_chain(hr1, cr1, art1, ai1, clock=_fixed_clock)
    rpt = verify_evidence_chain(chain, hr1, cr1, art1, ai2, clock=_fixed_clock)
    assert rpt.is_valid is False


# --- Verifier nunca lanza -----------------------------------


def test_verifier_never_raises() -> None:
    hr, cr, art, ai = _full_pipeline(_make_evidence(detector_event_id="x"))
    chain = build_evidence_chain(hr, cr, art, ai, clock=_fixed_clock)
    rpt = verify_evidence_chain(chain, hr, cr, art, ai, clock=_fixed_clock)
    assert isinstance(rpt, ChainVerificationReport)


# --- Determinismo del reporte -------------------------------


def test_verify_report_reproducible() -> None:
    hr, cr, art, ai = _full_pipeline(_make_evidence(detector_event_id="x"))
    chain = build_evidence_chain(hr, cr, art, ai, clock=_fixed_clock)
    r1 = verify_evidence_chain(chain, hr, cr, art, ai, clock=_fixed_clock)
    r2 = verify_evidence_chain(chain, hr, cr, art, ai, clock=_fixed_clock)
    assert r1.model_dump(mode="json") == r2.model_dump(mode="json")


def test_verify_clock_only_affects_verified_at() -> None:
    hr, cr, art, ai = _full_pipeline(_make_evidence(detector_event_id="x"))
    chain = build_evidence_chain(hr, cr, art, ai, clock=_fixed_clock)

    def early() -> datetime:
        return datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)

    def late() -> datetime:
        return datetime(2027, 1, 1, 0, 0, tzinfo=timezone.utc)
    r1 = verify_evidence_chain(chain, hr, cr, art, ai, clock=early)
    r2 = verify_evidence_chain(chain, hr, cr, art, ai, clock=late)
    assert r1.is_valid == r2.is_valid
    assert r1.verification_hash == r2.verification_hash
    assert r1.verified_at != r2.verified_at
