"""Derivación automática de :class:`ExternalSourceRegistry` desde Raw + Normalized (ADR-0042).

Función pura. Lee de los repositorios persistidos
:class:`TLESnapshotsRepository` (capa Raw) y
:class:`OrbitalElementsRepository` (capa Normalized) para construir el
registry correspondiente a un :class:`EvidenceBundle` sin intervención
manual del operador.

Cierra el ciclo declarado en ADR-0040: la promesa fundacional de
trazabilidad hasta el dato externo opera ahora automáticamente cuando el
bundle proviene del catalog persistido.

Garantías:

* **Read-only**: jamás escribe en repos ni filesystem.
* **Determinista**: mismos repos + mismo bundle → mismo ``registry_id``.
* **Pura**: clock sólo afecta ``derived_at``.
* **Removible**: borrar este módulo deja v1 declarativo intacto.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from orbital_sentinel.analytics.bundles import EvidenceBundle
from orbital_sentinel.analytics.external_sources.builder import (
    build_external_source_record,
    build_external_source_registry,
)
from orbital_sentinel.analytics.external_sources.models import (
    ExternalSourceRegistry,
    SourceProvider,
)
from orbital_sentinel.catalog.orbital_elements import OrbitalElementsRepository
from orbital_sentinel.catalog.tle_snapshots import TLESnapshotsRepository


def _map_provider(source_name: str) -> SourceProvider:
    """Mapea ``TLESnapshot.source`` a un ``SourceProvider`` literal cerrado.

    Conserva fidelity cuando el nombre del fetcher coincide con un literal
    soportado; cae a ``manual_offline_import`` para fuentes no enumeradas
    en v1.
    """
    if source_name == "celestrak":
        return "celestrak"
    if source_name == "space_track":
        return "space_track"
    if source_name == "norad":
        return "norad"
    if source_name == "test_fixture":
        return "test_fixture"
    return "manual_offline_import"


def derive_external_source_registry_for_bundle(
    bundle: EvidenceBundle,
    *,
    tle_snapshots_repo: TLESnapshotsRepository,
    orbital_elements_repo: OrbitalElementsRepository,
    clock: Callable[[], datetime] | None = None,
) -> ExternalSourceRegistry:
    """Deriva el :class:`ExternalSourceRegistry` correspondiente a un bundle.

    Algoritmo:

    1. Recolecta los ``object_id`` distintos de ``bundle.evidence_payloads``.
    2. Para cada uno, consulta
       :meth:`OrbitalElementsRepository.find_all_by_norad_id` para recuperar
       el conjunto de ``content_hash_source`` que contribuyeron observación
       a ese objeto.
    3. Para cada ``content_hash_source`` único, recupera
       :class:`TLESnapshot` desde Raw y lo convierte a
       :class:`ExternalSourceRecord` determinístico.
    4. Compone ``evidence_to_source_record_mapping``: cada ``evidence_id``
       apunta al conjunto de records que cubren su ``object_id``.

    Si un ``content_hash_source`` referenciado en Normalized no existe en
    Raw (cache purgado), se omite silenciosamente; el verifier detectará
    la cobertura faltante via ``evidence_not_covered_by_any_source_record``.

    Raises:
        ExternalSourceRegistryBuilderError: si el bundle tiene evidencia
            pero ningún snapshot fue encontrado en Raw (catalog vacío o
            bundle construido fuera del flujo persistido).
    """
    bundle_object_ids: set[int] = {
        bp.derived_evidence.object_id for bp in bundle.evidence_payloads
    }

    object_to_hash_sources: dict[int, list[str]] = {}
    for obj in sorted(bundle_object_ids):
        elements = orbital_elements_repo.find_all_by_norad_id(obj)
        object_to_hash_sources[obj] = sorted({
            e.content_hash_source for e in elements
        })

    all_hash_sources: list[str] = sorted({
        ch for srcs in object_to_hash_sources.values() for ch in srcs
    })

    hash_to_record_id: dict[str, str] = {}
    records = []
    for ch in all_hash_sources:
        snap = tle_snapshots_repo.get(ch)
        if snap is None:
            continue
        rec = build_external_source_record(
            source_provider=_map_provider(snap.source),
            source_url=snap.url,
            source_dataset_identifier=snap.dataset,
            fetched_at=snap.fetched_at,
            source_payload_hash=snap.content_hash,
            source_payload_size_bytes=snap.n_bytes,
            source_content_type="tle_text",
        )
        records.append(rec)
        hash_to_record_id[ch] = rec.source_record_id

    mapping: dict[str, list[str]] = {}
    for bp in bundle.evidence_payloads:
        obj = bp.derived_evidence.object_id
        hashes_for_obj = object_to_hash_sources.get(obj, [])
        mapping[bp.evidence_id] = sorted({
            hash_to_record_id[ch]
            for ch in hashes_for_obj
            if ch in hash_to_record_id
        })

    return build_external_source_registry(
        bundle, records, mapping, clock=clock,
    )
