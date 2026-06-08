"""Modelos del External Source Provenance Layer v1 (ADR-0040).

Cierra el primer eslabón de la cadena verificable hacia abajo: documenta de
qué fuente externa (Celestrak, Space-Track, fichero offline, etc.) provienen
los TLEs raw que dieron origen a cada :class:`DerivedEvidence` de un bundle.

Este layer NO descarga datos. NO valida URLs. NO interpreta. Sólo registra
content-addressablemente lo que el fetch infrastructure declara haber traído.
La integración con el fetch real (ADR-0011/ADR-0012) es responsabilidad de
una futura ADR; v1 acepta los registros como inputs explícitos.

Hard invariants enforced por model_validator:

* ``ExternalSourceRecord``: ``source_record_id`` recompute correctamente.
* ``ExternalSourceRegistry``: ``registry_id == registry_hash``.
"""

from __future__ import annotations

from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from orbital_sentinel.analytics.external_sources.hashing import (
    compute_external_source_record_id,
    compute_external_source_registry_hash,
)

SOURCE_LAYER_SCHEMA_VERSION = "1.0.0"
SOURCE_LAYER_ENGINE_VERSION = "1.0.0"
SOURCE_VERIFIER_ENGINE_VERSION = "1.0.0"

SourceProvider = Literal[
    "celestrak",
    "space_track",
    "norad",
    "manual_offline_import",
    "test_fixture",
]

SourceContentType = Literal[
    "tle_text",
    "json_api",
    "csv",
]

SourceRegistryEmitReason = Literal[
    "records_present", "empty_registry",
]

SourceVerificationFindingType = Literal[
    "source_record_id_recompute_mismatch",
    "duplicate_source_record_id",
    "registry_id_signature_alias_violation",
    "registry_hash_recompute_mismatch",
    "n_records_count_mismatch",
    "source_record_to_evidence_index_mismatch",
    "evidence_to_source_record_index_mismatch",
    "evidence_not_covered_by_any_source_record",
    "source_record_references_unknown_evidence",
    "source_record_with_empty_evidence_set",
    "unsupported_source_provider",
    "unsupported_source_content_type",
    "source_bundle_id_mismatch",
    "source_layer_engine_version_mismatch",
    "source_payload_size_negative",
]


class ExternalSourceRecord(BaseModel):
    """Una operación de ingesta externa que produjo evidencia primaria."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_record_id: str
    source_provider: SourceProvider
    source_url: str = Field(
        description=(
            "URI lógica del recurso (e.g., 'https://celestrak.org/NORAD/"
            "elements/gp.php?CATNR=12345'). Se almacena como literal; el "
            "layer no la dereferencia."
        ),
    )
    source_dataset_identifier: str = Field(
        description=(
            "Nombre canónico del dataset/endpoint (e.g., 'active.txt', "
            "'gp.php?CATNR=12345'). Permite agrupar fetches del mismo origen."
        ),
    )
    fetched_at: AwareDatetime = Field(
        description="Instante UTC declarado de descarga del payload.",
    )
    source_payload_hash: str = Field(
        description="SHA-256 de los bytes literales del payload externo.",
    )
    source_payload_size_bytes: int = Field(ge=0)
    source_content_type: SourceContentType
    schema_version: str = Field(default=SOURCE_LAYER_SCHEMA_VERSION)

    @model_validator(mode="after")
    def _source_record_id_must_recompute(self) -> ExternalSourceRecord:
        expected = compute_external_source_record_id(
            source_provider=self.source_provider,
            source_url=self.source_url,
            source_dataset_identifier=self.source_dataset_identifier,
            fetched_at=self.fetched_at,
            source_payload_hash=self.source_payload_hash,
            source_payload_size_bytes=self.source_payload_size_bytes,
            source_content_type=self.source_content_type,
            source_layer_engine_version=SOURCE_LAYER_ENGINE_VERSION,
        )
        if self.source_record_id != expected:
            raise ValueError(
                "source_record_id does not match recomputed hash "
                "(ADR-0040 SRC-001); "
                f"got {self.source_record_id!r}, expected {expected!r}."
            )
        return self


class ExternalSourceRegistry(BaseModel):
    """Registro content-addressable de procedencia externa para un bundle.

    Hard invariant ADR-0040: ``registry_id == registry_hash``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    registry_id: str
    registry_hash: str
    source_bundle_id: str = Field(
        description="bundle_id objetivo cubierto por este registro de procedencia.",
    )
    records: list[ExternalSourceRecord]
    n_records: int = Field(ge=0)
    source_record_to_evidence_index: dict[str, list[str]] = Field(
        description="Forward index: source_record_id → [evidence_id, …].",
    )
    evidence_to_source_record_index: dict[str, list[str]] = Field(
        description="Reverse index: evidence_id → [source_record_id, …].",
    )
    registry_emit_reason: SourceRegistryEmitReason
    schema_version: str = Field(default=SOURCE_LAYER_SCHEMA_VERSION)
    source_layer_engine_version: str = Field(default=SOURCE_LAYER_ENGINE_VERSION)
    derived_at: AwareDatetime

    @model_validator(mode="after")
    def _registry_id_must_equal_hash(self) -> ExternalSourceRegistry:
        if self.registry_id != self.registry_hash:
            raise ValueError(
                "registry_id must be a strict alias of registry_hash "
                "(ADR-0040 SRC-008); "
                f"got registry_id={self.registry_id!r}, "
                f"registry_hash={self.registry_hash!r}."
            )
        expected = compute_external_source_registry_hash(
            source_bundle_id=self.source_bundle_id,
            source_record_ids=[r.source_record_id for r in self.records],
            source_layer_engine_version=self.source_layer_engine_version,
        )
        if self.registry_hash != expected:
            raise ValueError(
                "registry_hash does not match recomputed hash (ADR-0040); "
                f"got {self.registry_hash!r}, expected {expected!r}.",
            )
        return self


class SourceVerificationFinding(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    finding_type: SourceVerificationFindingType
    affected_id: str
    expected: str
    actual: str


class SourceVerificationReport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    registry_id: str
    is_valid: bool
    n_records_verified: int = Field(ge=0)
    n_findings: int = Field(ge=0)

    registry_id_is_alias_of_registry_hash: bool
    registry_hash_recomputes_correctly: bool
    all_source_record_ids_recompute_correctly: bool
    no_duplicate_source_record_ids: bool
    forward_index_consistent: bool
    reverse_index_consistent: bool
    all_evidence_ids_covered: bool
    source_bundle_id_matches: bool
    source_layer_engine_version_consistent: bool

    findings: list[SourceVerificationFinding]

    verification_hash: str
    verifier_engine_version: str = Field(default=SOURCE_VERIFIER_ENGINE_VERSION)
    schema_version: str = Field(default=SOURCE_LAYER_SCHEMA_VERSION)
    verified_at: AwareDatetime
