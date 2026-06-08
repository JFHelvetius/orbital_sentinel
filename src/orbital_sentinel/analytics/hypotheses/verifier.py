"""Verifier del :class:`HypothesisRegistry` (ADR-0036).

Función pura. Nunca muta. Nunca lanza. Siempre retorna
:class:`HypothesisVerificationReport`.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone

from orbital_sentinel.analytics.agent_contract import AgentInput
from orbital_sentinel.analytics.claims import ClaimRegistry
from orbital_sentinel.analytics.hypotheses.builder import (
    _format_hypothesis_label,
)
from orbital_sentinel.analytics.hypotheses.hashing import (
    compute_hypothesis_id,
    compute_hypothesis_verification_hash,
)
from orbital_sentinel.analytics.hypotheses.models import (
    HYPOTHESIS_LAYER_ENGINE_VERSION,
    HYPOTHESIS_VERIFIER_ENGINE_VERSION,
    SUPPORTED_HYPOTHESIS_MODELS_V1,
    HypothesisRegistry,
    HypothesisVerificationFinding,
    HypothesisVerificationFindingType,
    HypothesisVerificationReport,
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _f(
    ft: HypothesisVerificationFindingType, affected: str, expected: str, actual: str,
) -> HypothesisVerificationFinding:
    return HypothesisVerificationFinding(
        finding_type=ft, affected_id=affected, expected=expected, actual=actual,
    )


def verify_hypothesis_registry(
    registry: HypothesisRegistry,
    claim_registry: ClaimRegistry,
    agent_input: AgentInput,
    *,
    clock: Callable[[], datetime] | None = None,
) -> HypothesisVerificationReport:
    """Recomputa firmas y enlaces. Nunca lanza."""
    findings: list[HypothesisVerificationFinding] = []
    hypotheses = list(registry.hypotheses)
    bundle = agent_input.bundle
    claim_ids_in_registry = {c.claim_id for c in claim_registry.claims}
    evidence_by_id: dict[str, tuple[int, str]] = {
        bp.evidence_id: (bp.derived_evidence.object_id, bp.derived_evidence.evidence_type)
        for bp in bundle.evidence_payloads
    }
    claim_evidence_by_id = {
        c.claim_id: c.supporting_evidence_ids for c in claim_registry.claims
    }

    # --- 1. Source IDs ----------------------------------------------
    src_clr_ok = registry.source_claim_registry_id == claim_registry.registry_id
    if not src_clr_ok:
        findings.append(_f(
            "source_claim_registry_id_mismatch", "registry",
            claim_registry.registry_id, registry.source_claim_registry_id,
        ))
    src_bundle_ok = registry.source_bundle_id == bundle.bundle_id
    if not src_bundle_ok:
        findings.append(_f(
            "source_bundle_id_mismatch", "registry",
            bundle.bundle_id, registry.source_bundle_id,
        ))
    src_ai_ok = registry.source_agent_input_id == agent_input.agent_input_id
    if not src_ai_ok:
        findings.append(_f(
            "source_agent_input_id_mismatch", "registry",
            agent_input.agent_input_id, registry.source_agent_input_id,
        ))
    all_source_ok = src_clr_ok and src_bundle_ok and src_ai_ok

    # --- 2. Modelo soportado ----------------------------------------
    model_supported = registry.source_model_identifier in SUPPORTED_HYPOTHESIS_MODELS_V1
    if not model_supported:
        findings.append(_f(
            "unsupported_hypothesis_model", "registry",
            f"one of {SUPPORTED_HYPOTHESIS_MODELS_V1!r}",
            registry.source_model_identifier,
        ))

    # --- 3. n_hypotheses ---------------------------------------------
    n_ok = registry.n_hypotheses == len(hypotheses)
    if not n_ok:
        findings.append(_f(
            "n_hypotheses_count_mismatch", "registry",
            str(len(hypotheses)), str(registry.n_hypotheses),
        ))

    # --- 4. registry_id alias hash ----------------------------------
    alias_ok = registry.registry_id == registry.registry_hash
    if not alias_ok:
        findings.append(_f(
            "registry_id_signature_alias_violation", "registry",
            registry.registry_hash, registry.registry_id,
        ))

    # --- 5. Per-hypothesis ------------------------------------------
    seen_indices: set[int] = set()
    seen_hids: set[str] = set()
    hyps_with_findings: set[str] = set()
    all_hyps_recompute = True
    label_template_ok = True
    for h in hypotheses:
        expected_hid = compute_hypothesis_id(
            source_claim_registry_id=h.source_claim_registry_id,
            hypothesis_index=h.hypothesis_index,
            grouping_key=h.grouping_key,
            supporting_claim_ids=h.supporting_claim_ids,
            hypothesis_label=h.hypothesis_label,
            hypothesis_layer_engine_version=HYPOTHESIS_LAYER_ENGINE_VERSION,
        )
        if h.hypothesis_id != expected_hid:
            all_hyps_recompute = False
            findings.append(_f(
                "hypothesis_id_recompute_mismatch", h.hypothesis_id,
                expected_hid, h.hypothesis_id,
            ))
            hyps_with_findings.add(h.hypothesis_id)
        if not h.supporting_claim_ids:
            findings.append(_f(
                "hypothesis_without_supporting_claims", h.hypothesis_id,
                ">=1 claim_id", "0 claim_ids",
            ))
            hyps_with_findings.add(h.hypothesis_id)
        for cid in h.supporting_claim_ids:
            if cid not in claim_ids_in_registry:
                findings.append(_f(
                    "supporting_claim_not_in_registry", h.hypothesis_id,
                    "present_in_claim_registry", "absent",
                ))
                hyps_with_findings.add(h.hypothesis_id)
        # Verify label matches template for the grouping key
        try:
            object_id_str, ev_type = h.grouping_key.split("|", 1)
            expected_label = _format_hypothesis_label(
                object_id=int(object_id_str),
                evidence_type=ev_type,
                n_claims=len(h.supporting_claim_ids),
            )
            if h.hypothesis_label != expected_label:
                label_template_ok = False
                findings.append(_f(
                    "hypothesis_label_does_not_match_template", h.hypothesis_id,
                    expected_label, h.hypothesis_label,
                ))
                hyps_with_findings.add(h.hypothesis_id)
            # Cross-check grouping_key against actual evidence
            first_ev_evidence_by_claim: list[tuple[int, str]] = []
            for cid in h.supporting_claim_ids:
                if claim_evidence_by_id.get(cid):
                    ev = claim_evidence_by_id[cid][0]
                    if ev in evidence_by_id:
                        first_ev_evidence_by_claim.append(evidence_by_id[ev])
            for tup in first_ev_evidence_by_claim:
                if tup != (int(object_id_str), ev_type):
                    label_template_ok = False
                    findings.append(_f(
                        "hypothesis_label_does_not_match_template", h.hypothesis_id,
                        f"{int(object_id_str)}|{ev_type}",
                        f"{tup[0]}|{tup[1]}",
                    ))
                    hyps_with_findings.add(h.hypothesis_id)
                    break
        except ValueError:
            label_template_ok = False
            findings.append(_f(
                "hypothesis_label_does_not_match_template", h.hypothesis_id,
                "object_id|evidence_type", h.grouping_key,
            ))
            hyps_with_findings.add(h.hypothesis_id)
        if h.hypothesis_index in seen_indices:
            findings.append(_f(
                "duplicate_hypothesis_index", h.hypothesis_id,
                "unique", str(h.hypothesis_index),
            ))
            hyps_with_findings.add(h.hypothesis_id)
        seen_indices.add(h.hypothesis_index)
        if h.hypothesis_id in seen_hids:
            findings.append(_f(
                "duplicate_hypothesis_id", h.hypothesis_id, "unique", h.hypothesis_id,
            ))
            hyps_with_findings.add(h.hypothesis_id)
        seen_hids.add(h.hypothesis_id)

    expected_indices = set(range(len(hypotheses)))
    if seen_indices != expected_indices:
        findings.append(_f(
            "hypothesis_index_not_sequential", "registry",
            f"{{0..{len(hypotheses) - 1}}}",
            ",".join(str(i) for i in sorted(seen_indices)),
        ))

    # --- 6. Forward index -------------------------------------------
    expected_forward = {h.hypothesis_id: list(h.supporting_claim_ids) for h in hypotheses}
    forward_ok = registry.hypothesis_to_claim_index == expected_forward
    if not forward_ok:
        findings.append(_f(
            "forward_index_mismatch", "registry",
            "matches hypotheses.supporting_claim_ids", "differs",
        ))
    forward_keys_ok = set(registry.hypothesis_to_claim_index.keys()) == seen_hids
    if not forward_keys_ok:
        findings.append(_f(
            "forward_index_key_set_mismatch", "registry",
            "set(hypothesis_ids)", "differs",
        ))

    # --- 7. Reverse index --------------------------------------------
    expected_reverse: dict[str, list[str]] = {}
    for h in hypotheses:
        for cid in h.supporting_claim_ids:
            expected_reverse.setdefault(cid, []).append(h.hypothesis_id)
    expected_reverse_sorted = {k: sorted(v) for k, v in expected_reverse.items()}
    actual_reverse_sorted = {
        k: sorted(v) for k, v in registry.claim_to_hypothesis_index.items()
    }
    reverse_ok = expected_reverse_sorted == actual_reverse_sorted
    if not reverse_ok:
        findings.append(_f(
            "reverse_index_mismatch", "registry",
            "transpose of forward index", "differs",
        ))
    expected_reverse_keys = {cid for h in hypotheses for cid in h.supporting_claim_ids}
    reverse_keys_ok = set(registry.claim_to_hypothesis_index.keys()) == expected_reverse_keys
    if not reverse_keys_ok:
        findings.append(_f(
            "reverse_index_key_set_mismatch", "registry",
            "set(union of supporting_claim_ids)", "differs",
        ))

    # --- 8. Coverage de claims --------------------------------------
    hyp_claim_union: set[str] = set()
    for h in hypotheses:
        hyp_claim_union.update(h.supporting_claim_ids)
    if claim_ids_in_registry:
        uncovered = claim_ids_in_registry - hyp_claim_union
        for cid in sorted(uncovered):
            findings.append(_f(
                "claim_not_referenced_by_any_hypothesis", cid,
                "referenced_by_at_least_one_hypothesis", "uncovered",
            ))
    all_claims_covered = (
        not claim_ids_in_registry
        or claim_ids_in_registry.issubset(hyp_claim_union)
    )

    all_supporting_in_registry = all(
        cid in claim_ids_in_registry
        for h in hypotheses
        for cid in h.supporting_claim_ids
    )

    is_valid = (
        all_source_ok
        and model_supported
        and n_ok
        and alias_ok
        and all_hyps_recompute
        and all_supporting_in_registry
        and forward_ok
        and forward_keys_ok
        and reverse_ok
        and reverse_keys_ok
        and all_claims_covered
        and label_template_ok
        and seen_indices == expected_indices
        and len(seen_hids) == len(hypotheses)
    )

    verification_hash = compute_hypothesis_verification_hash(
        registry_id=registry.registry_id,
        is_valid=is_valid,
        n_hypotheses_verified=len(hypotheses),
        n_findings=len(findings),
        verifier_engine_version=HYPOTHESIS_VERIFIER_ENGINE_VERSION,
    )
    verified_at = (clock or _utc_now)()
    return HypothesisVerificationReport(
        registry_id=registry.registry_id,
        is_valid=is_valid,
        n_hypotheses_verified=len(hypotheses),
        n_hypotheses_with_findings=len(hyps_with_findings),
        n_findings=len(findings),
        forward_index_consistent=forward_ok and forward_keys_ok,
        reverse_index_consistent=reverse_ok and reverse_keys_ok,
        all_supporting_claims_in_registry=all_supporting_in_registry,
        all_claims_covered_by_some_hypothesis=all_claims_covered,
        all_hypothesis_ids_recompute_correctly=all_hyps_recompute,
        registry_id_is_alias_of_registry_hash=alias_ok,
        all_source_ids_match=all_source_ok,
        source_model_supported=model_supported,
        findings=findings,
        verification_hash=verification_hash,
        verified_at=verified_at,
    )
