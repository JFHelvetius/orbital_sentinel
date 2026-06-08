"""Builder del :class:`HypothesisRegistry` (ADR-0036).

Función pura. NO genera contenido nuevo. NO interpreta. Sólo agrupa
``VerifiableClaim`` existentes por ``(object_id, evidence_type)``, donde
la pareja se obtiene del ``BundledEvidence`` referenciado por cada claim
en el ``EvidenceBundle`` del ``AgentInput``.

El modelo de agrupación v1 es ``template_hypothesis_grouping_v01``:
claims que comparten el mismo ``(object_id, evidence_type)`` forman una
hipótesis.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone

from orbital_sentinel.analytics.agent_contract import AgentInput
from orbital_sentinel.analytics.claims import ClaimRegistry
from orbital_sentinel.analytics.hypotheses.hashing import (
    compute_hypothesis_id,
    compute_hypothesis_registry_hash,
)
from orbital_sentinel.analytics.hypotheses.models import (
    HYPOTHESIS_LAYER_ENGINE_VERSION,
    Hypothesis,
    HypothesisRegistry,
    HypothesisRegistryEmitReason,
)
from orbital_sentinel.core.errors import HypothesisRegistryBuilderError

HYPOTHESIS_MODEL_IDENTIFIER_V1 = "template_hypothesis_grouping_v01"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _format_hypothesis_label(
    *, object_id: int, evidence_type: str, n_claims: int,
) -> str:
    """Template determinístico v1. Nunca interpretativo."""
    plural = "claim" if n_claims == 1 else "claims"
    return (
        f"Object {object_id} exhibits {evidence_type} evidence "
        f"({n_claims} {plural})."
    )


def build_hypothesis_registry(
    claim_registry: ClaimRegistry,
    agent_input: AgentInput,
    *,
    clock: Callable[[], datetime] | None = None,
) -> HypothesisRegistry:
    """Agrupa los claims existentes en :class:`Hypothesis` deterministas.

    Raises:
        HypothesisRegistryBuilderError: si los inputs son incompatibles
            (registry no apunta al mismo bundle/agent_input).
    """
    if claim_registry.source_bundle_id != agent_input.bundle.bundle_id:
        raise HypothesisRegistryBuilderError(
            f"claim_registry.source_bundle_id ({claim_registry.source_bundle_id[:12]}…) "
            f"!= agent_input.bundle.bundle_id ({agent_input.bundle.bundle_id[:12]}…)."
        )
    if claim_registry.source_agent_input_id != agent_input.agent_input_id:
        raise HypothesisRegistryBuilderError(
            "claim_registry.source_agent_input_id does not match "
            "agent_input.agent_input_id.",
        )

    bundle = agent_input.bundle
    evidence_by_id: dict[str, tuple[int, str]] = {}
    for bp in bundle.evidence_payloads:
        evidence_by_id[bp.evidence_id] = (
            bp.derived_evidence.object_id,
            bp.derived_evidence.evidence_type,
        )

    hypotheses: list[Hypothesis] = []
    emit_reason: HypothesisRegistryEmitReason

    if not claim_registry.claims:
        emit_reason = "empty_claim_registry"
    else:
        emit_reason = "claim_registry_populated"
        # Agrupa por (object_id, evidence_type) preservando orden de aparición
        # del primer claim para determinismo.
        grouping: dict[tuple[int, str], list[str]] = {}
        first_seen_order: list[tuple[int, str]] = []
        for c in claim_registry.claims:
            if not c.supporting_evidence_ids:
                raise HypothesisRegistryBuilderError(
                    f"Claim {c.claim_id[:12]}… has no supporting_evidence_ids; "
                    "builder cannot derive a grouping_key.",
                )
            first_ev = c.supporting_evidence_ids[0]
            if first_ev not in evidence_by_id:
                raise HypothesisRegistryBuilderError(
                    f"Claim {c.claim_id[:12]}… references evidence_id "
                    f"{first_ev[:12]}… not present in agent_input bundle.",
                )
            key = evidence_by_id[first_ev]
            if key not in grouping:
                grouping[key] = []
                first_seen_order.append(key)
            grouping[key].append(c.claim_id)

        for idx, key in enumerate(first_seen_order):
            object_id, evidence_type = key
            supporting = sorted(grouping[key])
            grouping_key = f"{object_id}|{evidence_type}"
            label = _format_hypothesis_label(
                object_id=object_id,
                evidence_type=evidence_type,
                n_claims=len(supporting),
            )
            hid = compute_hypothesis_id(
                source_claim_registry_id=claim_registry.registry_id,
                hypothesis_index=idx,
                grouping_key=grouping_key,
                supporting_claim_ids=supporting,
                hypothesis_label=label,
                hypothesis_layer_engine_version=HYPOTHESIS_LAYER_ENGINE_VERSION,
            )
            hypotheses.append(
                Hypothesis(
                    hypothesis_id=hid,
                    source_claim_registry_id=claim_registry.registry_id,
                    hypothesis_index=idx,
                    grouping_key=grouping_key,
                    supporting_claim_ids=supporting,
                    hypothesis_label=label,
                )
            )

    forward: dict[str, list[str]] = {
        h.hypothesis_id: list(h.supporting_claim_ids) for h in hypotheses
    }
    forward_ordered = {k: forward[k] for k in sorted(forward.keys())}

    reverse: dict[str, list[str]] = {}
    for h in hypotheses:
        for cid in h.supporting_claim_ids:
            reverse.setdefault(cid, []).append(h.hypothesis_id)
    reverse_ordered = {k: sorted(reverse[k]) for k in sorted(reverse.keys())}

    registry_hash = compute_hypothesis_registry_hash(
        source_claim_registry_id=claim_registry.registry_id,
        source_bundle_id=agent_input.bundle.bundle_id,
        source_agent_input_id=agent_input.agent_input_id,
        hypothesis_ids=[h.hypothesis_id for h in hypotheses],
        hypothesis_layer_engine_version=HYPOTHESIS_LAYER_ENGINE_VERSION,
    )
    derived_at = (clock or _utc_now)()
    return HypothesisRegistry(
        registry_id=registry_hash,
        registry_hash=registry_hash,
        source_claim_registry_id=claim_registry.registry_id,
        source_bundle_id=agent_input.bundle.bundle_id,
        source_agent_input_id=agent_input.agent_input_id,
        source_explanation_id=claim_registry.source_explanation_id,
        source_model_identifier=HYPOTHESIS_MODEL_IDENTIFIER_V1,
        source_claim_layer_engine_version=claim_registry.claim_layer_engine_version,
        n_hypotheses=len(hypotheses),
        hypotheses=hypotheses,
        hypothesis_to_claim_index=forward_ordered,
        claim_to_hypothesis_index=reverse_ordered,
        registry_emit_reason=emit_reason,
        derived_at=derived_at,
    )
