"""Explanation Context Layer v0.1 (ADR-0030)."""

from orbital_sentinel.analytics.explanation.builder import (
    build_explanation_context,
)
from orbital_sentinel.analytics.explanation.models import (
    CANONICAL_DETECTORS_V01,
    EVIDENCE_TYPES_V01,
    EXPLANATION_LAYER_ENGINE_VERSION,
    EXPLANATION_LAYER_SCHEMA_VERSION,
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

__all__ = [
    "CANONICAL_DETECTORS_V01",
    "EVIDENCE_TYPES_V01",
    "EXPLANATION_LAYER_ENGINE_VERSION",
    "EXPLANATION_LAYER_SCHEMA_VERSION",
    "CanonicalDetector",
    "ExplanationContext",
    "ExplanationDetectorSummary",
    "ExplanationEvidenceReference",
    "ExplanationTimeline",
    "ExplanationTimelineEntry",
    "build_explanation_context",
    "compute_context_id",
    "compute_payload_hash",
    "compute_source_catalog_signature",
]
