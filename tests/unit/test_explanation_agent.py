"""Tests del :func:`generate_explanation` (ADR-0033)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from orbital_sentinel.analytics.agent_contract import build_agent_input
from orbital_sentinel.analytics.bundles import build_evidence_bundle
from orbital_sentinel.analytics.evidence import (
    EVIDENCE_TYPE_ANOMALY,
    EVIDENCE_TYPE_CONJUNCTION,
    EVIDENCE_TYPE_MANEUVER,
    DerivedEvidence,
    EvidenceCatalog,
    compute_evidence_id,
)
from orbital_sentinel.analytics.explanation import build_explanation_context
from orbital_sentinel.analytics.explanation_agent import (
    EXPLANATION_AGENT_ENGINE_VERSION,
    MODEL_IDENTIFIER_V01,
    all_templates_canonical,
    compute_prompt_hash,
    generate_explanation,
)

EPOCH = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)
DERIVED_AT = datetime(2026, 6, 6, 12, 0, tzinfo=timezone.utc)


def _fixed_clock() -> datetime:
    return DERIVED_AT


def _make_evidence(
    *,
    detector: str = "maneuver_detection_v01",
    evidence_type: str = EVIDENCE_TYPE_MANEUVER,
    detector_event_id: str = "evt",
    days_offset: float = 0.0,
    payload: dict | None = None,
) -> DerivedEvidence:
    ep = EPOCH + timedelta(days=days_offset)
    return DerivedEvidence(
        evidence_id=compute_evidence_id(
            source_detector=detector, object_id=25544,
            detector_event_id=detector_event_id, event_epoch=ep,
            analysis_engine_version="0.1.0",
        ),
        object_id=25544,
        evidence_type=evidence_type,
        source_detector=detector,
        detector_event_id=detector_event_id,
        event_epoch=ep,
        honesty_payload=payload or {"detection_method_name": "test"},
        analysis_engine_version="0.1.0",
    )


def _build_agent_input(*evs: DerivedEvidence):  # type: ignore[no-untyped-def]
    catalog = EvidenceCatalog.from_evidence(list(evs), derived_at=DERIVED_AT)
    ctx = build_explanation_context(catalog, object_id=25544, clock=_fixed_clock)
    bundle = build_evidence_bundle(ctx, catalog, clock=_fixed_clock)
    return build_agent_input(
        bundle, declared_consumer_class="explanation_agent_v01",
        clock=_fixed_clock,
    )


# --- Caso empty bundle ----------------------------------------------


def test_generate_explanation_empty_bundle_no_claims() -> None:
    ai = _build_agent_input()
    art = generate_explanation(ai, clock=_fixed_clock)
    assert art.referenced_evidence_ids == []
    assert art.generation_metadata.n_evidence_processed == 0
    # Empty bundle: el agente no afirma nada; solo declara vacío fácticamente
    assert "empty" in art.explanation_text.lower()


# --- Caso con evidencia maneuver ----------------------------------


def test_generate_explanation_with_maneuver_evidence_emits_factual_line() -> None:
    maneuver_payload = {
        "detection_method_name": "element_jump_z_score_v1",
        "baseline_window_days": 14.0,
        "detection_threshold_sigma": 3.0,
        "n_baseline_samples": 5,
        "dominant_component": "mean_motion",
        "delta_t_days": 1.0,
        "delta_mean_motion_rev_day": 0.01,
        "delta_eccentricity": 0.0,
        "delta_inclination_deg": 0.0,
        "z_score_mean_motion": 4.5,
        "z_score_eccentricity": 0.1,
        "z_score_inclination": 0.2,
        "tle_content_hash_before": "a" * 64,
        "tle_content_hash_after": "b" * 64,
        "content_hash_source_before": "c" * 64,
        "content_hash_source_after": "d" * 64,
        "epoch_before": EPOCH.isoformat(),
        "epoch_after": (EPOCH + timedelta(days=1)).isoformat(),
    }
    ev = _make_evidence(
        detector="maneuver_detection_v01",
        evidence_type=EVIDENCE_TYPE_MANEUVER,
        payload=maneuver_payload,
    )
    ai = _build_agent_input(ev)
    art = generate_explanation(ai, clock=_fixed_clock)
    assert "maneuver_detection_v01" in art.explanation_text
    assert "dominant_component='mean_motion'" in art.explanation_text
    assert "is_apparent_not_confirmed=True" in art.explanation_text


# --- Caso con evidencia anomaly ----------------------------------


def test_generate_explanation_with_anomaly_evidence_emits_factual_line() -> None:
    anomaly_payload = {
        "detection_method_name": "self_baseline_z_score_v1",
        "baseline_window_days": 14.0,
        "threshold_sigma": 3.0,
        "n_baseline_samples": 5,
        "feature_name": "mean_motion",
        "observed_value": 15.51,
        "baseline_mean": 15.5,
        "baseline_stddev": 1e-5,
        "anomaly_score": 100.0,
    }
    ev = _make_evidence(
        detector="anomaly_detection_v01",
        evidence_type=EVIDENCE_TYPE_ANOMALY,
        payload=anomaly_payload,
        detector_event_id="anom-1",
    )
    ai = _build_agent_input(ev)
    art = generate_explanation(ai, clock=_fixed_clock)
    assert "anomaly_detection_v01" in art.explanation_text
    assert "feature='mean_motion'" in art.explanation_text
    assert "is_apparent_not_confirmed=True" in art.explanation_text


# --- Determinismo ------------------------------------------------


def test_generate_explanation_deterministic_across_runs() -> None:
    ev = _make_evidence(detector_event_id="evt-x")
    ai = _build_agent_input(ev)
    a = generate_explanation(ai, clock=_fixed_clock)
    b = generate_explanation(ai, clock=_fixed_clock)
    assert a.model_dump(mode="json") == b.model_dump(mode="json")


def test_generate_explanation_id_content_addressable() -> None:
    ev = _make_evidence(detector_event_id="evt-x")
    ai = _build_agent_input(ev)
    a = generate_explanation(ai, clock=_fixed_clock)
    b = generate_explanation(ai, clock=_fixed_clock)
    assert a.explanation_id == b.explanation_id


def test_generate_explanation_clock_only_affects_timestamps() -> None:
    ev = _make_evidence(detector_event_id="evt-x")
    ai = _build_agent_input(ev)

    def early() -> datetime:
        return datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)

    def late() -> datetime:
        return datetime(2027, 1, 1, 0, 0, tzinfo=timezone.utc)
    a = generate_explanation(ai, clock=early)
    b = generate_explanation(ai, clock=late)
    assert a.explanation_id == b.explanation_id
    assert a.explanation_text == b.explanation_text
    assert a.referenced_evidence_ids == b.referenced_evidence_ids
    assert a.generated_at != b.generated_at


# --- Trazabilidad y auditoría --------------------------------------


def test_audit_record_matches_artifact() -> None:
    ev = _make_evidence(detector_event_id="evt-x")
    ai = _build_agent_input(ev)
    art = generate_explanation(ai, clock=_fixed_clock)
    assert art.audit_record.explanation_id == art.explanation_id
    assert art.audit_record.agent_input_id == ai.agent_input_id
    assert art.audit_record.bundle_id == ai.bundle.bundle_id
    assert set(art.audit_record.evidence_ids_used) == set(art.referenced_evidence_ids)


def test_audit_prompt_hash_matches_helper() -> None:
    ev = _make_evidence(detector_event_id="evt-x")
    ai = _build_agent_input(ev)
    art = generate_explanation(ai, clock=_fixed_clock)
    expected = compute_prompt_hash(
        templates_canonical=all_templates_canonical(),
        engine_version=EXPLANATION_AGENT_ENGINE_VERSION,
    )
    assert art.audit_record.prompt_hash == expected
    assert art.generation_metadata.prompt_hash == expected


def test_audit_model_identifier_is_template_v01() -> None:
    ev = _make_evidence(detector_event_id="evt-x")
    ai = _build_agent_input(ev)
    art = generate_explanation(ai, clock=_fixed_clock)
    assert art.audit_record.model_identifier == MODEL_IDENTIFIER_V01
    assert art.generation_metadata.model_identifier == MODEL_IDENTIFIER_V01


def test_referenced_evidence_subset_of_bundle() -> None:
    a = _make_evidence(detector_event_id="a", days_offset=0)
    b = _make_evidence(detector_event_id="b", days_offset=1)
    ai = _build_agent_input(a, b)
    art = generate_explanation(ai, clock=_fixed_clock)
    bundle_ids = {bp.evidence_id for bp in ai.bundle.evidence_payloads}
    for evid in art.referenced_evidence_ids:
        assert evid in bundle_ids


def test_n_evidence_processed_matches_count() -> None:
    a = _make_evidence(detector_event_id="a", days_offset=0)
    b = _make_evidence(detector_event_id="b", days_offset=1)
    ai = _build_agent_input(a, b)
    art = generate_explanation(ai, clock=_fixed_clock)
    assert art.generation_metadata.n_evidence_processed == len(art.referenced_evidence_ids)


# --- Restricción: agente NO especula -----------------------------


def test_explanation_text_does_not_contain_interpretive_language() -> None:
    """ADR-0033 prohíbe especulación, hipótesis, lenguaje interpretativo."""
    ev = _make_evidence(detector_event_id="evt-x")
    ai = _build_agent_input(ev)
    art = generate_explanation(ai, clock=_fixed_clock)
    forbidden = (
        "probably", "likely", "suggests", "implies", "might mean",
        "could be", "maybe", "possibly", "indicates that",
        "suspicious", "dangerous", "malicious", "threat",
        "recommendation", "should investigate",
    )
    raw = art.explanation_text.lower()
    for word in forbidden:
        assert word not in raw, f"palabra prohibida en explanation_text: {word!r}"


def test_explanation_text_always_says_evidence_observed() -> None:
    """Las líneas siempre arrancan con 'Evidence', nunca con interpretación."""
    ev = _make_evidence(detector_event_id="evt-x")
    ai = _build_agent_input(ev)
    art = generate_explanation(ai, clock=_fixed_clock)
    if art.referenced_evidence_ids:
        for line in art.explanation_text.split("\n"):
            if line.strip():
                assert line.startswith("Evidence")


# --- Caso conjunction -------------------------------------------


def test_generate_explanation_with_conjunction_evidence() -> None:
    payload = {
        "miss_distance_km": 0.5,
        "relative_velocity_km_s": 14.0,
        "pc": 1e-5,
        "pc_method": "foster_1992_fast_approximation",
        "covariance_model_name": "tle_isotropic_spherical_v1",
        "covariance_baseline_sigma_km": 1.0,
        "covariance_growth_sigma_km_per_day": 1.0,
        "combined_sigma_at_tca_km": 1.41,
        "combined_hard_body_radius_km": 0.01,
        "sgp4_uncertainty_baseline_km": 3.0,
        "sgp4_uncertainty_growth_km_per_day": 3.0,
        "tca_resolution_minutes": 0.017,
        "tca_was_refined": True,
        "other_norad_cat_id": 99999,
        "detection_content_hash": "x" * 64,
        "side": "a",
    }
    ev = _make_evidence(
        detector="conjunction_detection_v01",
        evidence_type=EVIDENCE_TYPE_CONJUNCTION,
        payload=payload,
        detector_event_id="conj-1",
    )
    ai = _build_agent_input(ev)
    art = generate_explanation(ai, clock=_fixed_clock)
    assert "conjunction_detection_v01" in art.explanation_text
    assert "NORAD=99999" in art.explanation_text
    assert "is_apparent_not_confirmed=True" in art.explanation_text
