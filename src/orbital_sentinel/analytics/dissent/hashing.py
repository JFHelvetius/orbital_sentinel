"""Canonicalización SHA-256 del Dissent Layer (ADR-0041)."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from typing import Any


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def compute_dissent_id(
    *,
    target_case_id: str,
    target_case_signature: str,
    dissent_index: int,
    dissent_type: str,
    dissent_basis_evidence_ids: Iterable[str],
    referenced_alternative_case_id: str,
    dissent_label: str,
    dissent_layer_engine_version: str,
) -> str:
    """SHA-256 content-addressable de un ``DissentRecord``."""
    label_hash = hashlib.sha256(dissent_label.encode("utf-8")).hexdigest()
    canonical = "|".join([
        target_case_id,
        target_case_signature,
        str(dissent_index),
        dissent_type,
        ",".join(sorted(dissent_basis_evidence_ids)),
        referenced_alternative_case_id,
        label_hash,
        dissent_layer_engine_version,
    ])
    return hashlib.sha256(canonical.encode("ascii")).hexdigest()


def compute_dissent_ledger_hash(
    *,
    target_case_id: str,
    target_case_signature: str,
    dissent_ids: Iterable[str],
    dissent_layer_engine_version: str,
) -> str:
    canonical = "|".join([
        target_case_id,
        target_case_signature,
        ",".join(sorted(dissent_ids)),
        dissent_layer_engine_version,
    ])
    return hashlib.sha256(canonical.encode("ascii")).hexdigest()


def compute_dissent_verification_hash(
    *,
    ledger_id: str,
    is_valid: bool,
    n_records_verified: int,
    n_findings: int,
    verifier_engine_version: str,
) -> str:
    canonical = "|".join([
        ledger_id,
        "1" if is_valid else "0",
        str(n_records_verified),
        str(n_findings),
        verifier_engine_version,
    ])
    return hashlib.sha256(canonical.encode("ascii")).hexdigest()
