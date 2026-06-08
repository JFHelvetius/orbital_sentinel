"""Tests del :func:`verify_claim_registry` (ADR-0035)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from orbital_sentinel.analytics.agent_contract import build_agent_input
from orbital_sentinel.analytics.bundles import build_evidence_bundle
from orbital_sentinel.analytics.claims import (
    ClaimVerificationReport,
    build_claim_registry,
    verify_claim_registry,
)
from orbital_sentinel.analytics.evidence import (
    EVIDENCE_TYPE_MANEUVER,
    DerivedEvidence,
    EvidenceCatalog,
    compute_evidence_id,
)
from orbital_sentinel.analytics.explanation import build_explanation_context
from orbital_sentinel.analytics.explanation_agent import generate_explanation

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
    registry = build_claim_registry(artifact, agent_input, clock=_fixed_clock)
    return registry, agent_input, artifact


# --- Caso válido ---------------------------------------------


def test_verify_empty_registry_valid() -> None:
    reg, ai, art = _full_pipeline()
    rpt = verify_claim_registry(reg, ai, art, clock=_fixed_clock)
    assert rpt.is_valid is True
    assert rpt.findings == []


def test_verify_single_claim_registry_valid() -> None:
    reg, ai, art = _full_pipeline(_make_evidence(detector_event_id="x"))
    rpt = verify_claim_registry(reg, ai, art, clock=_fixed_clock)
    assert rpt.is_valid is True
    assert rpt.findings == []
    assert rpt.n_claims_verified == 1


def test_verify_multi_claim_registry_valid() -> None:
    a = _make_evidence(detector_event_id="a", days_offset=0)
    b = _make_evidence(detector_event_id="b", days_offset=1)
    c = _make_evidence(detector_event_id="c", days_offset=2)
    reg, ai, art = _full_pipeline(a, b, c)
    rpt = verify_claim_registry(reg, ai, art, clock=_fixed_clock)
    assert rpt.is_valid is True
    assert rpt.n_claims_verified == 3


def test_verify_all_checks_pass_on_valid_registry() -> None:
    reg, ai, art = _full_pipeline(_make_evidence(detector_event_id="x"))
    rpt = verify_claim_registry(reg, ai, art, clock=_fixed_clock)
    assert rpt.forward_index_consistent is True
    assert rpt.reverse_index_consistent is True
    assert rpt.all_supporting_evidence_in_bundle is True
    assert rpt.all_referenced_evidence_covered is True
    assert rpt.all_claim_ids_recompute_correctly is True
    assert rpt.registry_id_is_alias_of_registry_hash is True
    assert rpt.all_source_ids_match is True
    assert rpt.all_claim_texts_match_explanation is True
    assert rpt.source_model_supported is True


# --- Tampering por finding_type --------------------------


def test_verify_detects_source_explanation_id_mismatch() -> None:
    reg, ai, art = _full_pipeline(_make_evidence(detector_event_id="x"))
    tampered_art = art.model_copy(update={"explanation_id": "0" * 64})
    rpt = verify_claim_registry(reg, ai, tampered_art, clock=_fixed_clock)
    assert rpt.is_valid is False
    types = [f.finding_type for f in rpt.findings]
    assert "source_explanation_id_mismatch" in types


def test_verify_detects_source_bundle_id_mismatch_via_swapped_agent_input() -> None:
    """Si registry tiene source_bundle_id que no coincide con agent_input."""
    reg1, ai1, art1 = _full_pipeline(_make_evidence(detector_event_id="x"))
    _, ai2, _ = _full_pipeline(_make_evidence(detector_event_id="y"))
    # Verificar reg1 con ai2: source_bundle_id no coincide
    rpt = verify_claim_registry(reg1, ai2, art1, clock=_fixed_clock)
    assert rpt.is_valid is False
    types = [f.finding_type for f in rpt.findings]
    assert "source_bundle_id_mismatch" in types or \
           "source_agent_input_id_mismatch" in types


def test_verify_detects_claim_text_mismatch() -> None:
    reg, ai, art = _full_pipeline(_make_evidence(detector_event_id="x"))
    tampered_art = art.model_copy(update={
        "explanation_text": "Evidence MUTATED: detector said something else.",
    })
    rpt = verify_claim_registry(reg, ai, tampered_art, clock=_fixed_clock)
    assert rpt.is_valid is False
    types = [f.finding_type for f in rpt.findings]
    assert "claim_text_does_not_match_explanation_line" in types


def test_verify_detects_supporting_evidence_not_in_bundle() -> None:
    """Forzamos un registry cuya supporting_evidence apunta a un evidence_id ausente.

    Lo simulamos modificando el agent_input (cambiando bundle) y reverificando.
    """
    reg, ai, art = _full_pipeline(_make_evidence(detector_event_id="x"))
    _, ai_empty, _ = _full_pipeline()
    rpt = verify_claim_registry(reg, ai_empty, art, clock=_fixed_clock)
    assert rpt.is_valid is False
    types = [f.finding_type for f in rpt.findings]
    assert "supporting_evidence_not_in_bundle" in types or \
           "source_bundle_id_mismatch" in types


# --- Verifier nunca lanza --------------------------------


def test_verify_never_raises_on_completely_tampered_inputs() -> None:
    reg, ai, art = _full_pipeline(_make_evidence(detector_event_id="x"))
    tampered_art = art.model_copy(update={
        "explanation_id": "0" * 64,
        "explanation_text": "MUTATED",
        "source_bundle_id": "0" * 64,
        "source_agent_input_id": "0" * 64,
    })
    rpt = verify_claim_registry(reg, ai, tampered_art, clock=_fixed_clock)
    assert isinstance(rpt, ClaimVerificationReport)
    assert rpt.is_valid is False


# --- Determinismo del reporte ----------------------------


def test_verify_report_reproducible_across_runs() -> None:
    reg, ai, art = _full_pipeline(_make_evidence(detector_event_id="x"))
    a = verify_claim_registry(reg, ai, art, clock=_fixed_clock)
    b = verify_claim_registry(reg, ai, art, clock=_fixed_clock)
    assert a.model_dump(mode="json") == b.model_dump(mode="json")


def test_verify_clock_only_affects_verified_at() -> None:
    reg, ai, art = _full_pipeline(_make_evidence(detector_event_id="x"))

    def early() -> datetime:
        return datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)

    def late() -> datetime:
        return datetime(2027, 1, 1, 0, 0, tzinfo=timezone.utc)
    a = verify_claim_registry(reg, ai, art, clock=early)
    b = verify_claim_registry(reg, ai, art, clock=late)
    assert a.is_valid == b.is_valid
    assert a.verification_hash == b.verification_hash
    assert a.verified_at != b.verified_at


def test_verification_hash_changes_with_tampering() -> None:
    reg, ai, art = _full_pipeline(_make_evidence(detector_event_id="x"))
    good = verify_claim_registry(reg, ai, art, clock=_fixed_clock)
    tampered_art = art.model_copy(update={"explanation_id": "0" * 64})
    bad = verify_claim_registry(reg, ai, tampered_art, clock=_fixed_clock)
    assert good.verification_hash != bad.verification_hash


def test_verifier_engine_version_present() -> None:
    reg, ai, art = _full_pipeline(_make_evidence(detector_event_id="x"))
    rpt = verify_claim_registry(reg, ai, art, clock=_fixed_clock)
    assert rpt.verifier_engine_version == "0.1.0"


# --- Ciclo build + verify es cerrado ---------------------


def test_build_then_verify_always_valid() -> None:
    """Cualquier registry recién construido debe verificar como valid."""
    a = _make_evidence(detector_event_id="a", days_offset=0)
    b = _make_evidence(detector_event_id="b", days_offset=1)
    c = _make_evidence(detector_event_id="c", days_offset=2)
    reg, ai, art = _full_pipeline(a, b, c)
    rpt = verify_claim_registry(reg, ai, art, clock=_fixed_clock)
    assert rpt.is_valid is True
    assert rpt.findings == []


def test_n_claims_with_findings_aggregates_correctly() -> None:
    reg, ai, art = _full_pipeline(_make_evidence(detector_event_id="x"))
    tampered_art = art.model_copy(update={"explanation_text": "BAD"})
    rpt = verify_claim_registry(reg, ai, tampered_art, clock=_fixed_clock)
    # Al menos un claim afectado por mismatch de texto
    assert rpt.n_claims_with_findings >= 1
