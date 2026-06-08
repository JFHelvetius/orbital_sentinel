"""Hypothesis Layer v1 (ADR-0036)."""

from orbital_sentinel.analytics.hypotheses.builder import (
    HYPOTHESIS_MODEL_IDENTIFIER_V1,
    build_hypothesis_registry,
)
from orbital_sentinel.analytics.hypotheses.hashing import (
    canonical_json,
    compute_hypothesis_id,
    compute_hypothesis_registry_hash,
    compute_hypothesis_verification_hash,
)
from orbital_sentinel.analytics.hypotheses.models import (
    HYPOTHESIS_LAYER_ENGINE_VERSION,
    HYPOTHESIS_LAYER_SCHEMA_VERSION,
    HYPOTHESIS_VERIFIER_ENGINE_VERSION,
    SUPPORTED_HYPOTHESIS_MODELS_V1,
    Hypothesis,
    HypothesisRegistry,
    HypothesisRegistryEmitReason,
    HypothesisVerificationFinding,
    HypothesisVerificationFindingType,
    HypothesisVerificationReport,
)
from orbital_sentinel.analytics.hypotheses.verifier import verify_hypothesis_registry

__all__ = [
    "HYPOTHESIS_LAYER_ENGINE_VERSION",
    "HYPOTHESIS_LAYER_SCHEMA_VERSION",
    "HYPOTHESIS_MODEL_IDENTIFIER_V1",
    "HYPOTHESIS_VERIFIER_ENGINE_VERSION",
    "SUPPORTED_HYPOTHESIS_MODELS_V1",
    "Hypothesis",
    "HypothesisRegistry",
    "HypothesisRegistryEmitReason",
    "HypothesisVerificationFinding",
    "HypothesisVerificationFindingType",
    "HypothesisVerificationReport",
    "build_hypothesis_registry",
    "canonical_json",
    "compute_hypothesis_id",
    "compute_hypothesis_registry_hash",
    "compute_hypothesis_verification_hash",
    "verify_hypothesis_registry",
]
