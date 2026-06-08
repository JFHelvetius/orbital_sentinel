"""Tests del :func:`build_agent_input` (ADR-0032)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from orbital_sentinel.analytics.agent_contract import (
    CONTRACT_ENGINE_VERSION,
    build_agent_input,
    compute_agent_input_id,
)
from orbital_sentinel.analytics.bundles import (
    EvidenceBundle,
    build_evidence_bundle,
)
from orbital_sentinel.analytics.evidence import (
    EVIDENCE_TYPE_MANEUVER,
    DerivedEvidence,
    EvidenceCatalog,
    compute_evidence_id,
)
from orbital_sentinel.analytics.explanation import build_explanation_context
from orbital_sentinel.core.errors import AgentInputRejectedError

EPOCH = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)
DERIVED_AT = datetime(2026, 6, 6, 12, 0, tzinfo=timezone.utc)


def _fixed_clock() -> datetime:
    return DERIVED_AT


def _build_bundle() -> EvidenceBundle:
    de = DerivedEvidence(
        evidence_id=compute_evidence_id(
            source_detector="maneuver_detection_v01",
            object_id=25544,
            detector_event_id="evt",
            event_epoch=EPOCH,
            analysis_engine_version="0.1.0",
        ),
        object_id=25544,
        evidence_type=EVIDENCE_TYPE_MANEUVER,
        source_detector="maneuver_detection_v01",
        detector_event_id="evt",
        event_epoch=EPOCH,
        honesty_payload={"detection_method_name": "test"},
        analysis_engine_version="0.1.0",
    )
    catalog = EvidenceCatalog.from_evidence([de], derived_at=DERIVED_AT)
    ctx = build_explanation_context(catalog, object_id=25544, clock=_fixed_clock)
    return build_evidence_bundle(ctx, catalog, clock=_fixed_clock)


# --- Construcción exitosa -----------------------------------------


def test_build_agent_input_succeeds_for_valid_bundle() -> None:
    bundle = _build_bundle()
    ai = build_agent_input(
        bundle, declared_consumer_class="explanation_agent_v01",
        clock=_fixed_clock,
    )
    assert ai.bundle.bundle_id == bundle.bundle_id
    assert ai.verification_report.is_valid is True


def test_build_agent_input_id_is_content_addressable() -> None:
    bundle = _build_bundle()
    ai = build_agent_input(
        bundle, declared_consumer_class="explanation_agent_v01",
        clock=_fixed_clock,
    )
    expected = compute_agent_input_id(
        bundle_id=bundle.bundle_id,
        declared_consumer_class="explanation_agent_v01",
        contract_engine_version=CONTRACT_ENGINE_VERSION,
    )
    assert ai.agent_input_id == expected


def test_build_agent_input_deterministic_for_same_inputs() -> None:
    bundle = _build_bundle()
    a = build_agent_input(
        bundle, declared_consumer_class="explanation_agent_v01",
        clock=_fixed_clock,
    )
    b = build_agent_input(
        bundle, declared_consumer_class="explanation_agent_v01",
        clock=_fixed_clock,
    )
    assert a.agent_input_id == b.agent_input_id
    assert a.model_dump(mode="json") == b.model_dump(mode="json")


def test_build_agent_input_different_consumer_class_different_id() -> None:
    bundle = _build_bundle()
    a = build_agent_input(
        bundle, declared_consumer_class="explanation_agent_v01",
        clock=_fixed_clock,
    )
    b = build_agent_input(
        bundle, declared_consumer_class="api_endpoint_v01",
        clock=_fixed_clock,
    )
    assert a.agent_input_id != b.agent_input_id


def test_build_agent_input_embeds_verification_report() -> None:
    bundle = _build_bundle()
    ai = build_agent_input(
        bundle, declared_consumer_class="explanation_agent_v01",
        clock=_fixed_clock,
    )
    assert ai.verification_report.bundle_id == bundle.bundle_id


def test_build_agent_input_clock_only_affects_acceptance_at() -> None:
    bundle = _build_bundle()

    def early() -> datetime:
        return datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)

    def late() -> datetime:
        return datetime(2027, 1, 1, 0, 0, tzinfo=timezone.utc)
    a = build_agent_input(
        bundle, declared_consumer_class="explanation_agent_v01", clock=early,
    )
    b = build_agent_input(
        bundle, declared_consumer_class="explanation_agent_v01", clock=late,
    )
    assert a.agent_input_id == b.agent_input_id
    assert a.contract_acceptance_at != b.contract_acceptance_at


# --- Rechazo de bundles inválidos --------------------------------


def test_build_agent_input_rejects_tampered_bundle() -> None:
    bundle = _build_bundle()
    tampered_ctx = bundle.context.model_copy(update={"context_id": "0" * 64})
    tampered = bundle.model_copy(update={"context": tampered_ctx})
    with pytest.raises(AgentInputRejectedError) as exc:
        build_agent_input(
            tampered, declared_consumer_class="explanation_agent_v01",
            clock=_fixed_clock,
        )
    assert exc.value.verification_report.is_valid is False
    assert len(exc.value.verification_report.integrity_failures) > 0


def test_build_agent_input_rejection_attaches_full_report() -> None:
    bundle = _build_bundle()
    tampered = bundle.model_copy(update={"bundle_payload_signature": "0" * 64})
    with pytest.raises(AgentInputRejectedError) as exc:
        build_agent_input(
            tampered, declared_consumer_class="explanation_agent_v01",
            clock=_fixed_clock,
        )
    report = exc.value.verification_report
    failure_types = {f.failure_type for f in report.integrity_failures}
    assert "bundle_payload_signature_mismatch" in failure_types or \
           "bundle_signature_mismatch" in failure_types


# --- Determinismo total ------------------------------------------


def test_build_agent_input_full_output_reproducible() -> None:
    bundle = _build_bundle()
    a = build_agent_input(
        bundle, declared_consumer_class="explanation_agent_v01", clock=_fixed_clock,
    )
    b = build_agent_input(
        bundle, declared_consumer_class="explanation_agent_v01", clock=_fixed_clock,
    )
    assert a.model_dump(mode="json") == b.model_dump(mode="json")


def test_all_consumer_classes_accepted_by_builder() -> None:
    bundle = _build_bundle()
    for cls in (
        "explanation_agent_v01",
        "report_exporter_v01",
        "external_third_party_v01",
        "api_endpoint_v01",
        "audit_consumer_v01",
    ):
        ai = build_agent_input(
            bundle, declared_consumer_class=cls,  # type: ignore[arg-type]
            clock=_fixed_clock,
        )
        assert ai.declared_consumer_class == cls
