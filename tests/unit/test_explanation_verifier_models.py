"""Tests de modelos del Explanation Verification Layer (ADR-0034)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from orbital_sentinel.analytics.explanation_verifier import (
    EXPLANATION_VERIFICATION_SCHEMA_VERSION,
    EXPLANATION_VERIFIER_ENGINE_VERSION,
    ExplanationVerificationFinding,
    ExplanationVerificationReport,
    compute_verification_hash,
)

DERIVED_AT = datetime(2026, 6, 6, 12, 0, tzinfo=timezone.utc)


def _make_valid_report() -> ExplanationVerificationReport:
    vh = compute_verification_hash(
        explanation_id="e", bundle_id="b", agent_input_id="a",
        is_valid=True, referenced_evidence_count=0,
        verifier_engine_version=EXPLANATION_VERIFIER_ENGINE_VERSION,
    )
    return ExplanationVerificationReport(
        explanation_id="e", bundle_id="b", agent_input_id="a",
        is_valid=True,
        referenced_evidence_count=0,
        n_orphan_references=0,
        n_findings=0,
        explanation_id_recomputes_correctly=True,
        audit_explanation_id_matches=True,
        audit_bundle_id_matches=True,
        audit_agent_input_id_matches=True,
        prompt_hash_consistent_metadata_audit=True,
        referenced_audit_ids_consistent=True,
        source_bundle_id_matches_agent_input=True,
        source_agent_input_id_matches_agent_input=True,
        findings=[],
        verification_hash=vh,
        verified_at=DERIVED_AT,
    )


# --- compute_verification_hash --------------------------------


def test_verification_hash_deterministic() -> None:
    a = compute_verification_hash(
        explanation_id="e", bundle_id="b", agent_input_id="a",
        is_valid=True, referenced_evidence_count=3,
        verifier_engine_version="0.1.0",
    )
    b = compute_verification_hash(
        explanation_id="e", bundle_id="b", agent_input_id="a",
        is_valid=True, referenced_evidence_count=3,
        verifier_engine_version="0.1.0",
    )
    assert a == b
    assert len(a) == 64


def test_verification_hash_varies_with_is_valid() -> None:
    a = compute_verification_hash(
        explanation_id="e", bundle_id="b", agent_input_id="a",
        is_valid=True, referenced_evidence_count=3,
        verifier_engine_version="0.1.0",
    )
    b = compute_verification_hash(
        explanation_id="e", bundle_id="b", agent_input_id="a",
        is_valid=False, referenced_evidence_count=3,
        verifier_engine_version="0.1.0",
    )
    assert a != b


# --- Versioning ----------------------------------------------


def test_versioning_constants_v01() -> None:
    assert EXPLANATION_VERIFICATION_SCHEMA_VERSION == "0.1.0"
    assert EXPLANATION_VERIFIER_ENGINE_VERSION == "0.1.0"


# --- ExplanationVerificationFinding -------------------------


def test_finding_extra_forbid_and_frozen() -> None:
    f = ExplanationVerificationFinding(
        finding_type="evidence_id_not_in_bundle",
        affected_id="x", expected="present", actual="absent",
    )
    with pytest.raises(Exception):
        ExplanationVerificationFinding.model_validate(
            {**f.model_dump(mode="json"), "extra": 1}
        )
    with pytest.raises(Exception):
        f.affected_id = "y"  # type: ignore[misc]


def test_finding_rejects_unknown_type() -> None:
    with pytest.raises(Exception):
        ExplanationVerificationFinding(
            finding_type="not_a_real_finding",  # type: ignore[arg-type]
            affected_id="x", expected="a", actual="b",
        )


def test_finding_roundtrip() -> None:
    f = ExplanationVerificationFinding(
        finding_type="audit_bundle_id_mismatch",
        affected_id="audit_record", expected="x", actual="y",
    )
    raw = f.model_dump(mode="json")
    assert ExplanationVerificationFinding.model_validate(raw).model_dump(mode="json") == raw


# --- ExplanationVerificationReport --------------------------


def test_report_extra_forbid_and_frozen() -> None:
    rpt = _make_valid_report()
    with pytest.raises(Exception):
        ExplanationVerificationReport.model_validate(
            {**rpt.model_dump(mode="json"), "extra": 1}
        )
    with pytest.raises(Exception):
        rpt.is_valid = False  # type: ignore[misc]


def test_report_roundtrip() -> None:
    rpt = _make_valid_report()
    raw = rpt.model_dump(mode="json")
    assert ExplanationVerificationReport.model_validate(raw).model_dump(mode="json") == raw


def test_report_default_versioning() -> None:
    rpt = _make_valid_report()
    assert rpt.verifier_engine_version == EXPLANATION_VERIFIER_ENGINE_VERSION
    assert rpt.schema_version == EXPLANATION_VERIFICATION_SCHEMA_VERSION


def test_report_count_ge_zero() -> None:
    with pytest.raises(Exception):
        ExplanationVerificationReport(
            explanation_id="e", bundle_id="b", agent_input_id="a",
            is_valid=True, referenced_evidence_count=-1,
            n_orphan_references=0, n_findings=0,
            explanation_id_recomputes_correctly=True,
            audit_explanation_id_matches=True,
            audit_bundle_id_matches=True,
            audit_agent_input_id_matches=True,
            prompt_hash_consistent_metadata_audit=True,
            referenced_audit_ids_consistent=True,
            source_bundle_id_matches_agent_input=True,
            source_agent_input_id_matches_agent_input=True,
            findings=[],
            verification_hash="x" * 64,
            verified_at=DERIVED_AT,
        )
