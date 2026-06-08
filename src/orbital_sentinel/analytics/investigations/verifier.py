"""Verifier del :class:`InvestigationCase` (ADR-0038).

Función pura. Nunca lanza. Siempre retorna :class:`CaseVerificationReport`.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone

from orbital_sentinel.analytics.investigations.hashing import (
    compute_case_label_hash,
    compute_case_signature,
    compute_case_verification_hash,
)
from orbital_sentinel.analytics.investigations.models import (
    CASE_LAYER_ENGINE_VERSION,
    CASE_VERIFIER_ENGINE_VERSION,
    CaseVerificationFinding,
    CaseVerificationFindingType,
    CaseVerificationReport,
    InvestigationCase,
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _f(
    ft: CaseVerificationFindingType, affected: str, expected: str, actual: str,
) -> CaseVerificationFinding:
    return CaseVerificationFinding(
        finding_type=ft, affected_id=affected, expected=expected, actual=actual,
    )


def verify_investigation_case(
    case: InvestigationCase,
    *,
    clock: Callable[[], datetime] | None = None,
) -> CaseVerificationReport:
    """Verifica integridad cross-layer del caso embebido."""
    findings: list[CaseVerificationFinding] = []

    # --- 1. case_id alias ----------------------------------------
    alias_ok = case.case_id == case.case_signature
    if not alias_ok:
        findings.append(_f(
            "case_id_signature_alias_violation", "case",
            case.case_signature, case.case_id,
        ))

    # --- 2. case_label_hash ---------------------------------------
    expected_label_hash = compute_case_label_hash(case.case_label)
    label_hash_ok = case.case_label_hash == expected_label_hash
    if not label_hash_ok:
        findings.append(_f(
            "case_label_hash_mismatch", "case",
            expected_label_hash, case.case_label_hash,
        ))

    # --- 3. case_signature recompute -------------------------------
    expected_sig = compute_case_signature(
        chain_id=case.referenced_chain_id,
        hypothesis_registry_id=case.referenced_hypothesis_registry_id,
        claim_registry_id=case.referenced_claim_registry_id,
        explanation_id=case.referenced_explanation_id,
        agent_input_id=case.referenced_agent_input_id,
        bundle_id=case.referenced_bundle_id,
        case_label_hash=case.case_label_hash,
        case_layer_engine_version=case.case_layer_engine_version,
    )
    sig_ok = case.case_signature == expected_sig
    if not sig_ok:
        findings.append(_f(
            "case_signature_recompute_mismatch", "case",
            expected_sig, case.case_signature,
        ))

    # --- 4. embedded IDs match referenced IDs ----------------------
    embedded_ok = True
    if case.chain.chain_id != case.referenced_chain_id:
        embedded_ok = False
        findings.append(_f(
            "embedded_chain_id_mismatch_ref", "case",
            case.referenced_chain_id, case.chain.chain_id,
        ))
    if case.hypothesis_registry.registry_id != case.referenced_hypothesis_registry_id:
        embedded_ok = False
        findings.append(_f(
            "embedded_hypothesis_registry_id_mismatch_ref", "case",
            case.referenced_hypothesis_registry_id,
            case.hypothesis_registry.registry_id,
        ))
    if case.claim_registry.registry_id != case.referenced_claim_registry_id:
        embedded_ok = False
        findings.append(_f(
            "embedded_claim_registry_id_mismatch_ref", "case",
            case.referenced_claim_registry_id, case.claim_registry.registry_id,
        ))
    if case.explanation_artifact.explanation_id != case.referenced_explanation_id:
        embedded_ok = False
        findings.append(_f(
            "embedded_explanation_id_mismatch_ref", "case",
            case.referenced_explanation_id, case.explanation_artifact.explanation_id,
        ))
    if case.agent_input.agent_input_id != case.referenced_agent_input_id:
        embedded_ok = False
        findings.append(_f(
            "embedded_agent_input_id_mismatch_ref", "case",
            case.referenced_agent_input_id, case.agent_input.agent_input_id,
        ))
    if case.evidence_bundle.bundle_id != case.referenced_bundle_id:
        embedded_ok = False
        findings.append(_f(
            "embedded_bundle_id_mismatch_ref", "case",
            case.referenced_bundle_id, case.evidence_bundle.bundle_id,
        ))

    # --- 5. Pipeline consistency: chain ↔ otros artefactos ----------
    chain_pipeline_ok = True
    if case.chain.source_hypothesis_registry_id != case.hypothesis_registry.registry_id:
        chain_pipeline_ok = False
        findings.append(_f(
            "embedded_chain_inconsistent_with_hypothesis", "case",
            case.hypothesis_registry.registry_id,
            case.chain.source_hypothesis_registry_id,
        ))
    if case.chain.source_claim_registry_id != case.claim_registry.registry_id:
        chain_pipeline_ok = False
        findings.append(_f(
            "embedded_chain_inconsistent_with_claim_registry", "case",
            case.claim_registry.registry_id,
            case.chain.source_claim_registry_id,
        ))
    if case.chain.source_explanation_id != case.explanation_artifact.explanation_id:
        chain_pipeline_ok = False
        findings.append(_f(
            "embedded_chain_inconsistent_with_artifact", "case",
            case.explanation_artifact.explanation_id,
            case.chain.source_explanation_id,
        ))
    if case.chain.source_agent_input_id != case.agent_input.agent_input_id:
        chain_pipeline_ok = False
        findings.append(_f(
            "embedded_chain_inconsistent_with_agent_input", "case",
            case.agent_input.agent_input_id,
            case.chain.source_agent_input_id,
        ))
    if case.chain.source_bundle_id != case.evidence_bundle.bundle_id:
        chain_pipeline_ok = False
        findings.append(_f(
            "embedded_chain_inconsistent_with_bundle", "case",
            case.evidence_bundle.bundle_id, case.chain.source_bundle_id,
        ))

    # --- 6. Cross-layer source IDs --------------------------------
    pipeline_ok = True
    if case.hypothesis_registry.source_claim_registry_id != case.claim_registry.registry_id:
        pipeline_ok = False
        findings.append(_f(
            "embedded_hypothesis_inconsistent_with_claim_registry", "case",
            case.claim_registry.registry_id,
            case.hypothesis_registry.source_claim_registry_id,
        ))
    if case.claim_registry.source_explanation_id != case.explanation_artifact.explanation_id:
        pipeline_ok = False
        findings.append(_f(
            "embedded_claim_registry_inconsistent_with_artifact", "case",
            case.explanation_artifact.explanation_id,
            case.claim_registry.source_explanation_id,
        ))
    if case.explanation_artifact.source_agent_input_id != case.agent_input.agent_input_id:
        pipeline_ok = False
        findings.append(_f(
            "embedded_artifact_inconsistent_with_agent_input", "case",
            case.agent_input.agent_input_id,
            case.explanation_artifact.source_agent_input_id,
        ))
    if case.agent_input.bundle.bundle_id != case.evidence_bundle.bundle_id:
        pipeline_ok = False
        findings.append(_f(
            "embedded_agent_input_inconsistent_with_bundle", "case",
            case.evidence_bundle.bundle_id, case.agent_input.bundle.bundle_id,
        ))

    # --- 7. Engine version ----------------------------------------
    eng_ok = case.case_layer_engine_version == CASE_LAYER_ENGINE_VERSION
    if not eng_ok:
        findings.append(_f(
            "case_layer_engine_version_mismatch", "case",
            CASE_LAYER_ENGINE_VERSION, case.case_layer_engine_version,
        ))

    is_valid = (
        alias_ok and label_hash_ok and sig_ok
        and embedded_ok and chain_pipeline_ok and pipeline_ok and eng_ok
    )

    verification_hash = compute_case_verification_hash(
        case_id=case.case_id,
        is_valid=is_valid,
        n_artifacts_verified=6,
        n_findings=len(findings),
        verifier_engine_version=CASE_VERIFIER_ENGINE_VERSION,
    )
    verified_at = (clock or _utc_now)()
    return CaseVerificationReport(
        case_id=case.case_id,
        is_valid=is_valid,
        n_artifacts_verified=6,
        n_findings=len(findings),
        case_id_is_alias_of_case_signature=alias_ok,
        case_signature_recomputes_correctly=sig_ok,
        case_label_hash_recomputes_correctly=label_hash_ok,
        embedded_ids_match_referenced_ids=embedded_ok,
        embedded_chain_consistent_with_others=chain_pipeline_ok,
        embedded_artifacts_form_valid_pipeline=pipeline_ok,
        case_layer_engine_version_consistent=eng_ok,
        findings=findings,
        verification_hash=verification_hash,
        verified_at=verified_at,
    )
