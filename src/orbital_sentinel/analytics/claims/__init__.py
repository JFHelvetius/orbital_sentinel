"""Verifiable Claim Layer v0.1 (ADR-0035)."""

from orbital_sentinel.analytics.claims.builder import build_claim_registry
from orbital_sentinel.analytics.claims.hashing import (
    canonical_json,
    compute_claim_id,
    compute_registry_hash,
    compute_verification_hash,
)
from orbital_sentinel.analytics.claims.models import (
    CLAIM_LAYER_ENGINE_VERSION,
    CLAIM_LAYER_SCHEMA_VERSION,
    CLAIM_VERIFIER_ENGINE_VERSION,
    SUPPORTED_SOURCE_MODELS_V01,
    ClaimRegistry,
    ClaimVerificationFinding,
    ClaimVerificationFindingType,
    ClaimVerificationReport,
    RegistryEmitReason,
    VerifiableClaim,
)
from orbital_sentinel.analytics.claims.verifier import verify_claim_registry

__all__ = [
    "CLAIM_LAYER_ENGINE_VERSION",
    "CLAIM_LAYER_SCHEMA_VERSION",
    "CLAIM_VERIFIER_ENGINE_VERSION",
    "SUPPORTED_SOURCE_MODELS_V01",
    "ClaimRegistry",
    "ClaimVerificationFinding",
    "ClaimVerificationFindingType",
    "ClaimVerificationReport",
    "RegistryEmitReason",
    "VerifiableClaim",
    "build_claim_registry",
    "canonical_json",
    "compute_claim_id",
    "compute_registry_hash",
    "compute_verification_hash",
    "verify_claim_registry",
]
