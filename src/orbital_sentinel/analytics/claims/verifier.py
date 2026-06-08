"""Verifier del :class:`ClaimRegistry` (ADR-0035).

Función pura. Nunca muta. Nunca lanza por integridad rota. Siempre
retorna :class:`ClaimVerificationReport`.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone

from orbital_sentinel.analytics.agent_contract import AgentInput
from orbital_sentinel.analytics.claims.hashing import (
    compute_claim_id,
    compute_verification_hash,
)
from orbital_sentinel.analytics.claims.models import (
    CLAIM_LAYER_ENGINE_VERSION,
    CLAIM_VERIFIER_ENGINE_VERSION,
    SUPPORTED_SOURCE_MODELS_V01,
    ClaimRegistry,
    ClaimVerificationFinding,
    ClaimVerificationFindingType,
    ClaimVerificationReport,
)
from orbital_sentinel.analytics.explanation_agent import ExplanationArtifact


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _f(
    ft: ClaimVerificationFindingType, affected: str, expected: str, actual: str,
) -> ClaimVerificationFinding:
    return ClaimVerificationFinding(
        finding_type=ft, affected_id=affected, expected=expected, actual=actual,
    )


def verify_claim_registry(
    registry: ClaimRegistry,
    agent_input: AgentInput,
    artifact: ExplanationArtifact,
    *,
    clock: Callable[[], datetime] | None = None,
) -> ClaimVerificationReport:
    """Recomputa todas las firmas y enlaces. Nunca lanza."""
    findings: list[ClaimVerificationFinding] = []
    bundle = agent_input.bundle
    bundle_evidence_ids = {bp.evidence_id for bp in bundle.evidence_payloads}
    claims = list(registry.claims)

    # --- 1. Source IDs ---------------------------------------------
    source_explanation_ok = registry.source_explanation_id == artifact.explanation_id
    if not source_explanation_ok:
        findings.append(_f(
            "source_explanation_id_mismatch", "registry",
            artifact.explanation_id, registry.source_explanation_id,
        ))
    source_bundle_ok = registry.source_bundle_id == bundle.bundle_id
    if not source_bundle_ok:
        findings.append(_f(
            "source_bundle_id_mismatch", "registry",
            bundle.bundle_id, registry.source_bundle_id,
        ))
    source_ai_ok = registry.source_agent_input_id == agent_input.agent_input_id
    if not source_ai_ok:
        findings.append(_f(
            "source_agent_input_id_mismatch", "registry",
            agent_input.agent_input_id, registry.source_agent_input_id,
        ))
    all_source_ok = source_explanation_ok and source_bundle_ok and source_ai_ok

    # --- 2. Modelo soportado ---------------------------------------
    model_supported = registry.source_model_identifier in SUPPORTED_SOURCE_MODELS_V01
    if not model_supported:
        findings.append(_f(
            "unsupported_source_model", "registry",
            f"one of {SUPPORTED_SOURCE_MODELS_V01!r}",
            registry.source_model_identifier,
        ))

    # --- 3. n_claims coherente -------------------------------------
    n_claims_ok = registry.n_claims == len(claims)
    if not n_claims_ok:
        findings.append(_f(
            "n_claims_count_mismatch", "registry",
            str(len(claims)), str(registry.n_claims),
        ))

    # --- 4. registry_id alias de registry_hash ---------------------
    alias_ok = registry.registry_id == registry.registry_hash
    if not alias_ok:
        findings.append(_f(
            "registry_id_signature_alias_violation", "registry",
            registry.registry_hash, registry.registry_id,
        ))

    # --- 5. Por cada claim: recompute claim_id, supporting check ---
    seen_indices: set[int] = set()
    seen_claim_ids: set[str] = set()
    claims_with_findings: set[str] = set()
    all_claims_recompute = True
    for c in claims:
        expected_cid = compute_claim_id(
            source_explanation_id=c.source_explanation_id,
            claim_index=c.claim_index,
            supporting_evidence_ids=c.supporting_evidence_ids,
            claim_text=c.claim_text,
            claim_layer_engine_version=CLAIM_LAYER_ENGINE_VERSION,
        )
        if c.claim_id != expected_cid:
            all_claims_recompute = False
            findings.append(_f(
                "claim_id_recompute_mismatch", c.claim_id,
                expected_cid, c.claim_id,
            ))
            claims_with_findings.add(c.claim_id)
        if not c.supporting_evidence_ids:
            findings.append(_f(
                "claim_without_supporting_evidence", c.claim_id,
                ">=1 evidence_id", "0 evidence_ids",
            ))
            claims_with_findings.add(c.claim_id)
        for ev in c.supporting_evidence_ids:
            if ev not in bundle_evidence_ids:
                findings.append(_f(
                    "supporting_evidence_not_in_bundle", c.claim_id,
                    "present_in_bundle", "absent",
                ))
                claims_with_findings.add(c.claim_id)
        # claim_index unicidad
        if c.claim_index in seen_indices:
            findings.append(_f(
                "duplicate_claim_index", c.claim_id,
                "unique", str(c.claim_index),
            ))
            claims_with_findings.add(c.claim_id)
        seen_indices.add(c.claim_index)
        # claim_id unicidad
        if c.claim_id in seen_claim_ids:
            findings.append(_f(
                "duplicate_claim_id", c.claim_id, "unique", c.claim_id,
            ))
            claims_with_findings.add(c.claim_id)
        seen_claim_ids.add(c.claim_id)

    # --- 6. claim_index sequential 0..N-1 --------------------------
    expected_indices = set(range(len(claims)))
    if seen_indices != expected_indices:
        findings.append(_f(
            "claim_index_not_sequential", "registry",
            f"{{0..{len(claims) - 1}}}",
            ",".join(str(i) for i in sorted(seen_indices)),
        ))

    # --- 7. Forward index coherente con claims ---------------------
    expected_forward = {c.claim_id: list(c.supporting_evidence_ids) for c in claims}
    forward_ok = registry.claim_to_evidence_index == expected_forward
    if not forward_ok:
        findings.append(_f(
            "forward_index_mismatch", "registry",
            "matches claims supporting_evidence_ids", "differs",
        ))
    forward_keyset_ok = set(registry.claim_to_evidence_index.keys()) == seen_claim_ids
    if not forward_keyset_ok:
        findings.append(_f(
            "forward_index_key_set_mismatch", "registry",
            "set(claim_ids)", "differs",
        ))

    # --- 8. Reverse index = traspuesta del forward ----------------
    expected_reverse: dict[str, list[str]] = {}
    for c in claims:
        for ev in c.supporting_evidence_ids:
            expected_reverse.setdefault(ev, []).append(c.claim_id)
    expected_reverse_sorted = {k: sorted(v) for k, v in expected_reverse.items()}
    actual_reverse_sorted = {
        k: sorted(v) for k, v in registry.evidence_to_claim_index.items()
    }
    reverse_ok = expected_reverse_sorted == actual_reverse_sorted
    if not reverse_ok:
        findings.append(_f(
            "reverse_index_mismatch", "registry",
            "transpose of forward index", "differs",
        ))
    expected_reverse_keys = {ev for c in claims for ev in c.supporting_evidence_ids}
    reverse_keyset_ok = set(registry.evidence_to_claim_index.keys()) == expected_reverse_keys
    if not reverse_keyset_ok:
        findings.append(_f(
            "reverse_index_key_set_mismatch", "registry",
            "set(union of supporting_evidence_ids)", "differs",
        ))

    # --- 9. claim_text bit-exacto de explanation_text -------------
    lines = [ln for ln in artifact.explanation_text.split("\n") if ln.strip()]
    texts_ok = True
    for c in claims:
        if c.claim_index < len(lines):
            if c.claim_text != lines[c.claim_index]:
                texts_ok = False
                findings.append(_f(
                    "claim_text_does_not_match_explanation_line", c.claim_id,
                    lines[c.claim_index], c.claim_text,
                ))
                claims_with_findings.add(c.claim_id)
        else:
            texts_ok = False
            findings.append(_f(
                "claim_text_does_not_match_explanation_line", c.claim_id,
                f"line_index<{len(lines)}", f"line_index={c.claim_index}",
            ))
            claims_with_findings.add(c.claim_id)

    # --- 10. Cobertura referenced_evidence_ids ↔ claims -----------
    claim_evidence_union = set()
    for c in claims:
        claim_evidence_union.update(c.supporting_evidence_ids)
    artifact_refs = set(artifact.referenced_evidence_ids)
    referenced_covered = artifact_refs.issubset(claim_evidence_union) or not artifact_refs
    if artifact_refs and not artifact_refs.issubset(claim_evidence_union):
        for missing in sorted(artifact_refs - claim_evidence_union):
            findings.append(_f(
                "referenced_evidence_not_covered_by_any_claim", missing,
                "covered_by_at_least_one_claim", "uncovered",
            ))
    for extra in sorted(claim_evidence_union - artifact_refs):
        findings.append(_f(
            "claim_references_unknown_evidence", extra,
            "present_in_referenced_evidence_ids", "absent",
        ))
    references_subset_ok = claim_evidence_union.issubset(artifact_refs) or not claim_evidence_union

    # --- 11. supporting_evidence_in_bundle global -----------------
    all_supporting_in_bundle = all(
        ev in bundle_evidence_ids
        for c in claims
        for ev in c.supporting_evidence_ids
    )

    is_valid = (
        all_source_ok
        and model_supported
        and n_claims_ok
        and alias_ok
        and all_claims_recompute
        and all_supporting_in_bundle
        and forward_ok
        and forward_keyset_ok
        and reverse_ok
        and reverse_keyset_ok
        and texts_ok
        and referenced_covered
        and references_subset_ok
        and seen_indices == expected_indices
        and len(seen_claim_ids) == len(claims)
    )

    verification_hash = compute_verification_hash(
        registry_id=registry.registry_id,
        is_valid=is_valid,
        n_claims_verified=len(claims),
        n_findings=len(findings),
        verifier_engine_version=CLAIM_VERIFIER_ENGINE_VERSION,
    )
    verified_at = (clock or _utc_now)()
    return ClaimVerificationReport(
        registry_id=registry.registry_id,
        is_valid=is_valid,
        n_claims_verified=len(claims),
        n_claims_with_findings=len(claims_with_findings),
        n_findings=len(findings),
        forward_index_consistent=forward_ok and forward_keyset_ok,
        reverse_index_consistent=reverse_ok and reverse_keyset_ok,
        all_supporting_evidence_in_bundle=all_supporting_in_bundle,
        all_referenced_evidence_covered=referenced_covered and references_subset_ok,
        all_claim_ids_recompute_correctly=all_claims_recompute,
        registry_id_is_alias_of_registry_hash=alias_ok,
        all_source_ids_match=all_source_ok,
        all_claim_texts_match_explanation=texts_ok,
        source_model_supported=model_supported,
        findings=findings,
        verification_hash=verification_hash,
        verified_at=verified_at,
    )
