"""Pipeline mínimo Raw → Normalized: fetch → persist Raw → normalize → persist Normalized.

Encadena los componentes de Ingestion y Catalog para producir un flujo end-to-end
determinista y testeable sin red.

Posicionamiento arquitectónico
------------------------------
Este módulo es un **workflow de composición** en el sentido de ADR-0002 enmienda 1:
puede importar de cualquier plano lower-numbered porque su trabajo es atar
componentes de varios planos. Si en el futuro se añaden primitivas de scheduling
en ``orchestration/`` (APScheduler, retries, backoff), serán módulos low-level
distintos y seguirán la regla de dependencias hacia abajo sin excepciones.

Garantías
---------
- **Sin red en tests**: si se inyecta un transporte fake al Source, no hay tráfico.
- **Trazabilidad end-to-end**: ``content_hash`` del fetcher == ``content_hash``
  del snapshot Raw == ``content_hash_source`` de cada ``OrbitalElement``.
- **Idempotencia**: re-ejecutar con misma fuente y mismo contenido es no-op en
  Raw y Normalized.
- **Fail-fast en normalización**: si el snapshot contiene un TLE inválido, se
  lanza ``NormalizationError`` **después** de haber persistido Raw. Es deliberado:
  Raw es la fuente de verdad y debe quedar registrada para auditoría del fallo.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone

from orbital_sentinel.catalog.normalizers import (
    NORMALIZER_VERSION,
    normalize_snapshot,
)
from orbital_sentinel.catalog.orbital_elements import OrbitalElementsRepository
from orbital_sentinel.catalog.tle_snapshots import (
    TLESnapshot,
    TLESnapshotsRepository,
)
from orbital_sentinel.core.errors import IngestionError
from orbital_sentinel.ingestion.sources.artifact import RawArtifact, Source


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class IngestResult:
    """Resumen estructurado del resultado de una ejecución del pipeline."""

    artifact: RawArtifact
    snapshot_written: bool
    elements_written: int

    @property
    def is_new(self) -> bool:
        """True si esta ejecución produjo algún cambio en disco."""
        return self.snapshot_written or self.elements_written > 0


class IngestPipeline:
    """Compositor del pipeline mínimo Raw → Normalized.

    Inyectable en su totalidad para tests: ``Source`` con transporte fake,
    repositorios apuntando a ``tmp_path``, reloj determinista.
    """

    def __init__(
        self,
        source: Source,
        snapshots: TLESnapshotsRepository,
        elements: OrbitalElementsRepository,
        *,
        engine_version: str = NORMALIZER_VERSION,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._source = source
        self._snapshots = snapshots
        self._elements = elements
        self._engine_version = engine_version
        self._clock: Callable[[], datetime] = clock if clock is not None else _utc_now

    def ingest(self, dataset: str) -> IngestResult:
        """Ejecuta el pipeline para un dataset.

        Args:
            dataset: identificador del dataset en la fuente (``stations``,
                ``active``, ``catnr-25544``, etc.).

        Raises:
            IngestionError: si los bytes recibidos no son ASCII puro (no se
                pueden almacenar como ``raw_text`` sin pérdida bit-exacta).
            NormalizationError: si el contenido tiene algún TLE malformado.
                Raw queda persistido antes del fallo para auditoría.
        """
        artifact = self._source.fetch(dataset)
        snapshot = self._artifact_to_snapshot(artifact)
        snapshot_written = self._snapshots.insert(snapshot)

        derived_at = self._clock()
        elements = normalize_snapshot(
            snapshot,
            derived_at=derived_at,
            engine_version=self._engine_version,
        )
        elements_written = self._elements.insert_many(elements)

        return IngestResult(
            artifact=artifact,
            snapshot_written=snapshot_written,
            elements_written=elements_written,
        )

    def _artifact_to_snapshot(self, artifact: RawArtifact) -> TLESnapshot:
        try:
            raw_text = artifact.raw_bytes.decode("ascii")
        except UnicodeDecodeError as exc:
            raise IngestionError(
                f"Bytes no ASCII en artifact {artifact.source}/{artifact.dataset}: {exc}"
            ) from exc
        return TLESnapshot(
            content_hash=artifact.content_hash,
            source=artifact.source,
            dataset=artifact.dataset,
            url=artifact.url,
            fetched_at=artifact.fetched_at,
            raw_text=raw_text,
            n_bytes=len(artifact.raw_bytes),
        )
