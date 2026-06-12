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
from typing import Any

from orbital_sentinel.analytics.bundles import EvidenceBundle
from orbital_sentinel.analytics.evidence import CONSUMED_SOURCE_HASHES_KEY
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


def _consumed_source_hashes(honesty_payload: dict[str, Any]) -> list[str]:
    """Lee ``consumed_source_hashes`` del honesty_payload (ADR-0043).

    Devuelve lista limpia de hex strings, o ``[]`` si la clave no existe
    (evidencia pre-0043) o no es una lista de strings.
    """
    raw = honesty_payload.get(CONSUMED_SOURCE_HASHES_KEY)
    if not isinstance(raw, (list, tuple)):
        return []
    return [h for h in raw if isinstance(h, str) and h]


def derive_external_source_registry_for_bundle(
    bundle: EvidenceBundle,
    *,
    tle_snapshots_repo: TLESnapshotsRepository,
    orbital_elements_repo: OrbitalElementsRepository,
    clock: Callable[[], datetime] | None = None,
) -> ExternalSourceRegistry:
    """Deriva el :class:`ExternalSourceRegistry` correspondiente a un bundle.

    Granularidad por-evidencia (ADR-0043) con fallback por-objeto (ADR-0042):

    1. Para cada evidencia, determina sus ``content_hash_source`` consumidos:

       * Si su ``honesty_payload`` declara ``consumed_source_hashes`` (los TLEs
         exactos que el detector consumió, ADR-0043), se usan directamente.
       * Si no (bundle pre-0043), se cae al path por-objeto de ADR-0042:
         ``OrbitalElementsRepository.find_all_by_norad_id(object_id)`` →
         conjunto de hashes que contribuyeron observación al objeto.

    2. Para cada ``content_hash_source`` único (unión sobre todas las
       evidencias), recupera :class:`TLESnapshot` desde Raw y lo convierte a
       :class:`ExternalSourceRecord` determinístico.
    3. Compone ``evidence_to_source_record_mapping``: cada ``evidence_id``
       apunta al conjunto de records de SUS hashes consumidos.

    Si un ``content_hash_source`` no existe en Raw (cache purgado), se omite
    silenciosamente; el verifier detectará la cobertura faltante via
    ``evidence_not_covered_by_any_source_record``.

    Raises:
        ExternalSourceRegistryBuilderError: si el bundle tiene evidencia
            pero ningún snapshot fue encontrado en Raw (catalog vacío o
            bundle construido fuera del flujo persistido).
    """
    # Paso 1: hashes consumidos por evidencia (per-evidencia o fallback).
    object_hash_cache: dict[int, list[str]] = {}
    evidence_to_hashes: dict[str, list[str]] = {}
    for bp in bundle.evidence_payloads:
        consumed = _consumed_source_hashes(bp.derived_evidence.honesty_payload)
        if consumed:
            evidence_to_hashes[bp.evidence_id] = sorted(set(consumed))
            continue
        obj = bp.derived_evidence.object_id
        if obj not in object_hash_cache:
            elements = orbital_elements_repo.find_all_by_norad_id(obj)
            object_hash_cache[obj] = sorted({
                e.content_hash_source for e in elements
            })
        evidence_to_hashes[bp.evidence_id] = object_hash_cache[obj]

    # Paso 2: records para la unión de hashes consumidos.
    all_hash_sources: list[str] = sorted({
        ch for hashes in evidence_to_hashes.values() for ch in hashes
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

    # Paso 3: mapping por evidencia desde sus propios hashes.
    mapping: dict[str, list[str]] = {}
    for bp in bundle.evidence_payloads:
        hashes = evidence_to_hashes[bp.evidence_id]
        mapping[bp.evidence_id] = sorted({
            hash_to_record_id[ch]
            for ch in hashes
            if ch in hash_to_record_id
        })

    return build_external_source_registry(
        bundle, records, mapping, clock=clock,
    )
