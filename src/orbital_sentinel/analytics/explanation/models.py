"""Modelos públicos del Explanation Context Layer v0.1 (ADR-0030).

Vista estructurada y determinista de un :class:`EvidenceCatalog` para un
objeto. La capa **no interpreta**, **no clasifica**, **no infiere causas**,
**no asigna probabilidades**. Solo proyecta evidencia ya emitida por
detectores upstream en una forma estable consumible por downstream
(LLMs, APIs, dashboards, exportadores, reportes, herramientas externas).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

EXPLANATION_LAYER_SCHEMA_VERSION = "0.1.0"
"""SemVer del esquema (ADR-0010)."""

EXPLANATION_LAYER_ENGINE_VERSION = "0.1.0"
"""SemVer del motor de proyección (ADR-0010)."""

CANONICAL_DETECTORS_V01: tuple[str, ...] = (
    "anomaly_detection_v01",
    "conjunction_detection_v01",
    "maneuver_detection_v01",
)
"""Tupla canónica e inmutable de detectores v0.1, orden alfabético.

Un nuevo detector requerirá una enmienda a ADR-0030 que lo incorpore.
"""

EVIDENCE_TYPES_V01: tuple[str, ...] = (
    "anomaly_observed",
    "conjunction_detected",
    "maneuver_jump_detected",
)
"""Tupla canónica e inmutable de evidence_types v0.1, orden alfabético."""

CanonicalDetector = Literal[
    "anomaly_detection_v01",
    "conjunction_detection_v01",
    "maneuver_detection_v01",
]


# --- Helpers deterministas de hashing -----------------------------------


def compute_payload_hash(payload: dict[str, Any]) -> str:
    """SHA-256 sobre JSON canónico (``sort_keys=True``, separadores compactos).

    Idempotente y reproducible: dos dicts equivalentes producen el mismo
    hash independientemente del orden de inserción de las keys.
    """
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def compute_source_catalog_signature(evidence_ids: Iterable[str]) -> str:
    """SHA-256 sobre la firma del catálogo (evidence_ids ordenados)."""
    sorted_ids = sorted(evidence_ids)
    canonical = ",".join(sorted_ids)
    return hashlib.sha256(canonical.encode("ascii")).hexdigest()


def compute_context_id(
    *,
    object_id: int,
    explanation_engine_version: str,
    source_catalog_signature: str,
) -> str:
    """SHA-256 content-addressable del contexto.

    Determinístico: misma evidencia + misma versión del motor → mismo
    ``context_id``. No incluye ``derived_at`` ni metadata operacional.
    """
    canonical = "|".join(
        [
            str(object_id),
            explanation_engine_version,
            source_catalog_signature,
        ]
    )
    return hashlib.sha256(canonical.encode("ascii")).hexdigest()


# --- Modelos auxiliares ------------------------------------------------


class ExplanationEvidenceReference(BaseModel):
    """Puntero ligero a un :class:`DerivedEvidence` con verificación de integridad.

    No duplica el ``honesty_payload``; preserva su hash para que el
    consumidor pueda verificar que el payload original no fue alterado.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    evidence_id: str
    object_id: int
    event_epoch: AwareDatetime
    source_detector: CanonicalDetector
    evidence_type: str
    detector_event_id: str
    honesty_payload_hash: str
    analysis_engine_version: str


class ExplanationDetectorSummary(BaseModel):
    """Resumen por detector dentro del scope del contexto.

    Siempre presente en :class:`ExplanationContext.detector_summaries`
    para cada detector de ``CANONICAL_DETECTORS_V01``, aunque
    ``n_events = 0``. Shape predecible.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_detector: CanonicalDetector
    n_events: int = Field(ge=0)
    first_event_epoch: AwareDatetime | None = None
    last_event_epoch: AwareDatetime | None = None
    evidence_ids: list[str] = Field(default_factory=list)
    evidence_type_breakdown: dict[str, int] = Field(default_factory=dict)


class ExplanationTimelineEntry(BaseModel):
    """Una entrada en la línea temporal consolidada."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    epoch: AwareDatetime
    evidence_id: str
    source_detector: CanonicalDetector
    evidence_type: str
    honesty_payload_hash: str


class ExplanationTimeline(BaseModel):
    """Secuencia temporal consolidada de toda la evidencia del objeto."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    entries: list[ExplanationTimelineEntry]
    n_entries: int = Field(ge=0)
    first_epoch: AwareDatetime | None = None
    last_epoch: AwareDatetime | None = None


# --- Modelo raíz --------------------------------------------------------


class ExplanationContext(BaseModel):
    """Vista consolidada para un objeto, computada determinísticamente desde
    un :class:`EvidenceCatalog`.

    No interpreta. No clasifica. Solo agrega y proyecta. El consumidor
    downstream (LLM, API, dashboard, exportador) tiene aquí toda la
    estructura necesaria para razonar sobre la evidencia sin re-leer el
    catálogo subyacente.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    # --- Identidad ---
    object_id: int
    context_id: str = Field(description="SHA-256 content-addressable.")
    source_catalog_signature: str = Field(
        description="SHA-256 sobre evidence_ids ordenados del objeto."
    )

    # --- Counts ---
    n_evidence_total: int = Field(ge=0)

    # --- Cobertura temporal ---
    coverage_window_start: AwareDatetime | None = None
    coverage_window_end: AwareDatetime | None = None
    coverage_duration_seconds: float | None = Field(default=None, ge=0.0)

    # --- Agregaciones ---
    evidence_type_counts: dict[str, int] = Field(default_factory=dict)
    detector_summaries: list[ExplanationDetectorSummary]
    timeline: ExplanationTimeline
    evidence_references: list[ExplanationEvidenceReference]

    # --- Versioning ---
    schema_version: str = Field(default=EXPLANATION_LAYER_SCHEMA_VERSION)
    explanation_engine_version: str = Field(
        default=EXPLANATION_LAYER_ENGINE_VERSION
    )
    derived_at: AwareDatetime
