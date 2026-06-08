"""Explanation Verification Layer v0.1 (ADR-0034)."""

from orbital_sentinel.analytics.explanation_verifier.models import (
    EXPLANATION_VERIFICATION_SCHEMA_VERSION,
    EXPLANATION_VERIFIER_ENGINE_VERSION,
    ExplanationFindingType,
    ExplanationVerificationFinding,
    ExplanationVerificationReport,
    compute_verification_hash,
)
from orbital_sentinel.analytics.explanation_verifier.verifier import (
    verify_explanation,
)

__all__ = [
    "EXPLANATION_VERIFICATION_SCHEMA_VERSION",
    "EXPLANATION_VERIFIER_ENGINE_VERSION",
    "ExplanationFindingType",
    "ExplanationVerificationFinding",
    "ExplanationVerificationReport",
    "compute_verification_hash",
    "verify_explanation",
]
