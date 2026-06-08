"""Modelos públicos del Verifiable Evidence Bundle Layer v0.1 (ADR-0031).

Artefacto autocontenido y verificable que empaqueta:

* Un :class:`ExplanationContext` (ADR-0030) literal.
* Cada :class:`DerivedEvidence` referenciado por el contexto con su payload
  completo.
* Firmas SHA-256 anidadas que cualquier consumidor offline puede
  recomputar y validar.

Invariante crítico (ADR-0031 recomendación arquitectónica):
``bundle_id == bundle_signature`` siempre, enforced por model_validator.

Esta capa NO interpreta, NO clasifica, NO valida la "veracidad" de la
evidencia. Solo prueba **integridad de contenido** entre la creación y el
consumo del bundle.
"""

from __future__ import annotations

from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from orbital_sentinel.analytics.evidence.models import DerivedEvidence
from orbital_sentinel.analytics.explanation.models import ExplanationContext

BUNDLE_SCHEMA_VERSION = "0.1.0"
"""SemVer del esquema de bundle (ADR-0010)."""

BUNDLE_ENGINE_VERSION = "0.1.0"
"""SemVer del motor de construcción (ADR-0010)."""

VERIFIER_ENGINE_VERSION = "0.1.0"
"""SemVer del motor de verificación (ADR-0010)."""

IntegrityFailureType = Literal[
    "payload_hash_mismatch",
    "context_id_mismatch",
    "source_catalog_signature_mismatch",
    "bundle_payload_signature_mismatch",
    "bundle_signature_mismatch",
    "bundle_id_signature_alias_violation",
    "evidence_id_missing_from_payloads",
    "evidence_id_unexpected_in_payloads",
]


class BundledEvidence(BaseModel):
    """Un :class:`DerivedEvidence` empaquetado con su hash recomputado al
    construir el bundle.

    A diferencia de :class:`ExplanationEvidenceReference` (que solo lleva
    hash), aquí viaja el ``derived_evidence`` **completo** con su
    ``honesty_payload`` para que el consumidor pueda recomputar e independent-
    verificar.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    evidence_id: str
    derived_evidence: DerivedEvidence
    recomputed_payload_hash: str = Field(
        description="SHA-256 del honesty_payload computed at build time."
    )
    payload_integrity_verified_at_build: bool = Field(
        description=(
            "True si el hash recomputado coincide con el "
            "honesty_payload_hash del ExplanationEvidenceReference correspondiente."
        )
    )


class BundleIntegrityFailure(BaseModel):
    """Una violación de integridad reportada por :func:`verify_bundle`.

    Contrato cerrado de tipos de fallo. Cualquier modo de fallo nuevo
    requerirá enmienda al ADR-0031 y bump de versión.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    failure_type: IntegrityFailureType
    affected_id: str = Field(
        description="evidence_id, 'context' o 'bundle' según contexto del fallo."
    )
    expected: str
    actual: str


class EvidenceBundle(BaseModel):
    """Artefacto autocontenido y portátil con context + evidencia + firmas.

    Invariante hard: ``bundle_id == bundle_signature``. El model_validator
    rechaza cualquier construcción que viole el alias.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    # --- Identidad content-addressable ---
    bundle_id: str = Field(
        description=(
            "Alias estricto de bundle_signature. ADR-0031 recomendación: "
            "una sola identidad content-addressable, no dos identificadores "
            "para el mismo contenido."
        )
    )
    bundle_signature: str = Field(
        description="SHA-256 sobre (context_id, bundle_payload_signature, version)."
    )
    bundle_payload_signature: str = Field(
        description="SHA-256 sobre los evidence_payloads ordenados canónicamente."
    )

    # --- Identidad observacional ---
    object_id: int

    # --- Contenido ---
    context: ExplanationContext = Field(
        description="ExplanationContext literal embebido (ADR-0030)."
    )
    evidence_payloads: list[BundledEvidence] = Field(
        description="DerivedEvidence completos referenciados por el context."
    )
    n_evidence_payloads: int = Field(ge=0)

    # --- Versioning (ADR-0010) ---
    schema_version: str = Field(default=BUNDLE_SCHEMA_VERSION)
    bundle_engine_version: str = Field(default=BUNDLE_ENGINE_VERSION)
    derived_at: AwareDatetime

    @model_validator(mode="after")
    def _bundle_id_must_equal_bundle_signature(self) -> EvidenceBundle:
        """Invariante hard de ADR-0031: bundle_id es alias estricto.

        Una construcción donde ``bundle_id != bundle_signature`` es violación
        contractual del ADR-0031 y debe fallar en la construcción, no en
        verificación tardía.
        """
        if self.bundle_id != self.bundle_signature:
            raise ValueError(
                "bundle_id must be a strict alias of bundle_signature "
                "(ADR-0031 invariant); "
                f"bundle_id={self.bundle_id!r} "
                f"bundle_signature={self.bundle_signature!r}"
            )
        return self


class BundleVerificationReport(BaseModel):
    """Reporte determinístico de integridad emitido por :func:`verify_bundle`.

    El verifier NUNCA lanza por fallos de integridad: siempre retorna este
    reporte. El caller inspecciona ``is_valid`` y ``integrity_failures``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    bundle_id: str
    is_valid: bool

    # --- Contadores agregados ---
    n_payloads_total: int = Field(ge=0)
    n_payloads_with_valid_hash: int = Field(ge=0)
    n_payloads_with_invalid_hash: int = Field(ge=0)

    # --- Checks individuales ---
    context_id_recomputes_correctly: bool
    source_catalog_signature_recomputes_correctly: bool
    bundle_payload_signature_recomputes_correctly: bool
    bundle_signature_recomputes_correctly: bool
    bundle_id_is_alias_of_bundle_signature: bool

    # --- Fallos enumerados ---
    integrity_failures: list[BundleIntegrityFailure]

    # --- Versioning ---
    verifier_engine_version: str = Field(default=VERIFIER_ENGINE_VERSION)
    verified_at: AwareDatetime
