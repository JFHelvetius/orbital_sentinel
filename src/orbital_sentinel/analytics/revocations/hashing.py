"""Canonicalización SHA-256 del Revocation Layer (ADR-0039)."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from typing import Any


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def compute_revocation_id(
    *,
    target_artifact_type: str,
    target_artifact_id: str,
    target_artifact_signature: str,
    revocation_reason: str,
    superseding_artifact_id: str,
    supporting_evidence_ids: Iterable[str],
    revocation_label: str,
    revocation_layer_engine_version: str,
) -> str:
    """SHA-256 content-addressable de un ``RevocationRecord``.

    Hashea ``revocation_label`` por separado para preservar Unicode arbitrario.
    """
    label_hash = hashlib.sha256(revocation_label.encode("utf-8")).hexdigest()
    canonical = "|".join([
        target_artifact_type,
        target_artifact_id,
        target_artifact_signature,
        revocation_reason,
        superseding_artifact_id,
        ",".join(sorted(supporting_evidence_ids)),
        label_hash,
        revocation_layer_engine_version,
    ])
    return hashlib.sha256(canonical.encode("ascii")).hexdigest()


def compute_revocation_ledger_hash(
    *,
    revocation_ids: Iterable[str],
    revocation_layer_engine_version: str,
) -> str:
    """SHA-256 content-addressable del ``RevocationLedger`` global."""
    canonical = "|".join([
        ",".join(sorted(revocation_ids)),
        revocation_layer_engine_version,
    ])
    return hashlib.sha256(canonical.encode("ascii")).hexdigest()


def compute_revocation_verification_hash(
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
