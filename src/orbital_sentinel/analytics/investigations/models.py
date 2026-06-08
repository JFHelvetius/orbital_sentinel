"""Modelos del Investigation Case Layer v1 (ADR-0038).

Artefacto portable y autocontenido que empaqueta una investigación completa:

* :class:`EvidenceChain` (ADR-0037)
* :class:`HypothesisRegistry` (ADR-0036)
* :class:`ClaimRegistry` (ADR-0035)
* :class:`ExplanationArtifact` (ADR-0033)
* :class:`AgentInput` (ADR-0032)
* :class:`EvidenceBundle` (ADR-0031)

NO es una base de datos. NO es persistencia nueva. Es un artefacto derivado
verificable, mismo patrón que :class:`EvidenceBundle`. Cualquier consumidor
offline puede recomputar y verificar cada eslabón sin acceso a la instancia
origen.

Hard invariant: ``case_id == case_signature``.
"""

from __future__ import annotations

from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from orbital_sentinel.analytics.agent_contract import AgentInput
from orbital_sentinel.analytics.bundles import EvidenceBundle
from orbital_sentinel.analytics.claims import ClaimRegistry
from orbital_sentinel.analytics.evidence_chains import EvidenceChain
from orbital_sentinel.analytics.explanation_agent import ExplanationArtifact
from orbital_sentinel.analytics.hypotheses import HypothesisRegistry
from orbital_sentinel.analytics.investigations.hashing import (
    compute_case_label_hash,
    compute_case_signature,
)

CASE_LAYER_SCHEMA_VERSION = "1.0.0"
CASE_LAYER_ENGINE_VERSION = "1.0.0"
CASE_VERIFIER_ENGINE_VERSION = "1.0.0"

CaseEmitReason = Literal["full_case", "empty_case"]

CaseVerificationFindingType = Literal[
    "case_id_signature_alias_violation",
    "case_signature_recompute_mismatch",
    "embedded_chain_id_mismatch_ref",
    "embedded_hypothesis_registry_id_mismatch_ref",
    "embedded_claim_registry_id_mismatch_ref",
    "embedded_explanation_id_mismatch_ref",
    "embedded_agent_input_id_mismatch_ref",
    "embedded_bundle_id_mismatch_ref",
    "embedded_chain_inconsistent_with_hypothesis",
    "embedded_chain_inconsistent_with_claim_registry",
    "embedded_chain_inconsistent_with_artifact",
    "embedded_chain_inconsistent_with_agent_input",
    "embedded_chain_inconsistent_with_bundle",
    "embedded_hypothesis_inconsistent_with_claim_registry",
    "embedded_claim_registry_inconsistent_with_artifact",
    "embedded_artifact_inconsistent_with_agent_input",
    "embedded_agent_input_inconsistent_with_bundle",
    "case_label_hash_mismatch",
    "case_layer_engine_version_mismatch",
]


class InvestigationCase(BaseModel):
    """Caso de investigación portable y autocontenido.

    Hard invariant: ``case_id == case_signature``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    case_id: str
    case_signature: str
    case_label: str
    case_label_hash: str

    # --- IDs referenciados (redundantes con los embebidos, pero presentes
    # para enabling auditoría sin parseo) ---
    referenced_chain_id: str
    referenced_hypothesis_registry_id: str
    referenced_claim_registry_id: str
    referenced_explanation_id: str
    referenced_agent_input_id: str
    referenced_bundle_id: str

    # --- Payloads embebidos completos (portabilidad ADR-0031 style) ---
    chain: EvidenceChain
    hypothesis_registry: HypothesisRegistry
    claim_registry: ClaimRegistry
    explanation_artifact: ExplanationArtifact
    agent_input: AgentInput
    evidence_bundle: EvidenceBundle

    case_emit_reason: CaseEmitReason
    schema_version: str = Field(default=CASE_LAYER_SCHEMA_VERSION)
    case_layer_engine_version: str = Field(default=CASE_LAYER_ENGINE_VERSION)
    derived_at: AwareDatetime

    @model_validator(mode="after")
    def _case_id_must_equal_signature(self) -> InvestigationCase:
        if self.case_id != self.case_signature:
            raise ValueError(
                "case_id must be a strict alias of case_signature "
                "(ADR-0038 CASE-001); "
                f"case_id={self.case_id!r}, case_signature={self.case_signature!r}."
            )
        expected_label_hash = compute_case_label_hash(self.case_label)
        if self.case_label_hash != expected_label_hash:
            raise ValueError(
                "case_label_hash does not match recomputed hash (ADR-0038); "
                f"got {self.case_label_hash!r}, expected {expected_label_hash!r}.",
            )
        expected = compute_case_signature(
            chain_id=self.referenced_chain_id,
            hypothesis_registry_id=self.referenced_hypothesis_registry_id,
            claim_registry_id=self.referenced_claim_registry_id,
            explanation_id=self.referenced_explanation_id,
            agent_input_id=self.referenced_agent_input_id,
            bundle_id=self.referenced_bundle_id,
            case_label_hash=self.case_label_hash,
            case_layer_engine_version=self.case_layer_engine_version,
        )
        if self.case_signature != expected:
            raise ValueError(
                "case_signature does not match recomputed hash (ADR-0038); "
                f"got {self.case_signature!r}, expected {expected!r}.",
            )
        return self


class CaseVerificationFinding(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    finding_type: CaseVerificationFindingType
    affected_id: str
    expected: str
    actual: str


class CaseVerificationReport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    case_id: str
    is_valid: bool
    n_artifacts_verified: int = Field(ge=0)
    n_findings: int = Field(ge=0)

    case_id_is_alias_of_case_signature: bool
    case_signature_recomputes_correctly: bool
    case_label_hash_recomputes_correctly: bool
    embedded_ids_match_referenced_ids: bool
    embedded_chain_consistent_with_others: bool
    embedded_artifacts_form_valid_pipeline: bool
    case_layer_engine_version_consistent: bool

    findings: list[CaseVerificationFinding]

    verification_hash: str
    verifier_engine_version: str = Field(default=CASE_VERIFIER_ENGINE_VERSION)
    schema_version: str = Field(default=CASE_LAYER_SCHEMA_VERSION)
    verified_at: AwareDatetime
