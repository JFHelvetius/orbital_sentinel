"""Plantillas deterministas de explicación por evidencia (ADR-0033).

El agente jamás genera narrativa libre. Cada plantilla produce una afirmación
factual del patrón "Evidence says X", extrayendo SOLO campos ya presentes
en el ``honesty_payload`` del :class:`DerivedEvidence`. Sin inferencia,
sin especulación, sin hipótesis.
"""

from __future__ import annotations

from typing import Any

from orbital_sentinel.analytics.evidence.models import DerivedEvidence

# --- Identificadores machine-readable ---------------------------------

TEMPLATE_MANEUVER_V01 = (
    "Evidence {evidence_id_short}: detector 'maneuver_detection_v01' observed "
    "transition from epoch {epoch_before} to {epoch_after} "
    "with dominant_component='{dominant}', "
    "delta_mean_motion_rev_day={dmm}, delta_eccentricity={de}, "
    "delta_inclination_deg={di}, "
    "z_scores=(mean_motion={zn}, eccentricity={ze}, inclination={zi}); "
    "baseline_window_days={W}, detection_threshold_sigma={S}, "
    "n_baseline_samples={N}; is_apparent_not_confirmed=True."
)

TEMPLATE_ANOMALY_V01 = (
    "Evidence {evidence_id_short}: detector 'anomaly_detection_v01' observed "
    "feature='{feature}' value={observed} at epoch {epoch} against baseline "
    "(mean={mean}, stddev={stddev}); z_score={score}; "
    "baseline_window_days={W}, threshold_sigma={S}, n_baseline_samples={N}; "
    "is_apparent_not_confirmed=True."
)

TEMPLATE_CONJUNCTION_V01 = (
    "Evidence {evidence_id_short}: detector 'conjunction_detection_v01' "
    "identified conjunction with NORAD={other_norad} at TCA={tca}; "
    "miss_distance_km={miss}, Pc={pc} "
    "(method='{pc_method}', covariance_model='{cov_model}'); "
    "combined_hard_body_radius_km={hbr}, combined_sigma_at_tca_km={sigma}; "
    "is_apparent_not_confirmed=True."
)

TEMPLATE_UNKNOWN_V01 = (
    "Evidence {evidence_id_short}: detector '{detector}' produced evidence_type="
    "'{evidence_type}' at epoch {epoch}; honesty_payload preserved by reference; "
    "is_apparent_not_confirmed=True."
)


def _short(evidence_id: str) -> str:
    return f"{evidence_id[:12]}…"


def _format_maneuver(evidence: DerivedEvidence) -> str:
    p: dict[str, Any] = evidence.honesty_payload
    return TEMPLATE_MANEUVER_V01.format(
        evidence_id_short=_short(evidence.evidence_id),
        epoch_before=p.get("epoch_before", "unknown"),
        epoch_after=p.get("epoch_after", "unknown"),
        dominant=p.get("dominant_component", "unknown"),
        dmm=p.get("delta_mean_motion_rev_day", "unknown"),
        de=p.get("delta_eccentricity", "unknown"),
        di=p.get("delta_inclination_deg", "unknown"),
        zn=p.get("z_score_mean_motion", "unknown"),
        ze=p.get("z_score_eccentricity", "unknown"),
        zi=p.get("z_score_inclination", "unknown"),
        W=p.get("baseline_window_days", "unknown"),
        S=p.get("detection_threshold_sigma", "unknown"),
        N=p.get("n_baseline_samples", "unknown"),
    )


def _format_anomaly(evidence: DerivedEvidence) -> str:
    p: dict[str, Any] = evidence.honesty_payload
    return TEMPLATE_ANOMALY_V01.format(
        evidence_id_short=_short(evidence.evidence_id),
        feature=p.get("feature_name", "unknown"),
        observed=p.get("observed_value", "unknown"),
        epoch=evidence.event_epoch.isoformat(),
        mean=p.get("baseline_mean", "unknown"),
        stddev=p.get("baseline_stddev", "unknown"),
        score=p.get("anomaly_score", "unknown"),
        W=p.get("baseline_window_days", "unknown"),
        S=p.get("threshold_sigma", "unknown"),
        N=p.get("n_baseline_samples", "unknown"),
    )


def _format_conjunction(evidence: DerivedEvidence) -> str:
    p: dict[str, Any] = evidence.honesty_payload
    return TEMPLATE_CONJUNCTION_V01.format(
        evidence_id_short=_short(evidence.evidence_id),
        other_norad=p.get("other_norad_cat_id", "unknown"),
        tca=evidence.event_epoch.isoformat(),
        miss=p.get("miss_distance_km", "unknown"),
        pc=p.get("pc", "unknown"),
        pc_method=p.get("pc_method", "unknown"),
        cov_model=p.get("covariance_model_name", "unknown"),
        hbr=p.get("combined_hard_body_radius_km", "unknown"),
        sigma=p.get("combined_sigma_at_tca_km", "unknown"),
    )


def _format_unknown(evidence: DerivedEvidence) -> str:
    return TEMPLATE_UNKNOWN_V01.format(
        evidence_id_short=_short(evidence.evidence_id),
        detector=evidence.source_detector,
        evidence_type=evidence.evidence_type,
        epoch=evidence.event_epoch.isoformat(),
    )


def format_evidence_line(evidence: DerivedEvidence) -> str:
    """Produce una línea factual derivada exclusivamente del honesty_payload."""
    if evidence.evidence_type == "maneuver_jump_detected":
        return _format_maneuver(evidence)
    if evidence.evidence_type == "anomaly_observed":
        return _format_anomaly(evidence)
    if evidence.evidence_type == "conjunction_detected":
        return _format_conjunction(evidence)
    return _format_unknown(evidence)


def all_templates_canonical() -> str:
    """Concatenación canónica de TODAS las plantillas usadas, para prompt_hash.

    Determinístico. Cualquier cambio en alguna plantilla resulta en un
    prompt_hash distinto, permitiendo detección externa de drift de versión.
    """
    return "|".join([
        TEMPLATE_MANEUVER_V01,
        TEMPLATE_ANOMALY_V01,
        TEMPLATE_CONJUNCTION_V01,
        TEMPLATE_UNKNOWN_V01,
    ])
