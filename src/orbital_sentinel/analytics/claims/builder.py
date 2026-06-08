"""Builder del :class:`ClaimRegistry` (ADR-0035).

Función pura. Sin validación, sin verificación, sin reparación. Si el
artifact y agent_input no son estructuralmente compatibles, raise
:class:`ClaimRegistryBuilderError`.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone

from orbital_sentinel.analytics.agent_contract import AgentInput
from orbital_sentinel.analytics.claims.hashing import (
    compute_claim_id,
    compute_registry_hash,
)
from orbital_sentinel.analytics.claims.models import (
    CLAIM_LAYER_ENGINE_VERSION,
    SUPPORTED_SOURCE_MODELS_V01,
    ClaimRegistry,
    RegistryEmitReason,
    VerifiableClaim,
)
from orbital_sentinel.analytics.explanation_agent import ExplanationArtifact
from orbital_sentinel.core.errors import ClaimRegistryBuilderError


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def build_claim_registry(
    artifact: ExplanationArtifact,
    agent_input: AgentInput,
    *,
    clock: Callable[[], datetime] | None = None,
) -> ClaimRegistry:
    """Atomiza una :class:`ExplanationArtifact` en un :class:`ClaimRegistry`.

    Raises:
        ClaimRegistryBuilderError: si el artifact y agent_input no son
            compatibles, o si el ``model_identifier`` del agente no está
            soportado por la versión v0.1 del builder.
    """
    # --- Compatibilidad estructural --------------------------------
    if artifact.source_bundle_id != agent_input.bundle.bundle_id:
        raise ClaimRegistryBuilderError(
            f"artifact.source_bundle_id ({artifact.source_bundle_id[:12]}…) "
            f"!= agent_input.bundle.bundle_id ({agent_input.bundle.bundle_id[:12]}…)."
        )
    if artifact.source_agent_input_id != agent_input.agent_input_id:
        raise ClaimRegistryBuilderError(
            "artifact.source_agent_input_id does not match agent_input.agent_input_id."
        )
    model_id = artifact.generation_metadata.model_identifier
    if model_id not in SUPPORTED_SOURCE_MODELS_V01:
        raise ClaimRegistryBuilderError(
            f"Unsupported source model_identifier={model_id!r}; "
            f"v0.1 supports only {SUPPORTED_SOURCE_MODELS_V01!r}."
        )

    referenced_ids = list(artifact.referenced_evidence_ids)
    emit_reason: RegistryEmitReason

    claims: list[VerifiableClaim] = []
    if not referenced_ids:
        # Empty bundle path: el agente emite un único mensaje factual de
        # ausencia. No se atomiza en claims (ADR-0035 §"Empty bundle").
        emit_reason = "empty_bundle"
    else:
        emit_reason = "evidence_bundle"
        lines = [ln for ln in artifact.explanation_text.split("\n") if ln.strip()]
        if len(lines) != len(referenced_ids):
            raise ClaimRegistryBuilderError(
                f"explanation_text non-empty lines ({len(lines)}) does not "
                f"match len(referenced_evidence_ids) ({len(referenced_ids)})."
            )
        for idx, (line, evid) in enumerate(zip(lines, referenced_ids, strict=True)):
            supporting = [evid]
            claim_id = compute_claim_id(
                source_explanation_id=artifact.explanation_id,
                claim_index=idx,
                supporting_evidence_ids=supporting,
                claim_text=line,
                claim_layer_engine_version=CLAIM_LAYER_ENGINE_VERSION,
            )
            claims.append(
                VerifiableClaim(
                    claim_id=claim_id,
                    source_explanation_id=artifact.explanation_id,
                    claim_index=idx,
                    supporting_evidence_ids=supporting,
                    claim_text=line,
                )
            )

    # --- Forward index: claim_id → supporting_evidence_ids -----------
    forward: dict[str, list[str]] = {}
    for c in claims:
        forward[c.claim_id] = list(c.supporting_evidence_ids)
    forward_ordered: dict[str, list[str]] = {
        k: forward[k] for k in sorted(forward.keys())
    }

    # --- Reverse index: evidence_id → claim_ids ---------------------
    reverse: dict[str, list[str]] = {}
    for c in claims:
        for ev in c.supporting_evidence_ids:
            reverse.setdefault(ev, []).append(c.claim_id)
    reverse_ordered: dict[str, list[str]] = {
        k: sorted(reverse[k]) for k in sorted(reverse.keys())
    }

    registry_hash = compute_registry_hash(
        source_explanation_id=artifact.explanation_id,
        source_bundle_id=agent_input.bundle.bundle_id,
        source_agent_input_id=agent_input.agent_input_id,
        claim_ids=[c.claim_id for c in claims],
        claim_layer_engine_version=CLAIM_LAYER_ENGINE_VERSION,
    )
    derived_at = (clock or _utc_now)()
    return ClaimRegistry(
        registry_id=registry_hash,
        registry_hash=registry_hash,
        source_explanation_id=artifact.explanation_id,
        source_bundle_id=agent_input.bundle.bundle_id,
        source_agent_input_id=agent_input.agent_input_id,
        source_model_identifier=model_id,
        source_explanation_engine_version=artifact.explanation_engine_version,
        n_claims=len(claims),
        claims=claims,
        claim_to_evidence_index=forward_ordered,
        evidence_to_claim_index=reverse_ordered,
        registry_emit_reason=emit_reason,
        derived_at=derived_at,
    )
