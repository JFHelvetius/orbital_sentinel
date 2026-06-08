"""Investigation Case Layer v1 (ADR-0038)."""

from orbital_sentinel.analytics.investigations.builder import build_investigation_case
from orbital_sentinel.analytics.investigations.hashing import (
    canonical_json,
    compute_case_label_hash,
    compute_case_signature,
    compute_case_verification_hash,
)
from orbital_sentinel.analytics.investigations.models import (
    CASE_LAYER_ENGINE_VERSION,
    CASE_LAYER_SCHEMA_VERSION,
    CASE_VERIFIER_ENGINE_VERSION,
    CaseEmitReason,
    CaseVerificationFinding,
    CaseVerificationFindingType,
    CaseVerificationReport,
    InvestigationCase,
)
from orbital_sentinel.analytics.investigations.verifier import verify_investigation_case

__all__ = [
    "CASE_LAYER_ENGINE_VERSION",
    "CASE_LAYER_SCHEMA_VERSION",
    "CASE_VERIFIER_ENGINE_VERSION",
    "CaseEmitReason",
    "CaseVerificationFinding",
    "CaseVerificationFindingType",
    "CaseVerificationReport",
    "InvestigationCase",
    "build_investigation_case",
    "canonical_json",
    "compute_case_label_hash",
    "compute_case_signature",
    "compute_case_verification_hash",
    "verify_investigation_case",
]
