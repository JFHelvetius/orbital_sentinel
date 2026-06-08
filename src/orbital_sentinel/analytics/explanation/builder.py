"""Builder del :class:`ExplanationContext` (ADR-0030).

Función pura, deterministica, sin RNG, sin wall clock en lógica
semántica (solo ``derived_at`` como metadata operacional).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from typing import cast

from orbital_sentinel.analytics.evidence.models import EvidenceCatalog
from orbital_sentinel.analytics.explanation.models import (
    CANONICAL_DETECTORS_V01,
    EXPLANATION_LAYER_ENGINE_VERSION,
    CanonicalDetector,
    ExplanationContext,
    ExplanationDetectorSummary,
    ExplanationEvidenceReference,
    ExplanationTimeline,
    ExplanationTimelineEntry,
    compute_context_id,
    compute_payload_hash,
    compute_source_catalog_signature,
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def build_explanation_context(
    catalog: EvidenceCatalog,
    *,
    object_id: int,
    clock: Callable[[], datetime] | None = None,
) -> ExplanationContext:
    """Proyecta un :class:`EvidenceCatalog` filtrado al ``object_id``
    en una :class:`ExplanationContext` deterministica.

    El ``clock`` solo se usa para ``derived_at`` (metadata operacional);
    ``context_id`` y ``source_catalog_signature`` son content-addressable
    y no dependen del instante de construcción.
    """
    # 1. Filtrar el catálogo al objeto pedido.
    object_evidence = catalog.list_by_norad(object_id)

    # 2. Orden estable: (event_epoch asc, evidence_id asc).
    object_evidence = sorted(
        object_evidence,
        key=lambda ev: (ev.event_epoch, ev.evidence_id),
    )

    # 3. Firmas content-addressable.
    sig = compute_source_catalog_signature(
        ev.evidence_id for ev in object_evidence
    )
    context_id = compute_context_id(
        object_id=object_id,
        explanation_engine_version=EXPLANATION_LAYER_ENGINE_VERSION,
        source_catalog_signature=sig,
    )

    # 4. Hashes de payload por evidencia (preservación de integridad).
    payload_hashes: dict[str, str] = {
        ev.evidence_id: compute_payload_hash(ev.honesty_payload)
        for ev in object_evidence
    }

    # 5. Referencias por evidencia.
    references = [
        ExplanationEvidenceReference(
            evidence_id=ev.evidence_id,
            object_id=ev.object_id,
            event_epoch=ev.event_epoch,
            source_detector=ev.source_detector,
            evidence_type=ev.evidence_type,
            detector_event_id=ev.detector_event_id,
            honesty_payload_hash=payload_hashes[ev.evidence_id],
            analysis_engine_version=ev.analysis_engine_version,
        )
        for ev in object_evidence
    ]

    # 6. Timeline consolidado.
    timeline_entries = [
        ExplanationTimelineEntry(
            epoch=ev.event_epoch,
            evidence_id=ev.evidence_id,
            source_detector=ev.source_detector,
            evidence_type=ev.evidence_type,
            honesty_payload_hash=payload_hashes[ev.evidence_id],
        )
        for ev in object_evidence
    ]
    timeline = ExplanationTimeline(
        entries=timeline_entries,
        n_entries=len(timeline_entries),
        first_epoch=timeline_entries[0].epoch if timeline_entries else None,
        last_epoch=timeline_entries[-1].epoch if timeline_entries else None,
    )

    # 7. Cobertura temporal global.
    if object_evidence:
        coverage_start = object_evidence[0].event_epoch
        coverage_end = object_evidence[-1].event_epoch
        coverage_duration = (coverage_end - coverage_start).total_seconds()
    else:
        coverage_start = None
        coverage_end = None
        coverage_duration = None

    # 8. Counts por tipo (solo tipos observados, claves alfabéticas).
    type_counts: dict[str, int] = {}
    for ev in object_evidence:
        type_counts[ev.evidence_type] = type_counts.get(ev.evidence_type, 0) + 1
    evidence_type_counts = {k: type_counts[k] for k in sorted(type_counts)}

    # 9. Detector summaries: SIEMPRE los 3 canónicos en orden alfabético.
    detector_summaries: list[ExplanationDetectorSummary] = []
    for det_name in CANONICAL_DETECTORS_V01:
        det_evs = [ev for ev in object_evidence if ev.source_detector == det_name]
        det_evs.sort(key=lambda ev: (ev.event_epoch, ev.evidence_id))
        det_breakdown_raw: dict[str, int] = {}
        for ev in det_evs:
            det_breakdown_raw[ev.evidence_type] = (
                det_breakdown_raw.get(ev.evidence_type, 0) + 1
            )
        det_breakdown = {k: det_breakdown_raw[k] for k in sorted(det_breakdown_raw)}
        detector_summaries.append(
            ExplanationDetectorSummary(
                source_detector=cast(CanonicalDetector, det_name),
                n_events=len(det_evs),
                first_event_epoch=det_evs[0].event_epoch if det_evs else None,
                last_event_epoch=det_evs[-1].event_epoch if det_evs else None,
                evidence_ids=[ev.evidence_id for ev in det_evs],
                evidence_type_breakdown=det_breakdown,
            )
        )

    derived_at = (clock or _utc_now)()
    return ExplanationContext(
        object_id=object_id,
        context_id=context_id,
        source_catalog_signature=sig,
        n_evidence_total=len(object_evidence),
        coverage_window_start=coverage_start,
        coverage_window_end=coverage_end,
        coverage_duration_seconds=coverage_duration,
        evidence_type_counts=evidence_type_counts,
        detector_summaries=detector_summaries,
        timeline=timeline,
        evidence_references=references,
        derived_at=derived_at,
    )
