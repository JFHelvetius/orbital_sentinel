"""Validación de integridad referencial entre ``tle_snapshots`` y ``orbital_elements``.

Verifica los invariantes que el pipeline normal mantiene por construcción, para
detectar:

* Corrupción manual (borrar un archivo Parquet de Raw).
* Inserciones ad-hoc en Normalized sin pasar por el normalizador.
* Bugs futuros en migraciones o en el normalizador que rompan la trazabilidad.

Los invariantes verificados están documentados explícitamente en
``docs/architecture/invariants.md``.
"""

from __future__ import annotations

from collections import defaultdict

from pydantic import BaseModel, ConfigDict, Field

from orbital_sentinel.catalog.orbital_elements import OrbitalElementsRepository
from orbital_sentinel.catalog.tle_snapshots import TLESnapshotsRepository


class OrphanElement(BaseModel):
    """Una fila de ``orbital_elements`` cuyo ``content_hash_source`` no existe en Raw."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    content_hash_source: str
    tle_index: int
    engine_version: str


class IndexGap(BaseModel):
    """Discontinuidad en ``tle_index`` dentro de un grupo ``(snapshot, engine_version)``."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    content_hash_source: str
    engine_version: str
    expected_size: int
    missing_indices: list[int]


class IntegrityReport(BaseModel):
    """Resultado de :func:`verify_integrity`.

    ``orphan_elements`` y ``index_gaps`` son **violaciones**: indican
    inconsistencia entre Raw y Normalized o estructura corrupta del catálogo.

    ``unnormalized_snapshots`` es **informativo**: un Raw puede existir sin
    Normalized correspondiente durante operación normal (la normalización
    puede ir detrás de la ingesta).
    """

    model_config = ConfigDict(extra="forbid")

    orphan_elements: list[OrphanElement] = Field(default_factory=list)
    index_gaps: list[IndexGap] = Field(default_factory=list)
    unnormalized_snapshots: list[str] = Field(default_factory=list)

    @property
    def has_violations(self) -> bool:
        return bool(self.orphan_elements) or bool(self.index_gaps)


def verify_integrity(
    snapshots: TLESnapshotsRepository,
    elements: OrbitalElementsRepository,
) -> IntegrityReport:
    """Verifica los invariantes I1 e I2 entre Raw y Normalized.

    Coste: O(N) en filas Normalized + O(M) en filas Raw. Apropiado para
    catálogos de Fase 1 (10⁴–10⁵ filas). Si escala, optimizar con queries
    DuckDB selectivas.
    """
    raw_hashes = {s.content_hash for s in snapshots.iter_all()}
    all_elements = list(elements.iter_all())

    # I1: integridad referencial Normalized → Raw
    orphans = [
        OrphanElement(
            content_hash_source=el.content_hash_source,
            tle_index=el.tle_index,
            engine_version=el.engine_version,
        )
        for el in all_elements
        if el.content_hash_source not in raw_hashes
    ]

    # I2: continuidad de tle_index por grupo (content_hash_source, engine_version)
    groups: dict[tuple[str, str], list[int]] = defaultdict(list)
    for el in all_elements:
        groups[(el.content_hash_source, el.engine_version)].append(el.tle_index)

    index_gaps: list[IndexGap] = []
    for (source_hash, engine_version), indices in groups.items():
        if not indices:
            continue
        n = len(indices)
        expected = set(range(n))
        actual = set(indices)
        if expected != actual:
            index_gaps.append(
                IndexGap(
                    content_hash_source=source_hash,
                    engine_version=engine_version,
                    expected_size=n,
                    missing_indices=sorted(expected - actual),
                )
            )

    # Informativo: Raw sin Normalized correspondiente
    normalized_sources = {el.content_hash_source for el in all_elements}
    unnormalized = sorted(raw_hashes - normalized_sources)

    return IntegrityReport(
        orphan_elements=orphans,
        index_gaps=index_gaps,
        unnormalized_snapshots=unnormalized,
    )
