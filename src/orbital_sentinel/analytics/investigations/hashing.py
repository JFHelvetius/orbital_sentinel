"""Canonicalización SHA-256 del Investigation Case Layer (ADR-0038)."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def compute_case_signature(
    *,
    chain_id: str,
    hypothesis_registry_id: str,
    claim_registry_id: str,
    explanation_id: str,
    agent_input_id: str,
    bundle_id: str,
    case_label_hash: str,
    case_layer_engine_version: str,
) -> str:
    """SHA-256 sobre los identificadores content-addressable embebidos."""
    canonical = "|".join([
        chain_id,
        hypothesis_registry_id,
        claim_registry_id,
        explanation_id,
        agent_input_id,
        bundle_id,
        case_label_hash,
        case_layer_engine_version,
    ])
    return hashlib.sha256(canonical.encode("ascii")).hexdigest()


def compute_case_label_hash(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def compute_case_verification_hash(
    *,
    case_id: str,
    is_valid: bool,
    n_artifacts_verified: int,
    n_findings: int,
    verifier_engine_version: str,
) -> str:
    canonical = "|".join([
        case_id,
        "1" if is_valid else "0",
        str(n_artifacts_verified),
        str(n_findings),
        verifier_engine_version,
    ])
    return hashlib.sha256(canonical.encode("ascii")).hexdigest()
