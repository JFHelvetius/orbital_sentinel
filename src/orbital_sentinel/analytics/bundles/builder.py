"""Builder del :class:`EvidenceBundle` (ADR-0031).

Función pura. Responsabilidad **única**: tomar un :class:`ExplanationContext`
+ un :class:`EvidenceCatalog` y producir un bundle autocontenido.

Esta capa NO valida, NO verifica, NO repara. Si el contexto referencia un
evidence_id ausente del catálogo, simplemente no se incluye en
``evidence_payloads`` y el verifier downstream lo reportará como
``evidence_id_missing_from_payloads``.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone

from orbital_sentinel.analytics.bundles.hashing import (
    compute_bundle_payload_signature,
    compute_bundle_signature,
    compute_payload_hash,
)
from orbital_sentinel.analytics.bundles.models import (
    BUNDLE_ENGINE_VERSION,
    BundledEvidence,
    EvidenceBundle,
)
from orbital_sentinel.analytics.evidence.models import EvidenceCatalog
from orbital_sentinel.analytics.explanation.models import ExplanationContext


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def build_evidence_bundle(
    context: ExplanationContext,
    catalog: EvidenceCatalog,
    *,
    clock: Callable[[], datetime] | None = None,
) -> EvidenceBundle:
    """Empaqueta ``context`` + payloads del ``catalog`` en un bundle
    autocontenido y firmado.

    El ``clock`` solo se usa para ``derived_at`` (metadata operacional).
    ``bundle_id``, ``bundle_signature`` y ``bundle_payload_signature`` son
    content-addressable y no dependen del instante de construcción.
    """
    # 1. Mapa evidence_id → DerivedEvidence (filtrado al objeto del contexto).
    catalog_by_id = {
        ev.evidence_id: ev
        for ev in catalog.list_by_norad(context.object_id)
    }

    # 2. Construir BundledEvidence por cada referencia del contexto.
    bundled: list[BundledEvidence] = []
    for ref in context.evidence_references:
        derived = catalog_by_id.get(ref.evidence_id)
        if derived is None:
            # No incluido: el verifier reportará evidence_id_missing.
            continue
        recomputed = compute_payload_hash(derived.honesty_payload)
        bundled.append(
            BundledEvidence(
                evidence_id=ref.evidence_id,
                derived_evidence=derived,
                recomputed_payload_hash=recomputed,
                payload_integrity_verified_at_build=(
                    recomputed == ref.honesty_payload_hash
                ),
            )
        )

    # 3. Firmas anidadas.
    payload_sig = compute_bundle_payload_signature(bundled)
    bundle_sig = compute_bundle_signature(
        context_id=context.context_id,
        bundle_payload_signature=payload_sig,
        bundle_engine_version=BUNDLE_ENGINE_VERSION,
    )

    derived_at = (clock or _utc_now)()
    return EvidenceBundle(
        bundle_id=bundle_sig,          # alias estricto (model_validator lo enforce)
        bundle_signature=bundle_sig,
        bundle_payload_signature=payload_sig,
        object_id=context.object_id,
        context=context,
        evidence_payloads=bundled,
        n_evidence_payloads=len(bundled),
        derived_at=derived_at,
    )
