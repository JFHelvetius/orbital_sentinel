"""Tests del :func:`verify_hypothesis_registry` (ADR-0036)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from orbital_sentinel.analytics.agent_contract import build_agent_input
from orbital_sentinel.analytics.bundles import build_evidence_bundle
from orbital_sentinel.analytics.claims import build_claim_registry
from orbital_sentinel.analytics.evidence import (
    EVIDENCE_TYPE_MANEUVER,
    DerivedEvidence,
    EvidenceCatalog,
    compute_evidence_id,
)
from orbital_sentinel.analytics.explanation import build_explanation_context
from orbital_sentinel.analytics.explanation_agent import generate_explanation
from orbital_sentinel.analytics.hypotheses import (
    HypothesisVerificationReport,
    build_hypothesis_registry,
    verify_hypothesis_registry,
)

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
    claim_registry = build_claim_registry(artifact, agent_input, clock=_fixed_clock)
    hyp_registry = build_hypothesis_registry(claim_registry, agent_input, clock=_fixed_clock)
    return hyp_registry, claim_registry, agent_input


# --- Caso válido ---------------------------------------------


def test_verify_empty_hypothesis_registry_valid() -> None:
    h, c, a = _full_pipeline()
    rpt = verify_hypothesis_registry(h, c, a, clock=_fixed_clock)
    assert rpt.is_valid is True
    assert rpt.findings == []


def test_verify_single_hypothesis_registry_valid() -> None:
    h, c, a = _full_pipeline(_make_evidence(detector_event_id="x"))
    rpt = verify_hypothesis_registry(h, c, a, clock=_fixed_clock)
    assert rpt.is_valid is True
    assert rpt.findings == []
    assert rpt.n_hypotheses_verified == 1


def test_verify_multi_hypothesis_registry_valid() -> None:
    a1 = _make_evidence(detector_event_id="a", days_offset=0)
    b1 = _make_evidence(detector_event_id="b", days_offset=1)
    h, c, a = _full_pipeline(a1, b1)
    rpt = verify_hypothesis_registry(h, c, a, clock=_fixed_clock)
    assert rpt.is_valid is True


def test_verify_all_checks_pass() -> None:
    h, c, a = _full_pipeline(_make_evidence(detector_event_id="x"))
    rpt = verify_hypothesis_registry(h, c, a, clock=_fixed_clock)
    assert rpt.forward_index_consistent is True
    assert rpt.reverse_index_consistent is True
    assert rpt.all_supporting_claims_in_registry is True
    assert rpt.all_claims_covered_by_some_hypothesis is True
    assert rpt.all_hypothesis_ids_recompute_correctly is True
    assert rpt.registry_id_is_alias_of_registry_hash is True
    assert rpt.all_source_ids_match is True
    assert rpt.source_model_supported is True


# --- Swap detection -----------------------------------------


def test_verify_detects_source_claim_registry_id_mismatch() -> None:
    h1, c1, a1 = _full_pipeline(_make_evidence(detector_event_id="x"))
    _, c2, _ = _full_pipeline(_make_evidence(detector_event_id="y"))
    rpt = verify_hypothesis_registry(h1, c2, a1, clock=_fixed_clock)
    assert rpt.is_valid is False
    types = [f.finding_type for f in rpt.findings]
    assert "source_claim_registry_id_mismatch" in types


# --- Verifier nunca lanza -----------------------------------


def test_verify_never_raises() -> None:
    h, c, a = _full_pipeline(_make_evidence(detector_event_id="x"))
    rpt = verify_hypothesis_registry(h, c, a, clock=_fixed_clock)
    assert isinstance(rpt, HypothesisVerificationReport)


# --- Determinismo del reporte -------------------------------


def test_verify_report_reproducible() -> None:
    h, c, a = _full_pipeline(_make_evidence(detector_event_id="x"))
    r1 = verify_hypothesis_registry(h, c, a, clock=_fixed_clock)
    r2 = verify_hypothesis_registry(h, c, a, clock=_fixed_clock)
    assert r1.model_dump(mode="json") == r2.model_dump(mode="json")


def test_verify_clock_only_affects_verified_at() -> None:
    h, c, a = _full_pipeline(_make_evidence(detector_event_id="x"))

    def early() -> datetime:
        return datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)

    def late() -> datetime:
        return datetime(2027, 1, 1, 0, 0, tzinfo=timezone.utc)
    r1 = verify_hypothesis_registry(h, c, a, clock=early)
    r2 = verify_hypothesis_registry(h, c, a, clock=late)
    assert r1.is_valid == r2.is_valid
    assert r1.verification_hash == r2.verification_hash
    assert r1.verified_at != r2.verified_at


def test_verifier_engine_version_present() -> None:
    h, c, a = _full_pipeline(_make_evidence(detector_event_id="x"))
    rpt = verify_hypothesis_registry(h, c, a, clock=_fixed_clock)
    assert rpt.verifier_engine_version == "1.0.0"


def test_build_then_verify_always_valid() -> None:
    a1 = _make_evidence(detector_event_id="a", days_offset=0)
    b1 = _make_evidence(detector_event_id="b", days_offset=1)
    h, c, a = _full_pipeline(a1, b1)
    rpt = verify_hypothesis_registry(h, c, a, clock=_fixed_clock)
    assert rpt.is_valid is True
