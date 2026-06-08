"""Tests de modelos del Agent Input Contract (ADR-0032)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from orbital_sentinel.analytics.agent_contract import (
    CONTRACT_ENGINE_VERSION,
    CONTRACT_SCHEMA_VERSION,
    AgentInput,
    compute_agent_input_id,
)
from orbital_sentinel.analytics.bundles import (
    BUNDLE_ENGINE_VERSION,
    BundleVerificationReport,
    EvidenceBundle,
    compute_bundle_payload_signature,
    compute_bundle_signature,
)
from orbital_sentinel.analytics.explanation import (
    EXPLANATION_LAYER_ENGINE_VERSION,
    ExplanationContext,
    ExplanationDetectorSummary,
    ExplanationTimeline,
)
from orbital_sentinel.analytics.explanation import (
    compute_context_id as compute_explanation_context_id,
)
from orbital_sentinel.analytics.explanation import (
    compute_source_catalog_signature as compute_explanation_catalog_signature,
)
from orbital_sentinel.analytics.explanation.models import CANONICAL_DETECTORS_V01

DERIVED_AT = datetime(2026, 6, 6, 12, 0, tzinfo=timezone.utc)


def _make_empty_context(object_id: int = 25544) -> ExplanationContext:
    sig = compute_explanation_catalog_signature([])
    return ExplanationContext(
        object_id=object_id,
        context_id=compute_explanation_context_id(
            object_id=object_id,
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


def _make_valid_bundle() -> EvidenceBundle:
    ctx = _make_empty_context()
    payload_sig = compute_bundle_payload_signature([])
    bundle_sig = compute_bundle_signature(
        context_id=ctx.context_id,
        bundle_payload_signature=payload_sig,
        bundle_engine_version=BUNDLE_ENGINE_VERSION,
    )
    return EvidenceBundle(
        bundle_id=bundle_sig,
        bundle_signature=bundle_sig,
        bundle_payload_signature=payload_sig,
        object_id=25544,
        context=ctx,
        evidence_payloads=[],
        n_evidence_payloads=0,
        derived_at=DERIVED_AT,
    )


def _make_valid_report(bundle_id: str) -> BundleVerificationReport:
    return BundleVerificationReport(
        bundle_id=bundle_id,
        is_valid=True,
        n_payloads_total=0,
        n_payloads_with_valid_hash=0,
        n_payloads_with_invalid_hash=0,
        context_id_recomputes_correctly=True,
        source_catalog_signature_recomputes_correctly=True,
        bundle_payload_signature_recomputes_correctly=True,
        bundle_signature_recomputes_correctly=True,
        bundle_id_is_alias_of_bundle_signature=True,
        integrity_failures=[],
        verified_at=DERIVED_AT,
    )


def _make_invalid_report(bundle_id: str) -> BundleVerificationReport:
    return BundleVerificationReport(
        bundle_id=bundle_id,
        is_valid=False,
        n_payloads_total=0,
        n_payloads_with_valid_hash=0,
        n_payloads_with_invalid_hash=0,
        context_id_recomputes_correctly=False,
        source_catalog_signature_recomputes_correctly=True,
        bundle_payload_signature_recomputes_correctly=True,
        bundle_signature_recomputes_correctly=True,
        bundle_id_is_alias_of_bundle_signature=True,
        integrity_failures=[],
        verified_at=DERIVED_AT,
    )


def _make_valid_agent_input() -> AgentInput:
    bundle = _make_valid_bundle()
    report = _make_valid_report(bundle.bundle_id)
    agent_input_id = compute_agent_input_id(
        bundle_id=bundle.bundle_id,
        declared_consumer_class="explanation_agent_v01",
        contract_engine_version=CONTRACT_ENGINE_VERSION,
    )
    return AgentInput(
        agent_input_id=agent_input_id,
        bundle=bundle,
        verification_report=report,
        declared_consumer_class="explanation_agent_v01",
        contract_acceptance_at=DERIVED_AT,
    )


# --- Helper compute_agent_input_id --------------------------------


def test_compute_agent_input_id_deterministic() -> None:
    a = compute_agent_input_id(
        bundle_id="abc", declared_consumer_class="explanation_agent_v01",
        contract_engine_version="0.1.0",
    )
    b = compute_agent_input_id(
        bundle_id="abc", declared_consumer_class="explanation_agent_v01",
        contract_engine_version="0.1.0",
    )
    assert a == b
    assert len(a) == 64


def test_compute_agent_input_id_varies_with_bundle() -> None:
    a = compute_agent_input_id(
        bundle_id="x", declared_consumer_class="explanation_agent_v01",
        contract_engine_version="0.1.0",
    )
    b = compute_agent_input_id(
        bundle_id="y", declared_consumer_class="explanation_agent_v01",
        contract_engine_version="0.1.0",
    )
    assert a != b


def test_compute_agent_input_id_varies_with_consumer_class() -> None:
    a = compute_agent_input_id(
        bundle_id="x", declared_consumer_class="explanation_agent_v01",
        contract_engine_version="0.1.0",
    )
    b = compute_agent_input_id(
        bundle_id="x", declared_consumer_class="api_endpoint_v01",
        contract_engine_version="0.1.0",
    )
    assert a != b


# --- Versioning ----------------------------------------------------


def test_contract_versions_are_v01() -> None:
    assert CONTRACT_SCHEMA_VERSION == "0.1.0"
    assert CONTRACT_ENGINE_VERSION == "0.1.0"


# --- AgentInput modelo ---------------------------------------------


def test_agent_input_extra_forbid() -> None:
    ai = _make_valid_agent_input()
    with pytest.raises(Exception):
        AgentInput.model_validate({**ai.model_dump(mode="json"), "extra": 1})


def test_agent_input_frozen() -> None:
    ai = _make_valid_agent_input()
    with pytest.raises(Exception):
        ai.declared_consumer_class = "api_endpoint_v01"  # type: ignore[misc]


def test_agent_input_rejects_invalid_report() -> None:
    """Hard invariant ADR-0032: is_valid debe ser True."""
    bundle = _make_valid_bundle()
    invalid_report = _make_invalid_report(bundle.bundle_id)
    with pytest.raises(Exception, match="is_valid=True"):
        AgentInput(
            agent_input_id="x" * 64,
            bundle=bundle,
            verification_report=invalid_report,
            declared_consumer_class="explanation_agent_v01",
            contract_acceptance_at=DERIVED_AT,
        )


def test_agent_input_rejects_report_for_different_bundle() -> None:
    """Hard invariant: el report debe ser sobre este bundle."""
    bundle = _make_valid_bundle()
    foreign_report = _make_valid_report(bundle_id="x" * 64)
    with pytest.raises(Exception, match="bundle_id"):
        AgentInput(
            agent_input_id="x" * 64,
            bundle=bundle,
            verification_report=foreign_report,
            declared_consumer_class="explanation_agent_v01",
            contract_acceptance_at=DERIVED_AT,
        )


def test_agent_input_rejects_unknown_consumer_class() -> None:
    bundle = _make_valid_bundle()
    report = _make_valid_report(bundle.bundle_id)
    with pytest.raises(Exception):
        AgentInput(
            agent_input_id="x" * 64,
            bundle=bundle,
            verification_report=report,
            declared_consumer_class="not_a_real_consumer",  # type: ignore[arg-type]
            contract_acceptance_at=DERIVED_AT,
        )


def test_agent_input_roundtrip() -> None:
    ai = _make_valid_agent_input()
    raw = ai.model_dump(mode="json")
    rehydrated = AgentInput.model_validate(raw)
    assert rehydrated.model_dump(mode="json") == raw


def test_agent_input_default_versioning() -> None:
    ai = _make_valid_agent_input()
    assert ai.contract_schema_version == CONTRACT_SCHEMA_VERSION
    assert ai.contract_engine_version == CONTRACT_ENGINE_VERSION


def test_agent_input_accepts_all_consumer_classes() -> None:
    bundle = _make_valid_bundle()
    report = _make_valid_report(bundle.bundle_id)
    for cls in (
        "explanation_agent_v01",
        "report_exporter_v01",
        "external_third_party_v01",
        "api_endpoint_v01",
        "audit_consumer_v01",
    ):
        ai = AgentInput(
            agent_input_id=compute_agent_input_id(
                bundle_id=bundle.bundle_id,
                declared_consumer_class=cls,
                contract_engine_version=CONTRACT_ENGINE_VERSION,
            ),
            bundle=bundle,
            verification_report=report,
            declared_consumer_class=cls,  # type: ignore[arg-type]
            contract_acceptance_at=DERIVED_AT,
        )
        assert ai.declared_consumer_class == cls
