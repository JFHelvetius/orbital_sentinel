"""Modelos públicos del Agent Input Contract v0.1 (ADR-0032).

Frontera estructural entre la zona determinista del proyecto (ADRs 0000–0031)
y cualquier consumer no determinista downstream (Fase 5b agent, exportadores,
APIs, terceros).

Hard invariant: ``verification_report.is_valid == True`` siempre, enforced por
model_validator. No es posible construir un ``AgentInput`` desde un bundle
inválido.
"""

from __future__ import annotations

import hashlib
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from orbital_sentinel.analytics.bundles.models import (
    BundleVerificationReport,
    EvidenceBundle,
)

CONTRACT_SCHEMA_VERSION = "0.1.0"
"""SemVer del esquema (ADR-0010)."""

CONTRACT_ENGINE_VERSION = "0.1.0"
"""SemVer del motor del contrato (ADR-0010)."""

ConsumerClass = Literal[
    "explanation_agent_v01",
    "report_exporter_v01",
    "external_third_party_v01",
    "api_endpoint_v01",
    "audit_consumer_v01",
]


def compute_agent_input_id(
    *,
    bundle_id: str,
    declared_consumer_class: str,
    contract_engine_version: str,
) -> str:
    """SHA-256 content-addressable del AgentInput.

    Determinístico: mismo bundle + mismo consumer + misma versión motor →
    mismo ``agent_input_id``.
    """
    canonical = "|".join(
        [bundle_id, declared_consumer_class, contract_engine_version]
    )
    return hashlib.sha256(canonical.encode("ascii")).hexdigest()


class AgentInput(BaseModel):
    """Bundle verificado etiquetado para un consumer declarado.

    Hard invariant ADR-0032: ``verification_report.is_valid == True``. Cualquier
    intento de construir un ``AgentInput`` con un report inválido lanza en el
    model_validator.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    # --- Identidad content-addressable ---
    agent_input_id: str = Field(description="SHA-256 sobre (bundle_id, consumer, version).")

    # --- Contenido verificado ---
    bundle: EvidenceBundle = Field(description="EvidenceBundle literal embebido (ADR-0031).")
    verification_report: BundleVerificationReport = Field(
        description="Prueba embebida de que verify_bundle.is_valid=True."
    )

    # --- Destinatario declarado ---
    declared_consumer_class: ConsumerClass = Field(
        description="Clase de consumer downstream que recibirá este AgentInput."
    )

    # --- Versioning (ADR-0010) ---
    contract_schema_version: str = Field(default=CONTRACT_SCHEMA_VERSION)
    contract_engine_version: str = Field(default=CONTRACT_ENGINE_VERSION)

    # --- Metadata operacional ---
    contract_acceptance_at: AwareDatetime

    @model_validator(mode="after")
    def _verification_report_must_be_valid(self) -> AgentInput:
        """Invariante hard de ADR-0032."""
        if self.verification_report.is_valid is not True:
            raise ValueError(
                "AgentInput requires verification_report.is_valid=True "
                "(ADR-0032 invariant). Bundle did not pass verify_bundle."
            )
        if self.verification_report.bundle_id != self.bundle.bundle_id:
            raise ValueError(
                "verification_report.bundle_id must match bundle.bundle_id "
                "(ADR-0032 invariant)."
            )
        return self
