"""Tests del :func:`verify_explanation` (ADR-0034)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from orbital_sentinel.analytics.agent_contract import build_agent_input
from orbital_sentinel.analytics.bundles import build_evidence_bundle
from orbital_sentinel.analytics.evidence import (
    EVIDENCE_TYPE_MANEUVER,
    DerivedEvidence,
    EvidenceCatalog,
    compute_evidence_id,
)
from orbital_sentinel.analytics.explanation import build_explanation_context
from orbital_sentinel.analytics.explanation_agent import (
    ExplanationArtifact,
    generate_explanation,
)
from orbital_sentinel.analytics.explanation_verifier import (
    ExplanationVerificationReport,
    verify_explanation,
)

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


# --- Caso válido --------------------------------------------------


def test_verify_explanation_valid_empty_bundle() -> None:
    art, ai = _full_pipeline()
    rpt = verify_explanation(art, ai, clock=_fixed_clock)
    assert rpt.is_valid is True
    assert rpt.findings == []


def test_verify_explanation_valid_with_evidence() -> None:
    art, ai = _full_pipeline(_make_evidence(detector_event_id="x"))
    rpt = verify_explanation(art, ai, clock=_fixed_clock)
    assert rpt.is_valid is True
    assert rpt.findings == []
    assert rpt.referenced_evidence_count == 1


def test_verify_explanation_all_checks_pass_for_valid() -> None:
    art, ai = _full_pipeline(_make_evidence(detector_event_id="x"))
    rpt = verify_explanation(art, ai, clock=_fixed_clock)
    assert rpt.explanation_id_recomputes_correctly is True
    assert rpt.audit_explanation_id_matches is True
    assert rpt.audit_bundle_id_matches is True
    assert rpt.audit_agent_input_id_matches is True
    assert rpt.prompt_hash_consistent_metadata_audit is True
    assert rpt.referenced_audit_ids_consistent is True
    assert rpt.source_bundle_id_matches_agent_input is True
    assert rpt.source_agent_input_id_matches_agent_input is True
    assert rpt.n_orphan_references == 0


# --- Detección de tampering --------------------------------------


def test_verify_detects_evidence_id_not_in_bundle() -> None:
    """Si el artifact referencia un evidence_id que no está en el bundle."""
    art, ai = _full_pipeline(_make_evidence(detector_event_id="x"))
    # Añadir manualmente un evidence_id fantasma
    fake_id = "ghost_" + "0" * 58
    tampered_audit = art.audit_record.model_copy(update={
        "evidence_ids_used": [*art.audit_record.evidence_ids_used, fake_id],
    })
    tampered = art.model_copy(update={
        "referenced_evidence_ids": [*art.referenced_evidence_ids, fake_id],
        "audit_record": tampered_audit,
    })
    rpt = verify_explanation(tampered, ai, clock=_fixed_clock)
    assert rpt.is_valid is False
    types = [f.finding_type for f in rpt.findings]
    assert "evidence_id_not_in_bundle" in types


def test_verify_detects_audit_bundle_id_mismatch() -> None:
    art, ai = _full_pipeline(_make_evidence(detector_event_id="x"))
    tampered_audit = art.audit_record.model_copy(update={"bundle_id": "0" * 64})
    tampered = art.model_copy(update={"audit_record": tampered_audit})
    rpt = verify_explanation(tampered, ai, clock=_fixed_clock)
    assert rpt.is_valid is False
    types = [f.finding_type for f in rpt.findings]
    assert "audit_bundle_id_mismatch" in types


def test_verify_detects_source_bundle_id_mismatch() -> None:
    art, ai = _full_pipeline(_make_evidence(detector_event_id="x"))
    tampered = art.model_copy(update={"source_bundle_id": "0" * 64})
    rpt = verify_explanation(tampered, ai, clock=_fixed_clock)
    assert rpt.is_valid is False
    types = [f.finding_type for f in rpt.findings]
    assert "source_bundle_id_mismatch" in types
    # explanation_id también fallará (depende de source_bundle_id)
    assert "explanation_id_recompute_mismatch" in types


def test_verify_detects_referenced_id_missing_from_audit() -> None:
    art, ai = _full_pipeline(_make_evidence(detector_event_id="x"))
    # Quitar uno del audit pero dejarlo en referenced
    tampered_audit = art.audit_record.model_copy(update={"evidence_ids_used": []})
    # Need to bypass the artifact model_validator. We construct via deep copy:
    new_dict = art.model_dump(mode="json")
    new_dict["audit_record"]["evidence_ids_used"] = []
    # Cannot construct due to model_validator; in real-world the verifier still
    # operates on existing valid artifacts. We test via direct model_construct.
    tampered = ExplanationArtifact.model_construct(
        **{**art.__dict__, "audit_record": tampered_audit},
    )
    rpt = verify_explanation(tampered, ai, clock=_fixed_clock)
    types = [f.finding_type for f in rpt.findings]
    assert any(t in types for t in (
        "referenced_id_missing_from_audit",
        "audit_id_missing_from_referenced",
    ))


# --- Determinismo --------------------------------------------


def test_verify_report_reproducible() -> None:
    art, ai = _full_pipeline(_make_evidence(detector_event_id="x"))
    a = verify_explanation(art, ai, clock=_fixed_clock)
    b = verify_explanation(art, ai, clock=_fixed_clock)
    assert a.model_dump(mode="json") == b.model_dump(mode="json")


def test_verify_clock_only_affects_verified_at() -> None:
    art, ai = _full_pipeline(_make_evidence(detector_event_id="x"))

    def early() -> datetime:
        return datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)

    def late() -> datetime:
        return datetime(2027, 1, 1, 0, 0, tzinfo=timezone.utc)
    a = verify_explanation(art, ai, clock=early)
    b = verify_explanation(art, ai, clock=late)
    assert a.is_valid == b.is_valid
    assert a.verification_hash == b.verification_hash
    assert a.verified_at != b.verified_at


def test_verify_never_raises_on_tampered_artifact() -> None:
    art, ai = _full_pipeline(_make_evidence(detector_event_id="x"))
    tampered = art.model_copy(update={"source_bundle_id": "X" * 64})
    rpt = verify_explanation(tampered, ai, clock=_fixed_clock)
    assert isinstance(rpt, ExplanationVerificationReport)


def test_verification_hash_correlates_with_validity() -> None:
    art, ai = _full_pipeline(_make_evidence(detector_event_id="x"))
    good = verify_explanation(art, ai, clock=_fixed_clock)
    tampered = art.model_copy(update={"source_bundle_id": "0" * 64})
    bad = verify_explanation(tampered, ai, clock=_fixed_clock)
    assert good.verification_hash != bad.verification_hash
