"""Canonicalización SHA-256 del Claim Layer (ADR-0035).

ÚNICA fuente de hashing del módulo. Ningún otro archivo (`builder`,
`verifier`, `models`, `cli`) debe computar SHA-256 ad-hoc.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from typing import Any


def canonical_json(obj: Any) -> str:
    """JSON canónico: ``sort_keys=True``, separadores compactos, UTF-8."""
    return json.dumps(
        obj,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def compute_claim_id(
    *,
    source_explanation_id: str,
    claim_index: int,
    supporting_evidence_ids: Iterable[str],
    claim_text: str,
    claim_layer_engine_version: str,
) -> str:
    """SHA-256 content-addressable de un ``VerifiableClaim``.

    Hashea ``claim_text`` por separado para preservar Unicode arbitrario;
    el envelope final es ASCII por compatibilidad con el resto de la
    arquitectura.
    """
    text_hash = hashlib.sha256(claim_text.encode("utf-8")).hexdigest()
    canonical = "|".join([
        source_explanation_id,
        str(claim_index),
        ",".join(sorted(supporting_evidence_ids)),
        text_hash,
        claim_layer_engine_version,
    ])
    return hashlib.sha256(canonical.encode("ascii")).hexdigest()


def compute_registry_hash(
    *,
    source_explanation_id: str,
    source_bundle_id: str,
    source_agent_input_id: str,
    claim_ids: Iterable[str],
    claim_layer_engine_version: str,
) -> str:
    """SHA-256 content-addressable de un ``ClaimRegistry``.

    Independiente del orden de input por sort previo.
    """
    canonical = "|".join([
        source_explanation_id,
        source_bundle_id,
        source_agent_input_id,
        ",".join(sorted(claim_ids)),
        claim_layer_engine_version,
    ])
    return hashlib.sha256(canonical.encode("ascii")).hexdigest()


def compute_verification_hash(
    *,
    registry_id: str,
    is_valid: bool,
    n_claims_verified: int,
    n_findings: int,
    verifier_engine_version: str,
) -> str:
    """SHA-256 content-addressable del ``ClaimVerificationReport``.

    Excluye ``verified_at`` (metadata operacional).
    """
    canonical = "|".join([
        registry_id,
        "1" if is_valid else "0",
        str(n_claims_verified),
        str(n_findings),
        verifier_engine_version,
    ])
    return hashlib.sha256(canonical.encode("ascii")).hexdigest()
