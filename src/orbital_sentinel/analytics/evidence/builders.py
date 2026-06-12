"""Builders que convierten outputs de detectores en :class:`DerivedEvidence`.

Sin interpretación. Sin agregación entre detectores. Sin scoring. Cada
builder es una función pura que toma el output canónico de su detector y
emite una lista de :class:`DerivedEvidence` con ``honesty_payload``
preservado.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from orbital_sentinel.analytics.anomalies.models import (
    AnomalyDetectionResult,
    AnomalyEvent,
)
from orbital_sentinel.analytics.conjunctions.storage import ConjunctionDetection
from orbital_sentinel.analytics.evidence.models import (
    CONSUMED_SOURCE_HASHES_KEY,
    EVIDENCE_TYPE_ANOMALY,
    EVIDENCE_TYPE_CONJUNCTION,
    EVIDENCE_TYPE_MANEUVER,
    DerivedEvidence,
    compute_evidence_id,
)
from orbital_sentinel.analytics.maneuvers.detector import (
    ManeuverDetectionResult,
    ManeuverEvent,
)

# --- Provenance por-evidencia (ADR-0043) -------------------------------


def _ordered_unique(hashes: Iterable[str]) -> list[str]:
    """Lista determinística (ordenada, deduplicada) de content_hash_source."""
    return sorted({h for h in hashes if h})


# --- Maneuver -----------------------------------------------------------


def build_maneuver_evidence(
    result: ManeuverDetectionResult,
) -> list[DerivedEvidence]:
    """Convierte cada :class:`ManeuverEvent` en :class:`DerivedEvidence`.

    Honesty payload preserva: detection_method_name, baseline_window_days,
    detection_threshold_sigma, n_baseline_samples, dominant_component,
    delta_t_days, z-scores.
    """
    out: list[DerivedEvidence] = []
    for event in result.events:
        out.append(_maneuver_event_to_evidence(event))
    return out


def _maneuver_event_to_evidence(event: ManeuverEvent) -> DerivedEvidence:
    detector_event_id = (
        f"{event.tle_content_hash_before}_{event.tle_content_hash_after}"
    )
    honesty_payload: dict[str, Any] = {
        "detection_method_name": event.detection_method_name,
        "baseline_window_days": event.baseline_window_days,
        "detection_threshold_sigma": event.detection_threshold_sigma,
        "n_baseline_samples": event.n_baseline_samples,
        "dominant_component": event.dominant_component,
        "delta_t_days": event.delta_t_days,
        "delta_mean_motion_rev_day": event.delta_mean_motion_rev_day,
        "delta_eccentricity": event.delta_eccentricity,
        "delta_inclination_deg": event.delta_inclination_deg,
        "z_score_mean_motion": event.z_score_mean_motion,
        "z_score_eccentricity": event.z_score_eccentricity,
        "z_score_inclination": event.z_score_inclination,
        "tle_content_hash_before": event.tle_content_hash_before,
        "tle_content_hash_after": event.tle_content_hash_after,
        "content_hash_source_before": event.content_hash_source_before,
        "content_hash_source_after": event.content_hash_source_after,
        "epoch_before": event.epoch_before.isoformat(),
        "epoch_after": event.epoch_after.isoformat(),
        # ADR-0043: los dos TLEs exactos que sustentan el salto detectado.
        CONSUMED_SOURCE_HASHES_KEY: _ordered_unique(
            [event.content_hash_source_before, event.content_hash_source_after]
        ),
    }
    engine = "0.1.0"  # ManeuverEvent no expone analysis_engine_version directamente;
    # usamos el valor del módulo (mismo SemVer del detector)
    evidence_id = compute_evidence_id(
        source_detector="maneuver_detection_v01",
        object_id=event.norad_cat_id,
        detector_event_id=detector_event_id,
        event_epoch=event.epoch_after,
        analysis_engine_version=engine,
    )
    return DerivedEvidence(
        evidence_id=evidence_id,
        object_id=event.norad_cat_id,
        evidence_type=EVIDENCE_TYPE_MANEUVER,
        source_detector="maneuver_detection_v01",
        detector_event_id=detector_event_id,
        event_epoch=event.epoch_after,
        honesty_payload=honesty_payload,
        analysis_engine_version=engine,
        is_apparent_not_confirmed=event.is_apparent_not_confirmed,
    )


# --- Anomaly -----------------------------------------------------------


def build_anomaly_evidence(
    result: AnomalyDetectionResult,
) -> list[DerivedEvidence]:
    """Convierte cada :class:`AnomalyEvent` en :class:`DerivedEvidence`.

    Honesty payload preserva: detection_method_name, baseline_window_days,
    threshold_sigma, n_baseline_samples, feature_name, observed_value,
    baseline_mean, baseline_stddev, anomaly_score.
    """
    out: list[DerivedEvidence] = []
    for event in result.events:
        out.append(_anomaly_event_to_evidence(event))
    return out


def _anomaly_event_to_evidence(event: AnomalyEvent) -> DerivedEvidence:
    detector_event_id = (
        f"{event.norad_cat_id}_{event.epoch_datetime.isoformat()}_"
        f"{event.feature_name}"
    )
    honesty_payload: dict[str, Any] = {
        "detection_method_name": event.detection_method_name,
        "baseline_window_days": event.baseline_window_days,
        "threshold_sigma": event.threshold_sigma,
        "n_baseline_samples": event.n_baseline_samples,
        "feature_name": event.feature_name,
        "observed_value": event.observed_value,
        "baseline_mean": event.baseline_mean,
        "baseline_stddev": event.baseline_stddev,
        "anomaly_score": event.anomaly_score,
        "object_id_string": event.object_id,
        "content_hash_source": event.content_hash_source,
        # ADR-0043: el TLE exacto del punto observado que sustenta la anomalía.
        CONSUMED_SOURCE_HASHES_KEY: _ordered_unique([event.content_hash_source]),
    }
    evidence_id = compute_evidence_id(
        source_detector="anomaly_detection_v01",
        object_id=event.norad_cat_id,
        detector_event_id=detector_event_id,
        event_epoch=event.epoch_datetime,
        analysis_engine_version=event.analysis_engine_version,
    )
    return DerivedEvidence(
        evidence_id=evidence_id,
        object_id=event.norad_cat_id,
        evidence_type=EVIDENCE_TYPE_ANOMALY,
        source_detector="anomaly_detection_v01",
        detector_event_id=detector_event_id,
        event_epoch=event.epoch_datetime,
        honesty_payload=honesty_payload,
        analysis_engine_version=event.analysis_engine_version,
        is_apparent_not_confirmed=event.is_apparent_not_confirmed,
    )


# --- Conjunction -------------------------------------------------------


def build_conjunction_evidence(
    detections: Iterable[ConjunctionDetection],
    *,
    only_for_norad: int | None = None,
) -> list[DerivedEvidence]:
    """Convierte detecciones de conjunción en :class:`DerivedEvidence`.

    Una conjunción involucra dos NORADs (``norad_a``, ``norad_b``). El
    builder emite **un** registro por lado: el objeto ``object_id=norad_X``
    con identificador único por lado. Si ``only_for_norad`` se especifica,
    solo se emite el lado coincidente.

    Honesty payload preserva: miss_distance_km, pc, covariance_model_name,
    pc_method, sgp4_uncertainty_baseline_km, combined_hard_body_radius_km,
    combined_sigma_at_tca_km, tca_resolution_minutes, tca_was_refined.
    """
    out: list[DerivedEvidence] = []
    for det in detections:
        for side, norad, other in [
            ("a", det.norad_a, det.norad_b),
            ("b", det.norad_b, det.norad_a),
        ]:
            if only_for_norad is not None and norad != only_for_norad:
                continue
            out.append(_conjunction_to_evidence(det, side, norad, other))
    return out


def _conjunction_to_evidence(
    det: ConjunctionDetection,
    side: str,
    object_norad: int,
    other_norad: int,
) -> DerivedEvidence:
    detector_event_id = f"{det.detection_content_hash}_side_{side}"
    # ADR-0043: el TLE exacto de ESTE lado (a/b) de la conjunción. El TLE del
    # otro objeto sustenta la evidencia del otro lado, no la de este object_id.
    side_content_hash_source = (
        det.element_a_content_hash_source
        if side == "a"
        else det.element_b_content_hash_source
    )
    honesty_payload: dict[str, Any] = {
        "miss_distance_km": det.miss_distance_km,
        "relative_velocity_km_s": det.relative_velocity_km_s,
        "pc": det.pc,
        "pc_method": det.pc_method,
        "covariance_model_name": det.covariance_model_name,
        "covariance_baseline_sigma_km": det.covariance_baseline_sigma_km,
        "covariance_growth_sigma_km_per_day": det.covariance_growth_sigma_km_per_day,
        "combined_sigma_at_tca_km": det.combined_sigma_at_tca_km,
        "combined_hard_body_radius_km": det.combined_hard_body_radius_km,
        "sgp4_uncertainty_baseline_km": det.sgp4_uncertainty_baseline_km,
        "sgp4_uncertainty_growth_km_per_day": det.sgp4_uncertainty_growth_km_per_day,
        "tca_resolution_minutes": det.tca_resolution_minutes,
        "tca_was_refined": det.tca_was_refined,
        # ADR-0044: anotación honesta co-orbiting (no filtra, contextualiza).
        "is_apparent_co_orbiting": det.is_apparent_co_orbiting,
        "co_orbiting_velocity_threshold_km_s": det.co_orbiting_velocity_threshold_km_s,
        "other_norad_cat_id": other_norad,
        "detection_content_hash": det.detection_content_hash,
        "side": side,
        "content_hash_source": side_content_hash_source,
        CONSUMED_SOURCE_HASHES_KEY: _ordered_unique([side_content_hash_source]),
    }
    evidence_id = compute_evidence_id(
        source_detector="conjunction_detection_v01",
        object_id=object_norad,
        detector_event_id=detector_event_id,
        event_epoch=det.tca,
        analysis_engine_version=det.analysis_engine_version,
    )
    return DerivedEvidence(
        evidence_id=evidence_id,
        object_id=object_norad,
        evidence_type=EVIDENCE_TYPE_CONJUNCTION,
        source_detector="conjunction_detection_v01",
        detector_event_id=detector_event_id,
        event_epoch=det.tca,
        honesty_payload=honesty_payload,
        analysis_engine_version=det.analysis_engine_version,
        is_apparent_not_confirmed=True,
    )
