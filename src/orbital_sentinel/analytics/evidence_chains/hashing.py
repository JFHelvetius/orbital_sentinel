"""Canonicalización SHA-256 del Evidence Chain Layer (ADR-0037)."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from typing import Any


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def compute_chain_node_hash(
    *,
    link_type: str,
    link_id: str,
    link_signature: str,
    upstream_link_id: str,
) -> str:
    """SHA-256 sobre un nodo individual de la cadena."""
    canonical = "|".join([link_type, link_id, link_signature, upstream_link_id])
    return hashlib.sha256(canonical.encode("ascii")).hexdigest()


def compute_chain_hash(
    *,
    source_hypothesis_registry_id: str,
    node_hashes: Iterable[str],
    chain_layer_engine_version: str,
) -> str:
    """SHA-256 content-addressable del ``EvidenceChain`` global."""
    canonical = "|".join([
        source_hypothesis_registry_id,
        ",".join(node_hashes),
        chain_layer_engine_version,
    ])
    return hashlib.sha256(canonical.encode("ascii")).hexdigest()


def compute_chain_verification_hash(
    *,
    chain_id: str,
    is_valid: bool,
    n_nodes_verified: int,
    n_findings: int,
    verifier_engine_version: str,
) -> str:
    canonical = "|".join([
        chain_id,
        "1" if is_valid else "0",
        str(n_nodes_verified),
        str(n_findings),
        verifier_engine_version,
    ])
    return hashlib.sha256(canonical.encode("ascii")).hexdigest()
