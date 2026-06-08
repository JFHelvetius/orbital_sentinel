"""Tests del Investigation Case Layer (ADR-0038)."""

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
from orbital_sentinel.analytics.evidence_chains import build_evidence_chain
from orbital_sentinel.analytics.explanation import build_explanation_context
from orbital_sentinel.analytics.explanation_agent import generate_explanation
from orbital_sentinel.analytics.hypotheses import build_hypothesis_registry
from orbital_sentinel.analytics.investigations import (
    CaseVerificationReport,
    InvestigationCase,
    build_investigation_case,
    verify_investigation_case,
)
from orbital_sentinel.core.errors import InvestigationCaseBuilderError

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
    chain = build_evidence_chain(hr, cr, artifact, agent_input, clock=_fixed_clock)
    return chain, hr, cr, artifact, agent_input, bundle


# --- Build casos ---------------------------------------------


def test_build_investigation_case_empty() -> None:
    chain, hr, cr, art, ai, b = _full_pipeline()
    case = build_investigation_case(
        chain, hypothesis_registry=hr, claim_registry=cr,
        artifact=art, agent_input=ai, bundle=b, clock=_fixed_clock,
    )
    assert case.case_emit_reason == "empty_case"
    assert case.case_id == case.case_signature


def test_build_investigation_case_full() -> None:
    chain, hr, cr, art, ai, b = _full_pipeline(_make_evidence(detector_event_id="x"))
    case = build_investigation_case(
        chain, hypothesis_registry=hr, claim_registry=cr,
        artifact=art, agent_input=ai, bundle=b, clock=_fixed_clock,
    )
    assert case.case_emit_reason == "full_case"
    assert case.referenced_chain_id == chain.chain_id
    assert case.referenced_hypothesis_registry_id == hr.registry_id
    assert case.referenced_claim_registry_id == cr.registry_id
    assert case.referenced_explanation_id == art.explanation_id
    assert case.referenced_agent_input_id == ai.agent_input_id
    assert case.referenced_bundle_id == b.bundle_id


def test_build_investigation_case_label_template() -> None:
    chain, hr, cr, art, ai, b = _full_pipeline(_make_evidence(detector_event_id="x"))
    case = build_investigation_case(
        chain, hypothesis_registry=hr, claim_registry=cr,
        artifact=art, agent_input=ai, bundle=b, clock=_fixed_clock,
    )
    assert "object 25544" in case.case_label
    assert "1 hypothesis(es)" in case.case_label


def test_build_investigation_case_id_alias_of_signature() -> None:
    chain, hr, cr, art, ai, b = _full_pipeline(_make_evidence(detector_event_id="x"))
    case = build_investigation_case(
        chain, hypothesis_registry=hr, claim_registry=cr,
        artifact=art, agent_input=ai, bundle=b, clock=_fixed_clock,
    )
    assert case.case_id == case.case_signature


# --- Determinismo -------------------------------------------


def test_build_investigation_case_deterministic() -> None:
    chain, hr, cr, art, ai, b = _full_pipeline(_make_evidence(detector_event_id="x"))
    c1 = build_investigation_case(
        chain, hypothesis_registry=hr, claim_registry=cr,
        artifact=art, agent_input=ai, bundle=b, clock=_fixed_clock,
    )
    c2 = build_investigation_case(
        chain, hypothesis_registry=hr, claim_registry=cr,
        artifact=art, agent_input=ai, bundle=b, clock=_fixed_clock,
    )
    assert c1.case_id == c2.case_id
    assert c1.model_dump(mode="json") == c2.model_dump(mode="json")


def test_build_investigation_case_clock_only_affects_derived_at() -> None:
    chain, hr, cr, art, ai, b = _full_pipeline(_make_evidence(detector_event_id="x"))

    def early() -> datetime:
        return datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)

    def late() -> datetime:
        return datetime(2027, 1, 1, 0, 0, tzinfo=timezone.utc)
    c1 = build_investigation_case(
        chain, hypothesis_registry=hr, claim_registry=cr,
        artifact=art, agent_input=ai, bundle=b, clock=early,
    )
    c2 = build_investigation_case(
        chain, hypothesis_registry=hr, claim_registry=cr,
        artifact=art, agent_input=ai, bundle=b, clock=late,
    )
    assert c1.case_id == c2.case_id
    assert c1.derived_at != c2.derived_at


# --- Rechazo -----------------------------------------------


def test_build_investigation_case_rejects_swapped_chain() -> None:
    _, hr1, cr1, art1, ai1, b1 = _full_pipeline(_make_evidence(detector_event_id="x"))
    chain2, _, _, _, _, _ = _full_pipeline(_make_evidence(detector_event_id="y"))
    with pytest.raises(InvestigationCaseBuilderError):
        build_investigation_case(
            chain2, hypothesis_registry=hr1, claim_registry=cr1,
            artifact=art1, agent_input=ai1, bundle=b1, clock=_fixed_clock,
        )


