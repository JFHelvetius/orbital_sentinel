"""Canonicalización SHA-256 del Bundle Layer (ADR-0031).

Esta es la **única fuente** de hashing del bundle layer. Ningún otro módulo
(``builder``, ``verifier``, ``models``, ``cli``) debe computar SHA-256 ad-hoc.
Cualquier divergencia en la canonicalización rompería la verificabilidad
contractual del bundle.

Convenciones canónicas v0.1:

* JSON con ``sort_keys=True`` (claves recursivamente ordenadas).
* JSON con ``separators=(",", ":")`` (compacto, sin whitespace).
* ``default=str`` para fallback de tipos no nativos (defensa; los inputs
  normalmente son dicts JSON-puros tras ``model_dump(mode="json")``).
* Encoding UTF-8 para input al hash.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from orbital_sentinel.analytics.bundles.models import BundledEvidence


def canonical_json(obj: Any) -> str:
    """Serialización JSON canónica: misma entrada → mismo string siempre."""
    return json.dumps(
        obj,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def compute_payload_hash(payload: dict[str, Any]) -> str:
    """SHA-256 sobre un ``honesty_payload`` en su forma canónica.

    Misma semántica que :func:`compute_payload_hash` de ``analytics.explanation``,
    pero implementada localmente para que el bundle layer mantenga única
    fuente de hashing. Los resultados son bit-exactos entre los dos módulos
    porque ambos usan exactamente el mismo helper canónico.
    """
    return hashlib.sha256(
        canonical_json(payload).encode("utf-8")
    ).hexdigest()


def compute_bundle_payload_signature(
    payloads: Iterable[BundledEvidence],
) -> str:
    """SHA-256 sobre la lista ordenada de :class:`BundledEvidence`.

    Ordenamiento: ``(derived_evidence.event_epoch asc, evidence_id asc)``.
    Estabilidad bit-exacta independiente del orden de input.
    """
    sorted_payloads = sorted(
        payloads,
        key=lambda bp: (bp.derived_evidence.event_epoch, bp.evidence_id),
    )
    payload_dumps = [bp.model_dump(mode="json") for bp in sorted_payloads]
    return hashlib.sha256(
        canonical_json(payload_dumps).encode("utf-8")
    ).hexdigest()


def compute_bundle_signature(
    *,
    context_id: str,
    bundle_payload_signature: str,
    bundle_engine_version: str,
) -> str:
    """SHA-256 envelope sobre ``(context_id, bundle_payload_signature, version)``.

    Es el identificador content-addressable del bundle. ``bundle_id`` es
    alias estricto de este valor (model_validator de :class:`EvidenceBundle`
    lo enforce).
    """
    canonical = "|".join(
        [
            context_id,
            bundle_payload_signature,
            bundle_engine_version,
        ]
    )
    return hashlib.sha256(canonical.encode("ascii")).hexdigest()
