"""External Source Provenance Layer v1 (ADR-0040)."""

from orbital_sentinel.analytics.external_sources.builder import (
    build_external_source_record,
    build_external_source_registry,
)
from orbital_sentinel.analytics.external_sources.hashing import (
    canonical_json,
    compute_external_source_record_id,
    compute_external_source_registry_hash,
    compute_source_verification_hash,
)
from orbital_sentinel.analytics.external_sources.models import (
    SOURCE_LAYER_ENGINE_VERSION,
    SOURCE_LAYER_SCHEMA_VERSION,
    SOURCE_VERIFIER_ENGINE_VERSION,
    ExternalSourceRecord,
    ExternalSourceRegistry,
    SourceContentType,
    SourceProvider,
    SourceRegistryEmitReason,
    SourceVerificationFinding,
    SourceVerificationFindingType,
    SourceVerificationReport,
)
from orbital_sentinel.analytics.external_sources.provenance import (
    derive_external_source_registry_for_bundle,
)
from orbital_sentinel.analytics.external_sources.verifier import (
    verify_external_source_registry,
)

__all__ = [
    "SOURCE_LAYER_ENGINE_VERSION",
    "SOURCE_LAYER_SCHEMA_VERSION",
    "SOURCE_VERIFIER_ENGINE_VERSION",
    "ExternalSourceRecord",
    "ExternalSourceRegistry",
    "SourceContentType",
    "SourceProvider",
    "SourceRegistryEmitReason",
    "SourceVerificationFinding",
    "SourceVerificationFindingType",
    "SourceVerificationReport",
    "build_external_source_record",
    "build_external_source_registry",
    "canonical_json",
    "compute_external_source_record_id",
    "compute_external_source_registry_hash",
    "compute_source_verification_hash",
    "derive_external_source_registry_for_bundle",
    "verify_external_source_registry",
]
