"""Canonicalización SHA-256 del External Source Provenance Layer (ADR-0040)."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from datetime import datetime
from typing import Any


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def compute_external_source_record_id(
    *,
    source_provider: str,
    source_url: str,
    source_dataset_identifier: str,
    fetched_at: datetime,
    source_payload_hash: str,
    source_payload_size_bytes: int,
    source_content_type: str,
    source_layer_engine_version: str,
) -> str:
    """SHA-256 content-addressable de un ``ExternalSourceRecord``."""
    canonical = "|".join([
        source_provider,
        source_url,
        source_dataset_identifier,
        fetched_at.isoformat(),
        source_payload_hash,
        str(source_payload_size_bytes),
        source_content_type,
        source_layer_engine_version,
    ])
    return hashlib.sha256(canonical.encode("ascii")).hexdigest()


def compute_external_source_registry_hash(
    *,
    source_bundle_id: str,
    source_record_ids: Iterable[str],
    source_layer_engine_version: str,
) -> str:
    canonical = "|".join([
        source_bundle_id,
        ",".join(sorted(source_record_ids)),
        source_layer_engine_version,
    ])
    return hashlib.sha256(canonical.encode("ascii")).hexdigest()


def compute_source_verification_hash(
    *,
    registry_id: str,
    is_valid: bool,
    n_records_verified: int,
    n_findings: int,
    verifier_engine_version: str,
) -> str:
    canonical = "|".join([
        registry_id,
        "1" if is_valid else "0",
        str(n_records_verified),
        str(n_findings),
        verifier_engine_version,
    ])
    return hashlib.sha256(canonical.encode("ascii")).hexdigest()
