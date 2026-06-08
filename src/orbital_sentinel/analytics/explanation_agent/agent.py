"""Agente explicativo v0.1 (ADR-0033).

Toma un :class:`AgentInput` verificado y produce un
:class:`ExplanationArtifact` por concatenación determinista de plantillas
factuales sobre la evidencia embebida en el bundle.

Sin IA, sin ML, sin LLM, sin generación libre de texto, sin inferencia.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone

from orbital_sentinel.analytics.agent_contract import AgentInput
from orbital_sentinel.analytics.explanation_agent.models import (
    EXPLANATION_AGENT_ENGINE_VERSION,
    MODEL_IDENTIFIER_V01,
    ExplanationArtifact,
    ExplanationAuditRecord,
    ExplanationGenerationMetadata,
    compute_explanation_id,
    compute_prompt_hash,
)
from orbital_sentinel.analytics.explanation_agent.templates import (
    all_templates_canonical,
    format_evidence_line,
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def generate_explanation(
    agent_input: AgentInput,
    *,
    clock: Callable[[], datetime] | None = None,
) -> ExplanationArtifact:
    """Produce un :class:`ExplanationArtifact` deterministically derivado.

    Sin RNG. Sin wall clock en lógica semántica (solo en
    ``generated_at`` y ``audit_record.generation_timestamp`` que son
    metadata operacional).
    """
    bundle = agent_input.bundle

    # Orden estable: (event_epoch asc, evidence_id asc), igual que ADR-0030.
    sorted_payloads = sorted(
        bundle.evidence_payloads,
        key=lambda bp: (bp.derived_evidence.event_epoch, bp.evidence_id),
    )

    lines: list[str] = []
    evidence_ids_used: list[str] = []
    for bp in sorted_payloads:
        line = format_evidence_line(bp.derived_evidence)
        lines.append(line)
        evidence_ids_used.append(bp.evidence_id)

    if lines:
        explanation_text = "\n".join(lines)
    else:
        # Sin evidencia: NO se afirma nada. Mensaje factual mínimo.
        explanation_text = (
            f"Evidence catalog for object_id={bundle.object_id} is empty; "
            "no detections are referenced in this bundle."
        )

    prompt_hash = compute_prompt_hash(
        templates_canonical=all_templates_canonical(),
        engine_version=EXPLANATION_AGENT_ENGINE_VERSION,
    )
    explanation_id = compute_explanation_id(
        source_agent_input_id=agent_input.agent_input_id,
        source_bundle_id=bundle.bundle_id,
        prompt_hash=prompt_hash,
        explanation_engine_version=EXPLANATION_AGENT_ENGINE_VERSION,
    )
    timestamp = (clock or _utc_now)()
    audit = ExplanationAuditRecord(
        explanation_id=explanation_id,
        agent_input_id=agent_input.agent_input_id,
        bundle_id=bundle.bundle_id,
        evidence_ids_used=list(evidence_ids_used),
        generation_timestamp=timestamp,
        prompt_hash=prompt_hash,
        model_identifier=MODEL_IDENTIFIER_V01,
    )
    metadata = ExplanationGenerationMetadata(
        prompt_hash=prompt_hash,
        n_evidence_processed=len(evidence_ids_used),
    )
    return ExplanationArtifact(
        explanation_id=explanation_id,
        source_agent_input_id=agent_input.agent_input_id,
        source_bundle_id=bundle.bundle_id,
        referenced_evidence_ids=list(evidence_ids_used),
        explanation_text=explanation_text,
        generation_metadata=metadata,
        audit_record=audit,
        generated_at=timestamp,
    )
