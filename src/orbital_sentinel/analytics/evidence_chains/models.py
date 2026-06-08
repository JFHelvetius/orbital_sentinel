"""Modelos del Evidence Chain Layer v1 (ADR-0037).

Materializa la cadena content-addressable que va desde la ``HypothesisRegistry``
hasta el primer evidence atómico, atravesando cada artefacto verificable:

    raw_evidence
      → evidence_bundle
      → agent_input
      → explanation_artifact
      → claim_registry
      → hypothesis_registry

Cada nodo registra ``link_type``, ``link_id`` y ``link_signature``. La cadena
NO embebe los payloads; ése es el rol de :class:`InvestigationCase` (ADR-0038).
La cadena prueba sólo *enlaces estructurales* entre identidades content-
addressable previamente verificadas en sus respectivas capas.
"""

from __future__ import annotations

from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from orbital_sentinel.analytics.evidence_chains.hashing import (
    compute_chain_hash,
    compute_chain_node_hash,
)

CHAIN_LAYER_SCHEMA_VERSION = "1.0.0"
CHAIN_LAYER_ENGINE_VERSION = "1.0.0"
CHAIN_VERIFIER_ENGINE_VERSION = "1.0.0"

ChainLinkType = Literal[
    "raw_evidence",
    "evidence_bundle",
    "agent_input",
    "explanation_artifact",
    "claim_registry",
    "hypothesis_registry",
]

CANONICAL_CHAIN_ORDER: tuple[ChainLinkType, ...] = (
    "raw_evidence",
    "evidence_bundle",
    "agent_input",
    "explanation_artifact",
    "claim_registry",
    "hypothesis_registry",
)
"""Orden canónico v1. Cualquier cadena que no respete este orden es inválida."""

ChainEmitReason = Literal["full_chain", "empty_chain"]

ChainVerificationFindingType = Literal[
    "chain_id_signature_alias_violation",
    "chain_node_signature_mismatch",
    "chain_node_id_mismatch_upstream",
    "chain_node_missing_link",
    "chain_node_unexpected_link_type",
    "chain_order_violation",
    "chain_node_hash_recompute_mismatch",
    "broken_link_at_evidence_bundle",
    "broken_link_at_agent_input",
    "broken_link_at_explanation_artifact",
    "broken_link_at_claim_registry",
    "broken_link_at_hypothesis_registry",
    "raw_evidence_set_mismatch",
    "chain_layer_engine_version_mismatch",
    "n_nodes_count_mismatch",
]


class EvidenceChainNode(BaseModel):
    """Eslabón individual de la cadena. NO contiene payloads."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    link_type: ChainLinkType
    link_id: str
    link_signature: str = Field(
        description="Content-hash del artefacto enlazado (igual a link_id en capas alias).",
    )
    upstream_link_id: str = Field(
        description=(
            "link_id del nodo inmediatamente upstream (capa más cercana a raw). "
            "Para `raw_evidence` debe ser una cadena vacía."
        ),
    )
    node_hash: str = Field(
        description="SHA-256 sobre (link_type, link_id, link_signature, upstream_link_id).",
    )

    @model_validator(mode="after")
    def _node_hash_must_recompute(self) -> EvidenceChainNode:
        expected = compute_chain_node_hash(
            link_type=self.link_type,
            link_id=self.link_id,
            link_signature=self.link_signature,
            upstream_link_id=self.upstream_link_id,
        )
        if self.node_hash != expected:
            raise ValueError(
                "node_hash does not match recomputed hash (ADR-0037); "
                f"got {self.node_hash!r}, expected {expected!r}."
            )
        return self


class EvidenceChain(BaseModel):
    """Cadena verificable extremo a extremo.

    Hard invariant: ``chain_id == chain_hash``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    chain_id: str
    chain_hash: str
    source_hypothesis_registry_id: str
    source_claim_registry_id: str
    source_explanation_id: str
    source_agent_input_id: str
    source_bundle_id: str
    raw_evidence_ids: list[str] = Field(
        description=(
            "Conjunto canónico-ordenado de evidence_ids primarios que "
            "originaron la cadena."
        ),
    )
    nodes: list[EvidenceChainNode]
    n_nodes: int = Field(ge=0)
    chain_emit_reason: ChainEmitReason
    schema_version: str = Field(default=CHAIN_LAYER_SCHEMA_VERSION)
    chain_layer_engine_version: str = Field(default=CHAIN_LAYER_ENGINE_VERSION)
    derived_at: AwareDatetime

    @model_validator(mode="after")
    def _chain_id_must_equal_hash(self) -> EvidenceChain:
        if self.chain_id != self.chain_hash:
            raise ValueError(
                "chain_id must be a strict alias of chain_hash (ADR-0037 CHAIN-001); "
                f"got chain_id={self.chain_id!r}, chain_hash={self.chain_hash!r}."
            )
        expected = compute_chain_hash(
            source_hypothesis_registry_id=self.source_hypothesis_registry_id,
            node_hashes=[n.node_hash for n in self.nodes],
            chain_layer_engine_version=self.chain_layer_engine_version,
        )
        if self.chain_hash != expected:
            raise ValueError(
                "chain_hash does not match recomputed hash (ADR-0037); "
                f"got {self.chain_hash!r}, expected {expected!r}."
            )
        return self


class ChainVerificationFinding(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    finding_type: ChainVerificationFindingType
    affected_id: str
    expected: str
    actual: str


class ChainVerificationReport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    chain_id: str
    is_valid: bool
    n_nodes_verified: int = Field(ge=0)
    n_findings: int = Field(ge=0)

    chain_id_is_alias_of_chain_hash: bool
    all_node_hashes_recompute_correctly: bool
    chain_order_canonical: bool
    all_links_consistent: bool
    raw_evidence_ids_match_bundle: bool
    chain_layer_engine_version_consistent: bool

    findings: list[ChainVerificationFinding]

    verification_hash: str
    verifier_engine_version: str = Field(default=CHAIN_VERIFIER_ENGINE_VERSION)
    schema_version: str = Field(default=CHAIN_LAYER_SCHEMA_VERSION)
    verified_at: AwareDatetime