# --- Verifier valid path -----------------------------------


def test_verify_investigation_case_valid_empty() -> None:
    chain, hr, cr, art, ai, b = _full_pipeline()
    case = build_investigation_case(
        chain, hypothesis_registry=hr, claim_registry=cr,
        artifact=art, agent_input=ai, bundle=b, clock=_fixed_clock,
    )
    rpt = verify_investigation_case(case, clock=_fixed_clock)
    assert rpt.is_valid is True
    assert rpt.findings == []


def test_verify_investigation_case_valid_full() -> None:
    chain, hr, cr, art, ai, b = _full_pipeline(_make_evidence(detector_event_id="x"))
    case = build_investigation_case(
        chain, hypothesis_registry=hr, claim_registry=cr,
        artifact=art, agent_input=ai, bundle=b, clock=_fixed_clock,
    )
    rpt = verify_investigation_case(case, clock=_fixed_clock)
    assert rpt.is_valid is True
    assert rpt.findings == []
    assert rpt.n_artifacts_verified == 6


def test_verify_all_checks_pass() -> None:
    chain, hr, cr, art, ai, b = _full_pipeline(_make_evidence(detector_event_id="x"))
    case = build_investigation_case(
        chain, hypothesis_registry=hr, claim_registry=cr,
        artifact=art, agent_input=ai, bundle=b, clock=_fixed_clock,
    )
    rpt = verify_investigation_case(case, clock=_fixed_clock)
    assert rpt.case_id_is_alias_of_case_signature is True
    assert rpt.case_signature_recomputes_correctly is True
    assert rpt.case_label_hash_recomputes_correctly is True
    assert rpt.embedded_ids_match_referenced_ids is True
    assert rpt.embedded_chain_consistent_with_others is True
    assert rpt.embedded_artifacts_form_valid_pipeline is True
    assert rpt.case_layer_engine_version_consistent is True


# --- Verifier nunca lanza -----------------------------------


def test_verifier_never_raises() -> None:
    chain, hr, cr, art, ai, b = _full_pipeline(_make_evidence(detector_event_id="x"))
    case = build_investigation_case(
        chain, hypothesis_registry=hr, claim_registry=cr,
        artifact=art, agent_input=ai, bundle=b, clock=_fixed_clock,
    )
    rpt = verify_investigation_case(case, clock=_fixed_clock)
    assert isinstance(rpt, CaseVerificationReport)


# --- Determinismo del reporte -------------------------------


def test_verify_report_reproducible() -> None:
    chain, hr, cr, art, ai, b = _full_pipeline(_make_evidence(detector_event_id="x"))
    case = build_investigation_case(
        chain, hypothesis_registry=hr, claim_registry=cr,
        artifact=art, agent_input=ai, bundle=b, clock=_fixed_clock,
    )
    r1 = verify_investigation_case(case, clock=_fixed_clock)
    r2 = verify_investigation_case(case, clock=_fixed_clock)
    assert r1.model_dump(mode="json") == r2.model_dump(mode="json")


def test_verify_clock_only_affects_verified_at() -> None:
    chain, hr, cr, art, ai, b = _full_pipeline(_make_evidence(detector_event_id="x"))
    case = build_investigation_case(
        chain, hypothesis_registry=hr, claim_registry=cr,
        artifact=art, agent_input=ai, bundle=b, clock=_fixed_clock,
    )

    def early() -> datetime:
        return datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)

    def late() -> datetime:
        return datetime(2027, 1, 1, 0, 0, tzinfo=timezone.utc)
    r1 = verify_investigation_case(case, clock=early)
    r2 = verify_investigation_case(case, clock=late)
    assert r1.verification_hash == r2.verification_hash
    assert r1.verified_at != r2.verified_at


def test_case_is_portable_json_roundtrip() -> None:
    """Property crítica del ADR: un caso es portable end-to-end."""
    chain, hr, cr, art, ai, b = _full_pipeline(_make_evidence(detector_event_id="x"))
    case = build_investigation_case(
        chain, hypothesis_registry=hr, claim_registry=cr,
        artifact=art, agent_input=ai, bundle=b, clock=_fixed_clock,
    )
    dumped = case.model_dump(mode="json")
    rehydrated = InvestigationCase.model_validate(dumped)
    assert rehydrated.case_id == case.case_id
    rpt = verify_investigation_case(rehydrated, clock=_fixed_clock)
    assert rpt.is_valid is True
