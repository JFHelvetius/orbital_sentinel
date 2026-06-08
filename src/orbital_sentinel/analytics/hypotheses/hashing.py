"""Canonicalización SHA-256 del Hypothesis Layer (ADR-0036).

ÚNICA fuente de hashing del módulo.
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


def compute_hypothesis_id(
    *,
    source_claim_registry_id: str,
    hypothesis_index: int,
    grouping_key: str,
    supporting_claim_ids: Iterable[str],
    hypothesis_label: str,
    hypothesis_layer_engine_version: str,
) -> str:
    """SHA-256 content-addressable de una ``Hypothesis``.

    Hashea ``hypothesis_label`` por separado para preservar Unicode arbitrario;
    el envelope final es ASCII por compatibilidad con el resto de la arquitectura.
    """
    label_hash = hashlib.sha256(hypothesis_label.encode("utf-8")).hexdigest()
    canonical = "|".join([
        source_claim_registry_id,
        str(hypothesis_index),
        grouping_key,
        ",".join(sorted(supporting_claim_ids)),
        label_hash,
        hypothesis_layer_engine_version,
    ])
    return hashlib.sha256(canonical.encode("ascii")).hexdigest()


def compute_hypothesis_registry_hash(
    *,
    source_claim_registry_id: str,
    source_bundle_id: str,
    source_agent_input_id: str,
    hypothesis_ids: Iterable[str],
    hypothesis_layer_engine_version: str,
) -> str:
    """SHA-256 content-addressable de un ``HypothesisRegistry``."""
    canonical = "|".join([
        source_claim_registry_id,
        source_bundle_id,
        source_agent_input_id,
        ",".join(sorted(hypothesis_ids)),
        hypothesis_layer_engine_version,
    ])
    return hashlib.sha256(canonical.encode("ascii")).hexdigest()


def compute_hypothesis_verification_hash(
    *,
    registry_id: str,
    is_valid: bool,
    n_hypotheses_verified: int,
    n_findings: int,
    verifier_engine_version: str,
) -> str:
    """SHA-256 content-addressable del ``HypothesisVerificationReport``.

    Excluye ``verified_at`` (metadata operacional).
    """
    canonical = "|".join([
        registry_id,
        "1" if is_valid else "0",
        str(n_hypotheses_verified),
        str(n_findings),
        verifier_engine_version,
    ])
    return hashlib.sha256(canonical.encode("ascii")).hexdigest()
