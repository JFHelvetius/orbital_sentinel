"""Builder del :class:`EvidenceChain` (ADR-0037).

Función pura. No genera contenido nuevo: materializa enlaces estructurales
entre artefactos content-addressable ya existentes.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone

from orbital_sentinel.analytics.agent_contract import AgentInput
from orbital_sentinel.analytics.claims import ClaimRegistry
from orbital_sentinel.analytics.evidence_chains.hashing import (
    compute_chain_hash,
    compute_chain_node_hash,
)
from orbital_sentinel.analytics.evidence_chains.models import (
    CHAIN_LAYER_ENGINE_VERSION,
    ChainEmitReason,
    EvidenceChain,
    EvidenceChainNode,
)
from orbital_sentinel.analytics.explanation_agent import ExplanationArtifact
from orbital_sentinel.analytics.hypotheses import HypothesisRegistry
from orbital_sentinel.core.errors import EvidenceChainBuilderError


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _make_node(
    *, link_type: str, link_id: str, link_signature: str, upstream_link_id: str,
) -> EvidenceChainNode:
    nh = compute_chain_node_hash(
        link_type=link_type,
        link_id=link_id,
        link_signature=link_signature,
        upstream_link_id=upstream_link_id,
    )
    return EvidenceChainNode(
        link_type=link_type,  # type: ignore[arg-type]
        link_id=link_id,
        link_signature=link_signature,
        upstream_link_id=upstream_link_id,
        node_hash=nh,
    )


def build_evidence_chain(
    hypothesis_registry: HypothesisRegistry,
    claim_registry: ClaimRegistry,
    artifact: ExplanationArtifact,
    agent_input: AgentInput,
    *,
    clock: Callable[[], datetime] | None = None,
) -> EvidenceChain:
    """Materializa la cadena verificable extremo a extremo.

    Raises:
        EvidenceChainBuilderError: si los identificadores cross-layer no
            son coherentes (typically un swap entre artefactos).
    """
    bundle = agent_input.bundle
    # Coherencia cross-layer
    if hypothesis_registry.source_claim_registry_id != claim_registry.registry_id:
        raise EvidenceChainBuilderError(
            "hypothesis_registry.source_claim_registry_id does not match "
            "claim_registry.registry_id.",
        )
    if claim_registry.source_explanation_id != artifact.explanation_id:
        raise EvidenceChainBuilderError(
            "claim_registry.source_explanation_id does not match "
            "artifact.explanation_id.",
        )
    if artifact.source_agent_input_id != agent_input.agent_input_id:
        raise EvidenceChainBuilderError(
            "artifact.source_agent_input_id does not match agent_input.agent_input_id.",
        )
    if agent_input.bundle.bundle_id != bundle.bundle_id:
        raise EvidenceChainBuilderError(
            "agent_input.bundle.bundle_id mismatch (internal).",
        )

    raw_evidence_ids = sorted({bp.evidence_id for bp in bundle.evidence_payloads})

    nodes: list[EvidenceChainNode] = []
    if not raw_evidence_ids:
        emit_reason: ChainEmitReason = "empty_chain"
    else:
        emit_reason = "full_chain"
        # Nodo 0: raw_evidence (link_id = hash sintético sobre el conjunto)
        # Para preservar reproducibilidad, usamos un id determinístico.
        import hashlib
        raw_set_id = hashlib.sha256(
            ("|".join(raw_evidence_ids)).encode("ascii"),
        ).hexdigest()
        nodes.append(_make_node(
            link_type="raw_evidence",
            link_id=raw_set_id,
            link_signature=raw_set_id,
            upstream_link_id="",
        ))
        nodes.append(_make_node(
            link_type="evidence_bundle",
            link_id=bundle.bundle_id,
            link_signature=bundle.bundle_signature,
            upstream_link_id=nodes[-1].link_id,
        ))
        nodes.append(_make_node(
            link_type="agent_input",
            link_id=agent_input.agent_input_id,
            link_signature=agent_input.agent_input_id,
            upstream_link_id=nodes[-1].link_id,
        ))
        nodes.append(_make_node(
            link_type="explanation_artifact",
            link_id=artifact.explanation_id,
            link_signature=artifact.explanation_id,
            upstream_link_id=nodes[-1].link_id,
        ))
        nodes.append(_make_node(
            link_type="claim_registry",
            link_id=claim_registry.registry_id,
            link_signature=claim_registry.registry_hash,
            upstream_link_id=nodes[-1].link_id,
        ))
        nodes.append(_make_node(
            link_type="hypothesis_registry",
            link_id=hypothesis_registry.registry_id,
            link_signature=hypothesis_registry.registry_hash,
            upstream_link_id=nodes[-1].link_id,
        ))

    chain_hash = compute_chain_hash(
        source_hypothesis_registry_id=hypothesis_registry.registry_id,
        node_hashes=[n.node_hash for n in nodes],
        chain_layer_engine_version=CHAIN_LAYER_ENGINE_VERSION,
    )
    derived_at = (clock or _utc_now)()
    return EvidenceChain(
        chain_id=chain_hash,
        chain_hash=chain_hash,
        source_hypothesis_registry_id=hypothesis_registry.registry_id,
        source_claim_registry_id=claim_registry.registry_id,
        source_explanation_id=artifact.explanation_id,
        source_agent_input_id=agent_input.agent_input_id,
        source_bundle_id=bundle.bundle_id,
        raw_evidence_ids=raw_evidence_ids,
        nodes=nodes,
        n_nodes=len(nodes),
        chain_emit_reason=emit_reason,
        derived_at=derived_at,
    )
