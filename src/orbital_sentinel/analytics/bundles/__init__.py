"""Verifiable Evidence Bundle Layer v0.1 (ADR-0031)."""

from orbital_sentinel.analytics.bundles.builder import build_evidence_bundle
from orbital_sentinel.analytics.bundles.hashing import (
    canonical_json,
    compute_bundle_payload_signature,
    compute_bundle_signature,
    compute_payload_hash,
)
from orbital_sentinel.analytics.bundles.models import (
    BUNDLE_ENGINE_VERSION,
    BUNDLE_SCHEMA_VERSION,
    VERIFIER_ENGINE_VERSION,
    BundledEvidence,
    BundleIntegrityFailure,
    BundleVerificationReport,
    EvidenceBundle,
    IntegrityFailureType,
)
from orbital_sentinel.analytics.bundles.verifier import verify_bundle

__all__ = [
    "BUNDLE_ENGINE_VERSION",
    "BUNDLE_SCHEMA_VERSION",
    "VERIFIER_ENGINE_VERSION",
    "BundleIntegrityFailure",
    "BundleVerificationReport",
    "BundledEvidence",
    "EvidenceBundle",
    "IntegrityFailureType",
    "build_evidence_bundle",
    "canonical_json",
    "compute_bundle_payload_signature",
    "compute_bundle_signature",
    "compute_payload_hash",
    "verify_bundle",
]
