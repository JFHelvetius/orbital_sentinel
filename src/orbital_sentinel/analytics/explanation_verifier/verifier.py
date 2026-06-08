"""Verifier de :class:`ExplanationArtifact` (ADR-0034).

Función pura. Recomputa hashes, valida referencias cruzadas. Nunca lanza,
nunca muta.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone

from orbital_sentinel.analytics.agent_contract import AgentInput
from orbital_sentinel.analytics.explanation_agent import (
    EXPLANATION_AGENT_ENGINE_VERSION,
    ExplanationArtifact,
    all_templates_canonical,
    compute_explanation_id,
    compute_prompt_hash,
)
from orbital_sentinel.analytics.explanation_verifier.models import (
    EXPLANATION_VERIFIER_ENGINE_VERSION,
    ExplanationFindingType,
    ExplanationVerificationFinding,
    ExplanationVerificationReport,
    compute_verification_hash,
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _f(
    finding_type: ExplanationFindingType,
    affected_id: str,
    expected: str,
    actual: str,
) -> ExplanationVerificationFinding:
    return ExplanationVerificationFinding(
        finding_type=finding_type, affected_id=affected_id,
        expected=expected, actual=actual,
    )


def verify_explanation(
    artifact: ExplanationArtifact,
    agent_input: AgentInput,
    *,
    clock: Callable[[], datetime] | None = None,
) -> ExplanationVerificationReport:
    """Recomputa hashes y valida referencias cruzadas. Nunca lanza."""
    findings: list[ExplanationVerificationFinding] = []
    bundle = agent_input.bundle

    # --- 1. Cada referenced_evidence_id existe en el bundle -----------
    bundle_ids = {bp.evidence_id for bp in bundle.evidence_payloads}
    ref_ids = set(artifact.referenced_evidence_ids)
    n_orphan = 0
    for orphan in sorted(ref_ids - bundle_ids):
        n_orphan += 1
        findings.append(_f(
            "evidence_id_not_in_bundle",
            affected_id=orphan,
            expected="present_in_bundle",
            actual="absent",
        ))

    # --- 2. referenced_evidence_ids == audit.evidence_ids_used --------
    audit_ids = set(artifact.audit_record.evidence_ids_used)
    for missing in sorted(ref_ids - audit_ids):
        findings.append(_f(
            "referenced_id_missing_from_audit",
            affected_id=missing,
            expected="present_in_audit_evidence_ids_used",
            actual="absent",
        ))
    for unexpected in sorted(audit_ids - ref_ids):
        findings.append(_f(
            "audit_id_missing_from_referenced",
            affected_id=unexpected,
            expected="present_in_referenced_evidence_ids",
            actual="absent",
        ))
    refs_audit_consistent = (ref_ids == audit_ids)

    # --- 3. explanation_id recomputa correctamente -----------------
    expected_prompt_hash = compute_prompt_hash(
        templates_canonical=all_templates_canonical(),
        engine_version=EXPLANATION_AGENT_ENGINE_VERSION,
    )
    recomputed_explanation_id = compute_explanation_id(
        source_agent_input_id=artifact.source_agent_input_id,
        source_bundle_id=artifact.source_bundle_id,
        prompt_hash=expected_prompt_hash,
        explanation_engine_version=artifact.explanation_engine_version,
    )
    explanation_id_ok = recomputed_explanation_id == artifact.explanation_id
    if not explanation_id_ok:
        findings.append(_f(
            "explanation_id_recompute_mismatch",
            affected_id="artifact",
            expected=artifact.explanation_id,
            actual=recomputed_explanation_id,
        ))

    # --- 4. audit_record.explanation_id == artifact.explanation_id ----
    audit_exp_id_ok = (artifact.audit_record.explanation_id == artifact.explanation_id)
    if not audit_exp_id_ok:
        findings.append(_f(
            "audit_explanation_id_mismatch",
            affected_id="audit_record",
            expected=artifact.explanation_id,
            actual=artifact.audit_record.explanation_id,
        ))

    # --- 5. audit.bundle_id == artifact.source_bundle_id --------------
    audit_bundle_ok = (artifact.audit_record.bundle_id == artifact.source_bundle_id)
    if not audit_bundle_ok:
        findings.append(_f(
            "audit_bundle_id_mismatch",
            affected_id="audit_record",
            expected=artifact.source_bundle_id,
            actual=artifact.audit_record.bundle_id,
        ))

    # --- 6. audit.agent_input_id == artifact.source_agent_input_id ---
    audit_ai_ok = (artifact.audit_record.agent_input_id == artifact.source_agent_input_id)
    if not audit_ai_ok:
        findings.append(_f(
            "audit_agent_input_id_mismatch",
            affected_id="audit_record",
            expected=artifact.source_agent_input_id,
            actual=artifact.audit_record.agent_input_id,
        ))

    # --- 7. prompt_hash coherente entre metadata y audit -------------
    prompt_ok = (
        artifact.audit_record.prompt_hash == artifact.generation_metadata.prompt_hash
    )
    if not prompt_ok:
        findings.append(_f(
            "prompt_hash_mismatch_between_metadata_and_audit",
            affected_id="artifact",
            expected=artifact.generation_metadata.prompt_hash,
            actual=artifact.audit_record.prompt_hash,
        ))

    # --- 8. source_bundle_id matches agent_input.bundle.bundle_id ---
    source_bundle_ok = (artifact.source_bundle_id == bundle.bundle_id)
    if not source_bundle_ok:
        findings.append(_f(
            "source_bundle_id_mismatch",
            affected_id="artifact",
            expected=bundle.bundle_id,
            actual=artifact.source_bundle_id,
        ))

    # --- 9. source_agent_input_id matches agent_input.agent_input_id -
    source_ai_ok = (artifact.source_agent_input_id == agent_input.agent_input_id)
    if not source_ai_ok:
        findings.append(_f(
            "source_agent_input_id_mismatch",
            affected_id="artifact",
            expected=agent_input.agent_input_id,
            actual=artifact.source_agent_input_id,
        ))

    is_valid = (
        n_orphan == 0
        and refs_audit_consistent
        and explanation_id_ok
        and audit_exp_id_ok
        and audit_bundle_ok
        and audit_ai_ok
        and prompt_ok
        and source_bundle_ok
        and source_ai_ok
    )

    verification_hash = compute_verification_hash(
        explanation_id=artifact.explanation_id,
        bundle_id=bundle.bundle_id,
        agent_input_id=agent_input.agent_input_id,
        is_valid=is_valid,
        referenced_evidence_count=len(artifact.referenced_evidence_ids),
        verifier_engine_version=EXPLANATION_VERIFIER_ENGINE_VERSION,
    )
    verified_at = (clock or _utc_now)()
    return ExplanationVerificationReport(
        explanation_id=artifact.explanation_id,
        bundle_id=bundle.bundle_id,
        agent_input_id=agent_input.agent_input_id,
        is_valid=is_valid,
        referenced_evidence_count=len(artifact.referenced_evidence_ids),
        n_orphan_references=n_orphan,
        n_findings=len(findings),
        explanation_id_recomputes_correctly=explanation_id_ok,
        audit_explanation_id_matches=audit_exp_id_ok,
        audit_bundle_id_matches=audit_bundle_ok,
        audit_agent_input_id_matches=audit_ai_ok,
        prompt_hash_consistent_metadata_audit=prompt_ok,
        referenced_audit_ids_consistent=refs_audit_consistent,
        source_bundle_id_matches_agent_input=source_bundle_ok,
        source_agent_input_id_matches_agent_input=source_ai_ok,
        findings=findings,
        verification_hash=verification_hash,
        verified_at=verified_at,
    )
