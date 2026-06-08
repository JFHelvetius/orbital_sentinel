"""Tests de modelos y helpers del Claim Layer (ADR-0035)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from orbital_sentinel.analytics.claims import (
    CLAIM_LAYER_ENGINE_VERSION,
    CLAIM_LAYER_SCHEMA_VERSION,
    CLAIM_VERIFIER_ENGINE_VERSION,
    SUPPORTED_SOURCE_MODELS_V01,
    ClaimRegistry,
    ClaimVerificationFinding,
    ClaimVerificationReport,
    VerifiableClaim,
    canonical_json,
    compute_claim_id,
    compute_registry_hash,
    compute_verification_hash,
)

DERIVED_AT = datetime(2026, 6, 6, 12, 0, tzinfo=timezone.utc)


def _make_claim(
    *, idx: int = 0, ev_id: str = "ev1", text: str = "Evidence says X.",
) -> VerifiableClaim:
    cid = compute_claim_id(
        source_explanation_id="exp1",
        claim_index=idx,
        supporting_evidence_ids=[ev_id],
        claim_text=text,
        claim_layer_engine_version=CLAIM_LAYER_ENGINE_VERSION,
    )
    return VerifiableClaim(
        claim_id=cid,
        source_explanation_id="exp1",
        claim_index=idx,
        supporting_evidence_ids=[ev_id],
        claim_text=text,
    )


def _make_registry(*, claims: list[VerifiableClaim] | None = None) -> ClaimRegistry:
    claims = claims or []
    forward = {c.claim_id: list(c.supporting_evidence_ids) for c in claims}
    reverse: dict[str, list[str]] = {}
    for c in claims:
        for ev in c.supporting_evidence_ids:
            reverse.setdefault(ev, []).append(c.claim_id)
    reverse_sorted = {k: sorted(v) for k, v in sorted(reverse.items())}
    forward_sorted = {k: forward[k] for k in sorted(forward.keys())}
    rh = compute_registry_hash(
        source_explanation_id="exp1",
        source_bundle_id="b1",
        source_agent_input_id="a1",
        claim_ids=[c.claim_id for c in claims],
        claim_layer_engine_version=CLAIM_LAYER_ENGINE_VERSION,
    )
    return ClaimRegistry(
        registry_id=rh,
        registry_hash=rh,
        source_explanation_id="exp1",
        source_bundle_id="b1",
        source_agent_input_id="a1",
        source_model_identifier="template_explanation_v01",
        source_explanation_engine_version="0.1.0",
        n_claims=len(claims),
        claims=claims,
        claim_to_evidence_index=forward_sorted,
        evidence_to_claim_index=reverse_sorted,
        registry_emit_reason="evidence_bundle" if claims else "empty_bundle",
        derived_at=DERIVED_AT,
    )


# --- canonical_json ----------------------------------------------


def test_canonical_json_orders_keys() -> None:
    a = canonical_json({"b": 1, "a": 2})
    b = canonical_json({"a": 2, "b": 1})
    assert a == b


def test_canonical_json_compact_separators() -> None:
    out = canonical_json({"a": 1, "b": 2})
    assert ", " not in out
    assert ": " not in out


# --- compute_claim_id -------------------------------------------


def test_compute_claim_id_deterministic() -> None:
    a = compute_claim_id(
        source_explanation_id="x", claim_index=0,
        supporting_evidence_ids=["e1"], claim_text="hello",
        claim_layer_engine_version="0.1.0",
    )
    b = compute_claim_id(
        source_explanation_id="x", claim_index=0,
        supporting_evidence_ids=["e1"], claim_text="hello",
        claim_layer_engine_version="0.1.0",
    )
    assert a == b
    assert len(a) == 64


def test_compute_claim_id_varies_with_index() -> None:
    a = compute_claim_id(
        source_explanation_id="x", claim_index=0,
        supporting_evidence_ids=["e1"], claim_text="hello",
        claim_layer_engine_version="0.1.0",
    )
    b = compute_claim_id(
        source_explanation_id="x", claim_index=1,
        supporting_evidence_ids=["e1"], claim_text="hello",
        claim_layer_engine_version="0.1.0",
    )
    assert a != b


def test_compute_claim_id_supporting_order_irrelevant() -> None:
    a = compute_claim_id(
        source_explanation_id="x", claim_index=0,
        supporting_evidence_ids=["e1", "e2"], claim_text="t",
        claim_layer_engine_version="0.1.0",
    )
    b = compute_claim_id(
        source_explanation_id="x", claim_index=0,
        supporting_evidence_ids=["e2", "e1"], claim_text="t",
        claim_layer_engine_version="0.1.0",
    )
    assert a == b


def test_compute_claim_id_unicode_text() -> None:
    """claim_text con Unicode no debe romper el hash."""
    a = compute_claim_id(
        source_explanation_id="x", claim_index=0,
        supporting_evidence_ids=["e1"], claim_text="Evidence: σ=0.5, α=1.0",
        claim_layer_engine_version="0.1.0",
    )
    assert len(a) == 64


# --- compute_registry_hash --------------------------------------


def test_compute_registry_hash_deterministic() -> None:
    a = compute_registry_hash(
        source_explanation_id="e", source_bundle_id="b",
        source_agent_input_id="a", claim_ids=["c1", "c2"],
        claim_layer_engine_version="0.1.0",
    )
    b = compute_registry_hash(
        source_explanation_id="e", source_bundle_id="b",
        source_agent_input_id="a", claim_ids=["c2", "c1"],
        claim_layer_engine_version="0.1.0",
    )
    assert a == b


# --- compute_verification_hash ----------------------------------


def test_compute_verification_hash_deterministic() -> None:
    a = compute_verification_hash(
        registry_id="r", is_valid=True, n_claims_verified=3,
        n_findings=0, verifier_engine_version="0.1.0",
    )
    b = compute_verification_hash(
        registry_id="r", is_valid=True, n_claims_verified=3,
        n_findings=0, verifier_engine_version="0.1.0",
    )
    assert a == b


def test_compute_verification_hash_varies_with_is_valid() -> None:
    a = compute_verification_hash(
        registry_id="r", is_valid=True, n_claims_verified=0,
        n_findings=0, verifier_engine_version="0.1.0",
    )
    b = compute_verification_hash(
        registry_id="r", is_valid=False, n_claims_verified=0,
        n_findings=0, verifier_engine_version="0.1.0",
    )
    assert a != b


# --- Versioning ------------------------------------------------


def test_versioning_constants_v01() -> None:
    assert CLAIM_LAYER_SCHEMA_VERSION == "0.1.0"
    assert CLAIM_LAYER_ENGINE_VERSION == "0.1.0"
    assert CLAIM_VERIFIER_ENGINE_VERSION == "0.1.0"


def test_supported_source_models_v01() -> None:
    assert SUPPORTED_SOURCE_MODELS_V01 == ("template_explanation_v01",)


# --- VerifiableClaim -------------------------------------------


def test_claim_extra_forbid_and_frozen() -> None:
    c = _make_claim()
    with pytest.raises(Exception):
        VerifiableClaim.model_validate({**c.model_dump(mode="json"), "extra": 1})
    with pytest.raises(Exception):
        c.claim_text = "x"


def test_claim_supporting_min_length_1() -> None:
    with pytest.raises(Exception):
        VerifiableClaim(
            claim_id="x" * 64, source_explanation_id="x",
            claim_index=0, supporting_evidence_ids=[],
            claim_text="t",
        )


def test_claim_index_ge_zero() -> None:
    with pytest.raises(Exception):
        VerifiableClaim(
            claim_id="x" * 64, source_explanation_id="x",
            claim_index=-1, supporting_evidence_ids=["e1"],
            claim_text="t",
        )


def test_claim_invariant_id_must_recompute() -> None:
    """Hard invariant CLAIM-001."""
    with pytest.raises(Exception, match="recomputed hash"):
        VerifiableClaim(
            claim_id="0" * 64, source_explanation_id="x",
            claim_index=0, supporting_evidence_ids=["e1"],
            claim_text="t",
        )


def test_claim_roundtrip() -> None:
    c = _make_claim()
    raw = c.model_dump(mode="json")
    assert VerifiableClaim.model_validate(raw).model_dump(mode="json") == raw


# --- ClaimRegistry ---------------------------------------------


def test_registry_extra_forbid_and_frozen() -> None:
    r = _make_registry()
    with pytest.raises(Exception):
        ClaimRegistry.model_validate({**r.model_dump(mode="json"), "extra": 1})
    with pytest.raises(Exception):
        r.n_claims = 99


def test_registry_hard_invariant_id_equals_hash() -> None:
    """CLAIM-008: registry_id == registry_hash."""
    rh = compute_registry_hash(
        source_explanation_id="e", source_bundle_id="b",
        source_agent_input_id="a", claim_ids=[],
        claim_layer_engine_version="0.1.0",
    )
    with pytest.raises(Exception, match="strict alias"):
        ClaimRegistry(
            registry_id="forged_" + rh[7:],
            registry_hash=rh,
            source_explanation_id="e", source_bundle_id="b",
            source_agent_input_id="a",
            source_model_identifier="template_explanation_v01",
            source_explanation_engine_version="0.1.0",
            n_claims=0, claims=[],
            claim_to_evidence_index={}, evidence_to_claim_index={},
            registry_emit_reason="empty_bundle",
            derived_at=DERIVED_AT,
        )


def test_registry_hash_must_recompute() -> None:
    """registry_hash debe coincidir con recompute."""
    with pytest.raises(Exception, match="recomputed hash"):
        ClaimRegistry(
            registry_id="x" * 64, registry_hash="x" * 64,
            source_explanation_id="e", source_bundle_id="b",
            source_agent_input_id="a",
            source_model_identifier="template_explanation_v01",
            source_explanation_engine_version="0.1.0",
            n_claims=0, claims=[],
            claim_to_evidence_index={}, evidence_to_claim_index={},
            registry_emit_reason="empty_bundle",
            derived_at=DERIVED_AT,
        )


def test_registry_emit_reason_literal_closed() -> None:
    with pytest.raises(Exception):
        ClaimRegistry(
            registry_id="x", registry_hash="x",
            source_explanation_id="e", source_bundle_id="b",
            source_agent_input_id="a",
            source_model_identifier="template_explanation_v01",
            source_explanation_engine_version="0.1.0",
            n_claims=0, claims=[],
            claim_to_evidence_index={}, evidence_to_claim_index={},
            registry_emit_reason="other",  # type: ignore[arg-type]
            derived_at=DERIVED_AT,
        )


def test_registry_roundtrip() -> None:
    c = _make_claim()
    r = _make_registry(claims=[c])
    raw = r.model_dump(mode="json")
    assert ClaimRegistry.model_validate(raw).model_dump(mode="json") == raw


def test_registry_versioning_defaults() -> None:
    r = _make_registry()
    assert r.schema_version == CLAIM_LAYER_SCHEMA_VERSION == "0.1.0"
    assert r.claim_layer_engine_version == CLAIM_LAYER_ENGINE_VERSION == "0.1.0"


# --- ClaimVerificationFinding -------------------------------


def test_finding_literal_closed() -> None:
    with pytest.raises(Exception):
        ClaimVerificationFinding(
            finding_type="not_a_finding",  # type: ignore[arg-type]
            affected_id="x", expected="a", actual="b",
        )


def test_finding_extra_forbid() -> None:
    f = ClaimVerificationFinding(
        finding_type="claim_id_recompute_mismatch",
        affected_id="x", expected="a", actual="b",
    )
    with pytest.raises(Exception):
        ClaimVerificationFinding.model_validate(
            {**f.model_dump(mode="json"), "extra": 1}
        )


def test_finding_roundtrip() -> None:
    f = ClaimVerificationFinding(
        finding_type="duplicate_claim_id",
        affected_id="c", expected="unique", actual="duplicated",
    )
    raw = f.model_dump(mode="json")
    assert ClaimVerificationFinding.model_validate(raw).model_dump(mode="json") == raw


# --- ClaimVerificationReport -------------------------------


def _empty_report() -> ClaimVerificationReport:
    vh = compute_verification_hash(
        registry_id="r", is_valid=True, n_claims_verified=0,
        n_findings=0, verifier_engine_version="0.1.0",
    )
    return ClaimVerificationReport(
        registry_id="r", is_valid=True,
        n_claims_verified=0, n_claims_with_findings=0, n_findings=0,
        forward_index_consistent=True, reverse_index_consistent=True,
        all_supporting_evidence_in_bundle=True,
        all_referenced_evidence_covered=True,
        all_claim_ids_recompute_correctly=True,
        registry_id_is_alias_of_registry_hash=True,
        all_source_ids_match=True,
        all_claim_texts_match_explanation=True,
        source_model_supported=True,
        findings=[],
        verification_hash=vh,
        verified_at=DERIVED_AT,
    )


def test_report_extra_forbid_and_frozen() -> None:
    r = _empty_report()
    with pytest.raises(Exception):
        ClaimVerificationReport.model_validate({**r.model_dump(mode="json"), "extra": 1})
    with pytest.raises(Exception):
        r.is_valid = False


def test_report_roundtrip() -> None:
    r = _empty_report()
    raw = r.model_dump(mode="json")
    assert ClaimVerificationReport.model_validate(raw).model_dump(mode="json") == raw
