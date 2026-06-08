"""Verifier del :class:`EvidenceChain` (ADR-0037).

Función pura. Nunca lanza. Siempre retorna :class:`ChainVerificationReport`.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import datetime, timezone

from orbital_sentinel.analytics.agent_contract import AgentInput
from orbital_sentinel.analytics.claims import ClaimRegistry
from orbital_sentinel.analytics.evidence_chains.hashing import (
    compute_chain_node_hash,
    compute_chain_verification_hash,
)
from orbital_sentinel.analytics.evidence_chains.models import (
    CANONICAL_CHAIN_ORDER,
    CHAIN_LAYER_ENGINE_VERSION,
    CHAIN_VERIFIER_ENGINE_VERSION,
    ChainVerificationFinding,
    ChainVerificationFindingType,
    ChainVerificationReport,
    EvidenceChain,
)
from orbital_sentinel.analytics.explanation_agent import ExplanationArtifact
from orbital_sentinel.analytics.hypotheses import HypothesisRegistry


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _f(
    ft: ChainVerificationFindingType, affected: str, expected: str, actual: str,
) -> ChainVerificationFinding:
    return ChainVerificationFinding(
        finding_type=ft, affected_id=affected, expected=expected, actual=actual,
    )


def verify_evidence_chain(
    chain: EvidenceChain,
    hypothesis_registry: HypothesisRegistry,
    claim_registry: ClaimRegistry,
    artifact: ExplanationArtifact,
    agent_input: AgentInput,
    *,
    clock: Callable[[], datetime] | None = None,
) -> ChainVerificationReport:
    """Recomputa cada eslabón y valida la coherencia extremo a extremo."""
    findings: list[ChainVerificationFinding] = []
    nodes = list(chain.nodes)
    bundle = agent_input.bundle

    # --- 1. Alias chain_id == chain_hash ------------------------------
    alias_ok = chain.chain_id == chain.chain_hash
    if not alias_ok:
        findings.append(_f(
            "chain_id_signature_alias_violation", "chain",
            chain.chain_hash, chain.chain_id,
        ))

    # --- 2. n_nodes ---------------------------------------------------
    n_ok = chain.n_nodes == len(nodes)
    if not n_ok:
        findings.append(_f(
            "n_nodes_count_mismatch", "chain", str(len(nodes)), str(chain.n_nodes),
        ))

    # --- 3. chain_layer_engine_version --------------------------------
    eng_ok = chain.chain_layer_engine_version == CHAIN_LAYER_ENGINE_VERSION
    if not eng_ok:
        findings.append(_f(
            "chain_layer_engine_version_mismatch", "chain",
            CHAIN_LAYER_ENGINE_VERSION, chain.chain_layer_engine_version,
        ))

    # --- 4. Recomputo de cada node_hash --------------------------------
    all_node_hashes_ok = True
    for node in nodes:
        expected = compute_chain_node_hash(
            link_type=node.link_type,
            link_id=node.link_id,
            link_signature=node.link_signature,
            upstream_link_id=node.upstream_link_id,
        )
        if node.node_hash != expected:
            all_node_hashes_ok = False
            findings.append(_f(
                "chain_node_hash_recompute_mismatch", node.link_id,
                expected, node.node_hash,
            ))

    # --- 5. Orden canónico --------------------------------------------
    chain_order_ok = True
    if chain.chain_emit_reason == "full_chain":
        if len(nodes) != len(CANONICAL_CHAIN_ORDER):
            chain_order_ok = False
            findings.append(_f(
                "chain_order_violation", "chain",
                f"{len(CANONICAL_CHAIN_ORDER)} nodes", f"{len(nodes)} nodes",
            ))
        else:
            for i, expected_type in enumerate(CANONICAL_CHAIN_ORDER):
                if nodes[i].link_type != expected_type:
                    chain_order_ok = False
                    findings.append(_f(
                        "chain_node_unexpected_link_type", nodes[i].link_id,
                        expected_type, nodes[i].link_type,
                    ))
    elif chain.chain_emit_reason == "empty_chain" and nodes:
        chain_order_ok = False
        findings.append(_f(
            "chain_order_violation", "chain", "0 nodes",
            f"{len(nodes)} nodes (emit_reason=empty_chain)",
        ))

    # --- 6. Consistencia de links --------------------------------------
    all_links_ok = True
    if chain.chain_emit_reason == "full_chain" and len(nodes) == len(CANONICAL_CHAIN_ORDER):
        # raw_evidence: link_id es sha256 sobre raw_evidence_ids
        raw_ids = sorted(chain.raw_evidence_ids)
        expected_raw = hashlib.sha256(
            ("|".join(raw_ids)).encode("ascii"),
        ).hexdigest()
        if nodes[0].link_id != expected_raw:
            all_links_ok = False
            findings.append(_f(
                "broken_link_at_evidence_bundle", nodes[0].link_id,
                expected_raw, nodes[0].link_id,
            ))
        # evidence_bundle
        if nodes[1].link_id != bundle.bundle_id:
            all_links_ok = False
            findings.append(_f(
                "broken_link_at_evidence_bundle", nodes[1].link_id,
                bundle.bundle_id, nodes[1].link_id,
            ))
        if nodes[1].link_signature != bundle.bundle_signature:
            all_links_ok = False
            findings.append(_f(
                "chain_node_signature_mismatch", nodes[1].link_id,
                bundle.bundle_signature, nodes[1].link_signature,
            ))
        if nodes[1].upstream_link_id != nodes[0].link_id:
            all_links_ok = False
            findings.append(_f(
                "chain_node_id_mismatch_upstream", nodes[1].link_id,
                nodes[0].link_id, nodes[1].upstream_link_id,
            ))
        # agent_input
        if nodes[2].link_id != agent_input.agent_input_id:
            all_links_ok = False
            findings.append(_f(
                "broken_link_at_agent_input", nodes[2].link_id,
                agent_input.agent_input_id, nodes[2].link_id,
            ))
        if nodes[2].upstream_link_id != nodes[1].link_id:
            all_links_ok = False
            findings.append(_f(
                "chain_node_id_mismatch_upstream", nodes[2].link_id,
                nodes[1].link_id, nodes[2].upstream_link_id,
            ))
        # explanation_artifact
        if nodes[3].link_id != artifact.explanation_id:
            all_links_ok = False
            findings.append(_f(
                "broken_link_at_explanation_artifact", nodes[3].link_id,
                artifact.explanation_id, nodes[3].link_id,
            ))
        if nodes[3].upstream_link_id != nodes[2].link_id:
            all_links_ok = False
            findings.append(_f(
                "chain_node_id_mismatch_upstream", nodes[3].link_id,
                nodes[2].link_id, nodes[3].upstream_link_id,
            ))
        # claim_registry
        if nodes[4].link_id != claim_registry.registry_id:
            all_links_ok = False
            findings.append(_f(
                "broken_link_at_claim_registry", nodes[4].link_id,
                claim_registry.registry_id, nodes[4].link_id,
            ))
        if nodes[4].link_signature != claim_registry.registry_hash:
            all_links_ok = False
            findings.append(_f(
                "chain_node_signature_mismatch", nodes[4].link_id,
                claim_registry.registry_hash, nodes[4].link_signature,
            ))
        if nodes[4].upstream_link_id != nodes[3].link_id:
            all_links_ok = False
            findings.append(_f(
                "chain_node_id_mismatch_upstream", nodes[4].link_id,
                nodes[3].link_id, nodes[4].upstream_link_id,
            ))
        # hypothesis_registry
        if nodes[5].link_id != hypothesis_registry.registry_id:
            all_links_ok = False
            findings.append(_f(
                "broken_link_at_hypothesis_registry", nodes[5].link_id,
                hypothesis_registry.registry_id, nodes[5].link_id,
            ))
        if nodes[5].link_signature != hypothesis_registry.registry_hash:
            all_links_ok = False
            findings.append(_f(
                "chain_node_signature_mismatch", nodes[5].link_id,
                hypothesis_registry.registry_hash, nodes[5].link_signature,
            ))
        if nodes[5].upstream_link_id != nodes[4].link_id:
            all_links_ok = False
            findings.append(_f(
                "chain_node_id_mismatch_upstream", nodes[5].link_id,
                nodes[4].link_id, nodes[5].upstream_link_id,
            ))

    # --- 7. raw_evidence_ids consistent with bundle ------------------
    actual_bundle_evs = sorted({bp.evidence_id for bp in bundle.evidence_payloads})
    raw_ok = sorted(chain.raw_evidence_ids) == actual_bundle_evs
    if not raw_ok:
        findings.append(_f(
            "raw_evidence_set_mismatch", "chain",
            ",".join(actual_bundle_evs[:3]) + "…",
            ",".join(sorted(chain.raw_evidence_ids)[:3]) + "…",
        ))

    is_valid = (
        alias_ok and n_ok and eng_ok
        and all_node_hashes_ok and chain_order_ok and all_links_ok and raw_ok
    )

    verification_hash = compute_chain_verification_hash(
        chain_id=chain.chain_id,
        is_valid=is_valid,
        n_nodes_verified=len(nodes),
        n_findings=len(findings),
        verifier_engine_version=CHAIN_VERIFIER_ENGINE_VERSION,
    )
    verified_at = (clock or _utc_now)()
    return ChainVerificationReport(
        chain_id=chain.chain_id,
        is_valid=is_valid,
        n_nodes_verified=len(nodes),
        n_findings=len(findings),
        chain_id_is_alias_of_chain_hash=alias_ok,
        all_node_hashes_recompute_correctly=all_node_hashes_ok,
        chain_order_canonical=chain_order_ok,
        all_links_consistent=all_links_ok,
        raw_evidence_ids_match_bundle=raw_ok,
        chain_layer_engine_version_consistent=eng_ok,
        findings=findings,
        verification_hash=verification_hash,
        verified_at=verified_at,
    )
