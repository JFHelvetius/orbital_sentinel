"""Explanation Agent v0.1 (ADR-0033)."""

from orbital_sentinel.analytics.explanation_agent.agent import generate_explanation
from orbital_sentinel.analytics.explanation_agent.models import (
    EXPLANATION_AGENT_ENGINE_VERSION,
    EXPLANATION_AGENT_SCHEMA_VERSION,
    GENERATION_METHOD_V01,
    MODEL_IDENTIFIER_V01,
    ExplanationArtifact,
    ExplanationAuditRecord,
    ExplanationGenerationMetadata,
    compute_explanation_id,
    compute_prompt_hash,
)
from orbital_sentinel.analytics.explanation_agent.templates import (
    TEMPLATE_ANOMALY_V01,
    TEMPLATE_CONJUNCTION_V01,
    TEMPLATE_MANEUVER_V01,
    TEMPLATE_UNKNOWN_V01,
    all_templates_canonical,
    format_evidence_line,
)

__all__ = [
    "EXPLANATION_AGENT_ENGINE_VERSION",
    "EXPLANATION_AGENT_SCHEMA_VERSION",
    "GENERATION_METHOD_V01",
    "MODEL_IDENTIFIER_V01",
    "TEMPLATE_ANOMALY_V01",
    "TEMPLATE_CONJUNCTION_V01",
    "TEMPLATE_MANEUVER_V01",
    "TEMPLATE_UNKNOWN_V01",
    "ExplanationArtifact",
    "ExplanationAuditRecord",
    "ExplanationGenerationMetadata",
    "all_templates_canonical",
    "compute_explanation_id",
    "compute_prompt_hash",
    "format_evidence_line",
    "generate_explanation",
]
