"""Tests de modelos y helpers de hashing del Bundle Layer (ADR-0031)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from orbital_sentinel.analytics.bundles import (
    BUNDLE_ENGINE_VERSION,
    BUNDLE_SCHEMA_VERSION,
    VERIFIER_ENGINE_VERSION,
    BundledEvidence,
    BundleIntegrityFailure,
    BundleVerificationReport,
    EvidenceBundle,
    canonical_json,
    compute_bundle_payload_signature,
    compute_bundle_signature,
    compute_payload_hash,
)
from orbital_sentinel.analytics.evidence import (
    EVIDENCE_TYPE_MANEUVER,
    DerivedEvidence,
    compute_evidence_id,
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

EPOCH = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)
DERIVED_AT = datetime(2026, 6, 6, 12, 0, tzinfo=timezone.utc)


def _make_derived_evidence(*, payload: dict | None = None) -> DerivedEvidence:
    return DerivedEvidence(
        evidence_id=compute_evidence_id(
            source_detector="maneuver_detection_v01",
            object_id=25544,
            detector_event_id="evt-test",
            event_epoch=EPOCH,
            analysis_engine_version="0.1.0",
        ),
        object_id=25544,
        evidence_type=EVIDENCE_TYPE_MANEUVER,
        source_detector="maneuver_detection_v01",
        detector_event_id="evt-test",
        event_epoch=EPOCH,
        honesty_payload=payload or {"detection_method_name": "test"},
        analysis_engine_version="0.1.0",
    )


def _make_bundled_evidence() -> BundledEvidence:
    de = _make_derived_evidence()
    return BundledEvidence(
        evidence_id=de.evidence_id,
        derived_evidence=de,
        recomputed_payload_hash=compute_payload_hash(de.honesty_payload),
        payload_integrity_verified_at_build=True,
    )


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


# --- canonical_json ----------------------------------------------------


def test_canonical_json_orders_keys_recursively() -> None:
    a = canonical_json({"b": 2, "a": 1, "nested": {"y": 1, "x": 2}})
    b = canonical_json({"a": 1, "b": 2, "nested": {"x": 2, "y": 1}})
    assert a == b


def test_canonical_json_uses_compact_separators() -> None:
    out = canonical_json({"a": 1, "b": 2})
    assert ", " not in out
    assert ": " not in out


# --- compute_payload_hash ----------------------------------------------


def test_compute_payload_hash_deterministic() -> None:
    a = compute_payload_hash({"x": 1, "y": 2})
    b = compute_payload_hash({"y": 2, "x": 1})
    assert a == b
    assert len(a) == 64


def test_compute_payload_hash_distinct_inputs_distinct_hash() -> None:
    a = compute_payload_hash({"x": 1})
    b = compute_payload_hash({"x": 2})
    assert a != b


# --- compute_bundle_payload_signature ---------------------------------


def test_compute_bundle_payload_signature_empty() -> None:
    sig = compute_bundle_payload_signature([])
    assert len(sig) == 64


def test_compute_bundle_payload_signature_deterministic() -> None:
    bp = _make_bundled_evidence()
    a = compute_bundle_payload_signature([bp])
    b = compute_bundle_payload_signature([bp])
    assert a == b


# --- compute_bundle_signature -----------------------------------------


def test_compute_bundle_signature_deterministic() -> None:
    a = compute_bundle_signature(
        context_id="ctx", bundle_payload_signature="pay",
        bundle_engine_version="0.1.0",
    )
    b = compute_bundle_signature(
        context_id="ctx", bundle_payload_signature="pay",
        bundle_engine_version="0.1.0",
    )
    assert a == b


def test_compute_bundle_signature_varies_with_inputs() -> None:
    a = compute_bundle_signature(
        context_id="ctx_a", bundle_payload_signature="pay",
        bundle_engine_version="0.1.0",
    )
    b = compute_bundle_signature(
        context_id="ctx_b", bundle_payload_signature="pay",
        bundle_engine_version="0.1.0",
    )
    assert a != b


# --- Versioning constants ---------------------------------------------


def test_versioning_constants_are_v01() -> None:
    assert BUNDLE_SCHEMA_VERSION == "0.1.0"
    assert BUNDLE_ENGINE_VERSION == "0.1.0"
    assert VERIFIER_ENGINE_VERSION == "0.1.0"


# --- BundleIntegrityFailure -------------------------------------------


def test_integrity_failure_extra_forbid() -> None:
    f = BundleIntegrityFailure(
        failure_type="payload_hash_mismatch",
        affected_id="ev1", expected="a", actual="b",
    )
    with pytest.raises(Exception):
        BundleIntegrityFailure.model_validate(
            {**f.model_dump(mode="json"), "extra": 1}
        )


def test_integrity_failure_frozen() -> None:
    f = BundleIntegrityFailure(
        failure_type="payload_hash_mismatch",
        affected_id="ev1", expected="a", actual="b",
    )
    with pytest.raises(Exception):
        f.affected_id = "other"  # type: ignore[misc]


def test_integrity_failure_rejects_unknown_failure_type() -> None:
    with pytest.raises(Exception):
        BundleIntegrityFailure(
            failure_type="not_a_real_failure",  # type: ignore[arg-type]
            affected_id="x", expected="a", actual="b",
        )


def test_integrity_failure_roundtrip() -> None:
    f = BundleIntegrityFailure(
        failure_type="bundle_signature_mismatch",
        affected_id="bundle", expected="a", actual="b",
    )
    raw = f.model_dump(mode="json")
    assert BundleIntegrityFailure.model_validate(raw).model_dump(mode="json") == raw


# --- BundledEvidence ---------------------------------------------------


def test_bundled_evidence_extra_forbid_and_frozen() -> None:
    bp = _make_bundled_evidence()
    with pytest.raises(Exception):
        BundledEvidence.model_validate(
            {**bp.model_dump(mode="json"), "extra": 1}
        )
    with pytest.raises(Exception):
        bp.payload_integrity_verified_at_build = False  # type: ignore[misc]


def test_bundled_evidence_roundtrip() -> None:
    bp = _make_bundled_evidence()
    raw = bp.model_dump(mode="json")
    assert BundledEvidence.model_validate(raw).model_dump(mode="json") == raw


# --- EvidenceBundle: bundle_id == bundle_signature INVARIANTE ---------


def test_bundle_id_equals_bundle_signature() -> None:
    """Hard invariant ADR-0031: bundle_id es alias estricto de bundle_signature."""
    bundle = _make_valid_bundle()
    assert bundle.bundle_id == bundle.bundle_signature


def test_bundle_construction_rejects_bundle_id_signature_mismatch() -> None:
    """Si bundle_id != bundle_signature en construcción, debe lanzar."""
    ctx = _make_empty_context()
    payload_sig = compute_bundle_payload_signature([])
    bundle_sig = compute_bundle_signature(
        context_id=ctx.context_id,
        bundle_payload_signature=payload_sig,
        bundle_engine_version=BUNDLE_ENGINE_VERSION,
    )
    with pytest.raises(Exception, match="strict alias"):
        EvidenceBundle(
            bundle_id="forged_" + bundle_sig[7:],  # mismo largo, distinto valor
            bundle_signature=bundle_sig,
            bundle_payload_signature=payload_sig,
            object_id=25544,
            context=ctx,
            evidence_payloads=[],
            n_evidence_payloads=0,
            derived_at=DERIVED_AT,
        )


def test_bundle_extra_forbid() -> None:
    bundle = _make_valid_bundle()
    with pytest.raises(Exception):
        EvidenceBundle.model_validate(
            {**bundle.model_dump(mode="json"), "extra": 1}
        )


def test_bundle_frozen() -> None:
    bundle = _make_valid_bundle()
    with pytest.raises(Exception):
        bundle.bundle_id = "x" * 64  # type: ignore[misc]


def test_bundle_roundtrip() -> None:
    bundle = _make_valid_bundle()
    raw = bundle.model_dump(mode="json")
    rehydrated = EvidenceBundle.model_validate(raw)
    assert rehydrated.model_dump(mode="json") == raw
    assert rehydrated.bundle_id == rehydrated.bundle_signature


def test_bundle_versioning_defaults_v01() -> None:
    bundle = _make_valid_bundle()
    assert bundle.schema_version == BUNDLE_SCHEMA_VERSION == "0.1.0"
    assert bundle.bundle_engine_version == BUNDLE_ENGINE_VERSION == "0.1.0"


# --- BundleVerificationReport ----------------------------------------


def test_verification_report_extra_forbid_and_frozen() -> None:
    rpt = BundleVerificationReport(
        bundle_id="x" * 64,
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
    with pytest.raises(Exception):
        BundleVerificationReport.model_validate(
            {**rpt.model_dump(mode="json"), "extra": 1}
        )
    with pytest.raises(Exception):
        rpt.is_valid = False  # type: ignore[misc]


def test_verification_report_roundtrip() -> None:
    rpt = BundleVerificationReport(
        bundle_id="a" * 64,
        is_valid=False,
        n_payloads_total=2,
        n_payloads_with_valid_hash=1,
        n_payloads_with_invalid_hash=1,
        context_id_recomputes_correctly=True,
        source_catalog_signature_recomputes_correctly=True,
        bundle_payload_signature_recomputes_correctly=False,
        bundle_signature_recomputes_correctly=False,
        bundle_id_is_alias_of_bundle_signature=True,
        integrity_failures=[
            BundleIntegrityFailure(
                failure_type="payload_hash_mismatch",
                affected_id="ev1", expected="a", actual="b",
            ),
        ],
        verified_at=DERIVED_AT,
    )
    raw = rpt.model_dump(mode="json")
    assert BundleVerificationReport.model_validate(raw).model_dump(mode="json") == raw
