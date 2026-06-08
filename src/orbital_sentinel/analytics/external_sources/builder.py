"""Builder del External Source Provenance Layer (ADR-0040)."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from datetime import datetime, timezone

from orbital_sentinel.analytics.bundles import EvidenceBundle
from orbital_sentinel.analytics.external_sources.hashing import (
    compute_external_source_record_id,
    compute_external_source_registry_hash,
)
from orbital_sentinel.analytics.external_sources.models import (
    SOURCE_LAYER_ENGINE_VERSION,
    ExternalSourceRecord,
    ExternalSourceRegistry,
    SourceContentType,
    SourceProvider,
    SourceRegistryEmitReason,
)
from orbital_sentinel.core.errors import ExternalSourceRegistryBuilderError


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def build_external_source_record(
    *,
    source_provider: SourceProvider,
    source_url: str,
    source_dataset_identifier: str,
    fetched_at: datetime,
    source_payload_hash: str,
    source_payload_size_bytes: int,
    source_content_type: SourceContentType,
) -> ExternalSourceRecord:
    """Construye un :class:`ExternalSourceRecord` content-addressable."""
    rid = compute_external_source_record_id(
        source_provider=source_provider,
        source_url=source_url,
        source_dataset_identifier=source_dataset_identifier,
        fetched_at=fetched_at,
        source_payload_hash=source_payload_hash,
        source_payload_size_bytes=source_payload_size_bytes,
        source_content_type=source_content_type,
        source_layer_engine_version=SOURCE_LAYER_ENGINE_VERSION,
    )
    return ExternalSourceRecord(
        source_record_id=rid,
        source_provider=source_provider,
        source_url=source_url,
        source_dataset_identifier=source_dataset_identifier,
        fetched_at=fetched_at,
        source_payload_hash=source_payload_hash,
        source_payload_size_bytes=source_payload_size_bytes,
        source_content_type=source_content_type,
    )


def build_external_source_registry(
    bundle: EvidenceBundle,
    records: Iterable[ExternalSourceRecord],
    evidence_to_source_record_mapping: Mapping[str, Iterable[str]],
    *,
    clock: Callable[[], datetime] | None = None,
) -> ExternalSourceRegistry:
    """Construye un :class:`ExternalSourceRegistry` para un bundle dado.

    Args:
        bundle: Bundle objetivo. El registry queda atado a su ``bundle_id``.
        records: ``ExternalSourceRecord`` aportados por el fetch infra.
        evidence_to_source_record_mapping: mapping evidence_id → set de
            source_record_ids que ingirieron esa evidencia.

    Raises:
        ExternalSourceRegistryBuilderError: si algún evidence_id del
            bundle no aparece en el mapping, o si el mapping apunta a un
            source_record_id no presente en ``records``.
    """
    records_list = list(records)
    rec_by_id = {r.source_record_id: r for r in records_list}
    bundle_evs = {bp.evidence_id for bp in bundle.evidence_payloads}

    # --- mapping coherence checks ---------------------------------
    if bundle_evs and not records_list:
        raise ExternalSourceRegistryBuilderError(
            "Bundle has evidence but no source records were provided.",
        )
    for ev in bundle_evs:
        if ev not in evidence_to_source_record_mapping:
            raise ExternalSourceRegistryBuilderError(
                f"evidence_id {ev[:12]}… not covered by mapping.",
            )
    for ev, srcs in evidence_to_source_record_mapping.items():
        for s in srcs:
            if s not in rec_by_id:
                raise ExternalSourceRegistryBuilderError(
                    f"Mapping references unknown source_record_id "
                    f"{s[:12]}… for evidence {ev[:12]}….",
                )

    # --- Forward index: source_record_id → [evidence_id, …] -------
    forward: dict[str, list[str]] = {r.source_record_id: [] for r in records_list}
    for ev, srcs in evidence_to_source_record_mapping.items():
        if ev not in bundle_evs:
            continue
        for s in srcs:
            forward.setdefault(s, []).append(ev)
    forward_ordered = {k: sorted(forward[k]) for k in sorted(forward.keys())}

    # --- Reverse index: evidence_id → [source_record_id, …] ------
    reverse: dict[str, list[str]] = {}
    for ev in bundle_evs:
        srcs = evidence_to_source_record_mapping.get(ev, [])
        reverse[ev] = sorted(srcs)
    reverse_ordered = {k: reverse[k] for k in sorted(reverse.keys())}

    emit_reason: SourceRegistryEmitReason = (
        "empty_registry" if not records_list else "records_present"
    )
    registry_hash = compute_external_source_registry_hash(
        source_bundle_id=bundle.bundle_id,
        source_record_ids=[r.source_record_id for r in records_list],
        source_layer_engine_version=SOURCE_LAYER_ENGINE_VERSION,
    )
    derived_at = (clock or _utc_now)()
    return ExternalSourceRegistry(
        registry_id=registry_hash,
        registry_hash=registry_hash,
        source_bundle_id=bundle.bundle_id,
        records=records_list,
        n_records=len(records_list),
        source_record_to_evidence_index=forward_ordered,
        evidence_to_source_record_index=reverse_ordered,
        registry_emit_reason=emit_reason,
        derived_at=derived_at,
    )
