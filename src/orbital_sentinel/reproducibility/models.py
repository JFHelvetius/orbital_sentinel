"""Modelos del Installation Self-Verification (ADR-0013 enmienda 2).

Reporte content-addressable producido por :func:`verify_installation`.
"""

from __future__ import annotations

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

REPRODUCIBILITY_PACKAGE_VERSION = "1.0.0"
"""SemVer del módulo de auto-verificación (ADR-0010)."""


class HashMismatch(BaseModel):
    """Una discrepancia individual entre hash producido y hash frozen."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    artifact_key: str
    expected: str
    actual: str


class InstallationVerificationReport(BaseModel):
    """Reporte determinista de auto-verificación de instalación.

    Nunca lanzado por el verifier; siempre retornado. El caller inspecciona
    ``is_valid`` y ``mismatches``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    contract_version: str = Field(
        description="SemVer del contrato cryptográfico frozen en vectors.json.",
    )
    frozen_at: str = Field(
        description="Fecha de congelación del contrato (ISO date).",
    )
    is_valid: bool
    n_hashes_verified: int = Field(ge=0)
    n_mismatches: int = Field(ge=0)

    adrs_covered: list[str]
    mismatches: list[HashMismatch]
    package_version: str = Field(default=REPRODUCIBILITY_PACKAGE_VERSION)
    verified_at: AwareDatetime
