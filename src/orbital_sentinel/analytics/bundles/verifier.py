"""Verifier del :class:`EvidenceBundle` (ADR-0031).

Función pura. Responsabilidad **única**: dada una :class:`EvidenceBundle`
ya estructuralmente válida (model_validator pasó), recomputa todas sus
firmas anidadas y reporta integridad como :class:`BundleVerificationReport`.

Garantías contractuales:

* NUNCA muta el bundle.
* NUNCA lanza por fallos de integridad — los reporta en ``integrity_failures``.
* SIEMPRE retorna un reporte, incluso si todo falla.
* Determinístico: bundle fijo + clock fijo → mismo reporte bit-exacto.
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
    BundleIntegrityFailure,
    BundleVerificationReport,
    EvidenceBundle,
    IntegrityFailureType,
)
from orbital_sentinel.analytics.explanation.models import (
    compute_context_id,
    compute_source_catalog_signature,
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _fail(
    failure_type: IntegrityFailureType,
    affected_id: str,
    expected: str,
    actual: str,
) -> BundleIntegrityFailure:
    return BundleIntegrityFailure(
        failure_type=failure_type,
        affected_id=affected_id,
        expected=expected,
        actual=actual,
    )


def verify_bundle(
    bundle: EvidenceBundle,
    *,
    clock: Callable[[], datetime] | None = None,
) -> BundleVerificationReport:
    """Recomputa todas las firmas del ``bundle`` y reporta integridad.

    Args:
        bundle: bundle ya validado estructuralmente (model_validator pasó).
        clock: inyectable para tests deterministas; solo afecta
            ``verified_at``.

    Returns:
        :class:`BundleVerificationReport` con ``is_valid`` y enumeración
        de fallos. Nunca lanza.
    """
    failures: list[BundleIntegrityFailure] = []

    # --- 1. Coherencia de evidence_ids entre context y payloads -----------
    context_refs_by_id = {
        ref.evidence_id: ref for ref in bundle.context.evidence_references
    }
    payloads_by_id = {bp.evidence_id: bp for bp in bundle.evidence_payloads}
    context_ids = set(context_refs_by_id.keys())
    payload_ids = set(payloads_by_id.keys())

    for missing_id in sorted(context_ids - payload_ids):
        failures.append(_fail(
            "evidence_id_missing_from_payloads",
            affected_id=missing_id,
            expected="present_in_evidence_payloads",
            actual="absent",
        ))
    for unexpected_id in sorted(payload_ids - context_ids):
        failures.append(_fail(
            "evidence_id_unexpected_in_payloads",
            affected_id=unexpected_id,
            expected="absent_from_evidence_payloads",
            actual="present",
        ))

    # --- 2. Hashes de payload --------------------------------------------
    n_total = len(bundle.evidence_payloads)
    n_valid_hash = 0
    n_invalid_hash = 0
    for bp in bundle.evidence_payloads:
        ref = context_refs_by_id.get(bp.evidence_id)
        if ref is None:
            # Reportado arriba como unexpected; no contamos hash.
            continue
        recomputed = compute_payload_hash(bp.derived_evidence.honesty_payload)
        if recomputed == ref.honesty_payload_hash:
            n_valid_hash += 1
        else:
            n_invalid_hash += 1
            failures.append(_fail(
                "payload_hash_mismatch",
                affected_id=bp.evidence_id,
                expected=ref.honesty_payload_hash,
                actual=recomputed,
            ))

    # --- 3. source_catalog_signature recomputable ------------------------
    recomputed_catalog_sig = compute_source_catalog_signature(
        ref.evidence_id for ref in bundle.context.evidence_references
    )
    catalog_sig_ok = (
        recomputed_catalog_sig == bundle.context.source_catalog_signature
    )
    if not catalog_sig_ok:
        failures.append(_fail(
            "source_catalog_signature_mismatch",
            affected_id="context",
            expected=bundle.context.source_catalog_signature,
            actual=recomputed_catalog_sig,
        ))

    # --- 4. context_id recomputable -------------------------------------
    recomputed_ctx_id = compute_context_id(
        object_id=bundle.context.object_id,
        explanation_engine_version=bundle.context.explanation_engine_version,
        source_catalog_signature=bundle.context.source_catalog_signature,
    )
    ctx_id_ok = recomputed_ctx_id == bundle.context.context_id
    if not ctx_id_ok:
        failures.append(_fail(
            "context_id_mismatch",
            affected_id="context",
            expected=bundle.context.context_id,
            actual=recomputed_ctx_id,
        ))

    # --- 5. bundle_payload_signature recomputable -----------------------
    recomputed_payload_sig = compute_bundle_payload_signature(
        bundle.evidence_payloads
    )
    payload_sig_ok = (
        recomputed_payload_sig == bundle.bundle_payload_signature
    )
    if not payload_sig_ok:
        failures.append(_fail(
            "bundle_payload_signature_mismatch",
            affected_id="bundle",
            expected=bundle.bundle_payload_signature,
            actual=recomputed_payload_sig,
        ))

    # --- 6. bundle_signature recomputable -------------------------------
    recomputed_bundle_sig = compute_bundle_signature(
        context_id=bundle.context.context_id,
        bundle_payload_signature=bundle.bundle_payload_signature,
        bundle_engine_version=bundle.bundle_engine_version,
    )
    bundle_sig_ok = recomputed_bundle_sig == bundle.bundle_signature
    if not bundle_sig_ok:
        failures.append(_fail(
            "bundle_signature_mismatch",
            affected_id="bundle",
            expected=bundle.bundle_signature,
            actual=recomputed_bundle_sig,
        ))

    # --- 7. bundle_id es alias de bundle_signature ----------------------
    # En la práctica es imposible que falle: model_validator de
    # EvidenceBundle ya enforce este invariante. Lo reportamos para
    # documentar el contrato y por defensa en profundidad.
    id_is_alias = bundle.bundle_id == bundle.bundle_signature
    if not id_is_alias:
        failures.append(_fail(
            "bundle_id_signature_alias_violation",
            affected_id="bundle",
            expected=bundle.bundle_signature,
            actual=bundle.bundle_id,
        ))

    is_valid = (
        n_invalid_hash == 0
        and catalog_sig_ok
        and ctx_id_ok
        and payload_sig_ok
        and bundle_sig_ok
        and id_is_alias
        and not (context_ids - payload_ids)
        and not (payload_ids - context_ids)
    )

    verified_at = (clock or _utc_now)()
    return BundleVerificationReport(
        bundle_id=bundle.bundle_id,
        is_valid=is_valid,
        n_payloads_total=n_total,
        n_payloads_with_valid_hash=n_valid_hash,
        n_payloads_with_invalid_hash=n_invalid_hash,
        context_id_recomputes_correctly=ctx_id_ok,
        source_catalog_signature_recomputes_correctly=catalog_sig_ok,
        bundle_payload_signature_recomputes_correctly=payload_sig_ok,
        bundle_signature_recomputes_correctly=bundle_sig_ok,
        bundle_id_is_alias_of_bundle_signature=id_is_alias,
        integrity_failures=failures,
        verified_at=verified_at,
    )
