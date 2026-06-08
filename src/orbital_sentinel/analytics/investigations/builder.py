"""Builder del :class:`InvestigationCase` (ADR-0038).

Función pura. NO genera contenido nuevo: embebe payloads existentes y
materializa la coherencia cross-layer en un único artefacto portable.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone

from orbital_sentinel.analytics.agent_contract import AgentInput
from orbital_sentinel.analytics.bundles import EvidenceBundle
from orbital_sentinel.analytics.claims import ClaimRegistry
from orbital_sentinel.analytics.evidence_chains import EvidenceChain
from orbital_sentinel.analytics.explanation_agent import ExplanationArtifact
from orbital_sentinel.analytics.hypotheses import HypothesisRegistry
from orbital_sentinel.analytics.investigations.hashing import (
    compute_case_label_hash,
    compute_case_signature,
)
from orbital_sentinel.analytics.investigations.models import (
    CASE_LAYER_ENGINE_VERSION,
    CaseEmitReason,
    InvestigationCase,
)
from orbital_sentinel.core.errors import InvestigationCaseBuilderError


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _format_case_label(
    *, object_id: int, n_hypotheses: int, n_claims: int, n_evidence: int,
) -> str:
    return (
        f"Investigation case for object {object_id}: "
        f"{n_hypotheses} hypothesis(es) from {n_claims} claim(s) "
        f"over {n_evidence} evidence record(s)."
    )


def build_investigation_case(
    chain: EvidenceChain,
    *,
    hypothesis_registry: HypothesisRegistry,
    claim_registry: ClaimRegistry,
    artifact: ExplanationArtifact,
    agent_input: AgentInput,
    bundle: EvidenceBundle,
    clock: Callable[[], datetime] | None = None,
) -> InvestigationCase:
    """Empaqueta una investigación completa.

    Raises:
        InvestigationCaseBuilderError: si los identificadores cross-layer
            no comparten una raíz coherente.
    """
    if chain.source_hypothesis_registry_id != hypothesis_registry.registry_id:
        raise InvestigationCaseBuilderError(
            "chain.source_hypothesis_registry_id != hypothesis_registry.registry_id.",
        )
    if chain.source_claim_registry_id != claim_registry.registry_id:
        raise InvestigationCaseBuilderError(
            "chain.source_claim_registry_id != claim_registry.registry_id.",
        )
    if chain.source_explanation_id != artifact.explanation_id:
        raise InvestigationCaseBuilderError(
            "chain.source_explanation_id != artifact.explanation_id.",
        )
    if chain.source_agent_input_id != agent_input.agent_input_id:
        raise InvestigationCaseBuilderError(
            "chain.source_agent_input_id != agent_input.agent_input_id.",
        )
    if chain.source_bundle_id != bundle.bundle_id:
        raise InvestigationCaseBuilderError(
            "chain.source_bundle_id != bundle.bundle_id.",
        )
    if agent_input.bundle.bundle_id != bundle.bundle_id:
        raise InvestigationCaseBuilderError(
            "agent_input.bundle.bundle_id != bundle.bundle_id (cross-embedded mismatch).",
        )
    if hypothesis_registry.source_claim_registry_id != claim_registry.registry_id:
        raise InvestigationCaseBuilderError(
            "hypothesis_registry.source_claim_registry_id != claim_registry.registry_id.",
        )
    if claim_registry.source_explanation_id != artifact.explanation_id:
        raise InvestigationCaseBuilderError(
            "claim_registry.source_explanation_id != artifact.explanation_id.",
        )
    if artifact.source_agent_input_id != agent_input.agent_input_id:
        raise InvestigationCaseBuilderError(
            "artifact.source_agent_input_id != agent_input.agent_input_id.",
        )

    n_claims = claim_registry.n_claims
    n_hypotheses = hypothesis_registry.n_hypotheses
    n_evidence = bundle.n_evidence_payloads
    object_id = bundle.object_id
    case_label = _format_case_label(
        object_id=object_id, n_hypotheses=n_hypotheses,
        n_claims=n_claims, n_evidence=n_evidence,
    )
    case_label_hash = compute_case_label_hash(case_label)

    emit_reason: CaseEmitReason = (
        "empty_case" if n_evidence == 0 else "full_case"
    )

    case_signature = compute_case_signature(
        chain_id=chain.chain_id,
        hypothesis_registry_id=hypothesis_registry.registry_id,
        claim_registry_id=claim_registry.registry_id,
        explanation_id=artifact.explanation_id,
        agent_input_id=agent_input.agent_input_id,
        bundle_id=bundle.bundle_id,
        case_label_hash=case_label_hash,
        case_layer_engine_version=CASE_LAYER_ENGINE_VERSION,
    )
    derived_at = (clock or _utc_now)()
    return InvestigationCase(
        case_id=case_signature,
        case_signature=case_signature,
        case_label=case_label,
        case_label_hash=case_label_hash,
        referenced_chain_id=chain.chain_id,
        referenced_hypothesis_registry_id=hypothesis_registry.registry_id,
        referenced_claim_registry_id=claim_registry.registry_id,
        referenced_explanation_id=artifact.explanation_id,
        referenced_agent_input_id=agent_input.agent_input_id,
        referenced_bundle_id=bundle.bundle_id,
        chain=chain,
        hypothesis_registry=hypothesis_registry,
        claim_registry=claim_registry,
        explanation_artifact=artifact,
        agent_input=agent_input,
        evidence_bundle=bundle,
        case_emit_reason=emit_reason,
        derived_at=derived_at,
    )
