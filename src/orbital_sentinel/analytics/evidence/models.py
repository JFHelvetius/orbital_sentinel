"""Modelos públicos del Derived Evidence Layer v0.1 (ADR-0029).

Consolidación read-only de outputs de detectores en registros auditables.
La capa no clasifica, no infiere causas, no asigna probabilidades. Garantiza
que los honesty fields de los detectores upstream sobreviven en el
``honesty_payload`` de cada ``DerivedEvidence``.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from datetime import datetime
from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

EVIDENCE_LAYER_SCHEMA_VERSION = "0.1.0"
"""SemVer del esquema de evidencia (ADR-0010)."""

EVIDENCE_LAYER_ENGINE_VERSION = "0.1.0"
"""SemVer del motor de consolidación (ADR-0010)."""

# Identificadores autorizados de detector. Cualquier otro valor es input
# inválido en este ADR; nuevos detectores requieren su propio ADR.
SourceDetector = Literal[
    "maneuver_detection_v01",
    "anomaly_detection_v01",
    "conjunction_detection_v01",
]

EVIDENCE_TYPE_MANEUVER = "maneuver_jump_detected"
EVIDENCE_TYPE_ANOMALY = "anomaly_observed"
EVIDENCE_TYPE_CONJUNCTION = "conjunction_detected"


def compute_evidence_id(
    *,
    source_detector: str,
    object_id: int,
    detector_event_id: str,
    event_epoch: datetime,
    analysis_engine_version: str,
) -> str:
    """SHA-256 content-addressable sobre la identidad observacional.

    Determinístico: mismas entradas → mismo hash → mismo ``evidence_id``.
    Permite que el catálogo de-duplique en reinvocaciones.
    """
    canonical = "|".join(
        [
            source_detector,
            str(object_id),
            detector_event_id,
            event_epoch.isoformat(),
            analysis_engine_version,
        ]
    )
    return hashlib.sha256(canonical.encode("ascii")).hexdigest()


class DerivedEvidence(BaseModel):
    """Registro consolidado de un finding del detector upstream.

    NO interpreta. NO clasifica. NO asigna probabilidad. Preserva el
    ``honesty_payload`` con los campos críticos del detector original para
    que cualquier consumidor downstream tenga el contexto estadístico
    necesario.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    # --- Identidad content-addressable ---
    evidence_id: str = Field(description="SHA-256 hex; computed via compute_evidence_id.")

    # --- Identidad del objeto observado ---
    object_id: int = Field(description="NORAD cat ID del objeto.")

    # --- Tipo y origen ---
    evidence_type: str = Field(
        description="Identificador del tipo de evidencia (e.g. maneuver_jump_detected)."
    )
    source_detector: SourceDetector = Field(
        description="Identificador del detector origen, restringido a v0.1."
    )
    detector_event_id: str = Field(
        description="Identificador del evento dentro del output del detector."
    )

    # --- Tiempo del evento subyacente ---
    event_epoch: AwareDatetime = Field(
        description="Instante UTC del evento observado por el detector."
    )

    # --- Payload de honestidad propagado (ADR-0028 § Honesty Requirements) ---
    honesty_payload: dict[str, Any] = Field(
        description="Campos de honestidad preservados del detector upstream."
    )

    # --- Versioning (ADR-0010) ---
    analysis_engine_version: str = Field(
        description="engine_version del detector upstream que produjo el evento."
    )
    schema_version: str = Field(
        default=EVIDENCE_LAYER_SCHEMA_VERSION,
        description="SemVer del esquema del DerivedEvidence (ADR-0029).",
    )

    # --- Honesty global ---
    is_apparent_not_confirmed: bool = Field(default=True)


class EvidenceCatalog(BaseModel):
    """Contenedor inmutable de :class:`DerivedEvidence` con filtros deterministas.

    El catálogo en sí no persiste — ADR-0029 prohíbe persistencia nueva. Es
    estructura en memoria diseñada para consulta inmediata por el CLI o por
    consumidores in-process.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    evidence: list[DerivedEvidence]
    n_evidence: int = Field(ge=0)
    schema_version: str = Field(default=EVIDENCE_LAYER_SCHEMA_VERSION)
    catalog_engine_version: str = Field(default=EVIDENCE_LAYER_ENGINE_VERSION)
    derived_at: AwareDatetime

    @classmethod
    def from_evidence(
        cls,
        items: Iterable[DerivedEvidence],
        *,
        derived_at: datetime,
    ) -> EvidenceCatalog:
        """Construye un catálogo con ordenamiento determinístico.

        Orden: ``(event_epoch asc, evidence_id asc)``. De-duplica por
        ``evidence_id``.
        """
        seen: dict[str, DerivedEvidence] = {}
        for ev in items:
            seen.setdefault(ev.evidence_id, ev)
        ordered = sorted(
            seen.values(), key=lambda e: (e.event_epoch, e.evidence_id)
        )
        return cls(
            evidence=ordered,
            n_evidence=len(ordered),
            derived_at=derived_at,
        )

    # --- Filtros (read-only, devuelven listas nuevas ordenadas) ----------

    def list_all(self) -> list[DerivedEvidence]:
        return list(self.evidence)

    def list_by_norad(self, norad_cat_id: int) -> list[DerivedEvidence]:
        return [e for e in self.evidence if e.object_id == norad_cat_id]

    def list_by_detector(
        self, source_detector: str
    ) -> list[DerivedEvidence]:
        return [e for e in self.evidence if e.source_detector == source_detector]

    def list_by_epoch_range(
        self, *, start: datetime | None = None, end: datetime | None = None
    ) -> list[DerivedEvidence]:
        result = list(self.evidence)
        if start is not None:
            result = [e for e in result if e.event_epoch >= start]
        if end is not None:
            result = [e for e in result if e.event_epoch <= end]
        return result
