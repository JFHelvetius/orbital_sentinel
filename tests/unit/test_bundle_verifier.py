"""Tests del :func:`verify_bundle` (ADR-0031).

Garantías que cubren estos tests:

* Bundle válido → ``is_valid=True``, ``integrity_failures=[]``.
* Bundle manipulado → ``is_valid=False`` + failures enumerados.
* El verifier NUNCA lanza por integridad rota.
* El verifier SIEMPRE retorna un :class:`BundleVerificationReport`.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from orbital_sentinel.analytics.bundles import (
    VERIFIER_ENGINE_VERSION,
    BundledEvidence,
    BundleVerificationReport,
    EvidenceBundle,
    build_evidence_bundle,
    compute_payload_hash,
    verify_bundle,
)
from orbital_sentinel.analytics.evidence import (
    EVIDENCE_TYPE_MANEUVER,
    DerivedEvidence,
    EvidenceCatalog,
    compute_evidence_id,
)
from orbital_sentinel.analytics.explanation import build_explanation_context

EPOCH = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)
DERIVED_AT = datetime(2026, 6, 6, 12, 0, tzinfo=timezone.utc)


def _fixed_clock() -> datetime:
    return DERIVED_AT


def _make_evidence(
    *, detector_event_id: str = "evt", days_offset: float = 0.0,
    payload: dict | None = None,
) -> DerivedEvidence:
    ep = EPOCH + timedelta(days=days_offset)
    return DerivedEvidence(
        evidence_id=compute_evidence_id(
            source_detector="maneuver_detection_v01",
            object_id=25544,
            detector_event_id=detector_event_id,
            event_epoch=ep,
            analysis_engine_version="0.1.0",
        ),
        object_id=25544,
        evidence_type=EVIDENCE_TYPE_MANEUVER,
        source_detector="maneuver_detection_v01",
        detector_event_id=detector_event_id,
        event_epoch=ep,
        honesty_payload=payload or {"detection_method_name": "test"},
        analysis_engine_version="0.1.0",
    )


def _build_valid_bundle(*evs: DerivedEvidence) -> EvidenceBundle:
    cat = EvidenceCatalog.from_evidence(list(evs), derived_at=DERIVED_AT)
    ctx = build_explanation_context(cat, object_id=25544, clock=_fixed_clock)
    return build_evidence_bundle(ctx, cat, clock=_fixed_clock)


# --- Bundle válido ----------------------------------------------------


def test_verify_valid_empty_bundle_is_valid() -> None:
    bundle = _build_valid_bundle()
    rpt = verify_bundle(bundle, clock=_fixed_clock)
    assert rpt.is_valid is True
    assert rpt.integrity_failures == []


def test_verify_valid_single_evidence_bundle_is_valid() -> None:
    bundle = _build_valid_bundle(_make_evidence(detector_event_id="x"))
    rpt = verify_bundle(bundle, clock=_fixed_clock)
    assert rpt.is_valid is True
    assert rpt.n_payloads_total == 1
    assert rpt.n_payloads_with_valid_hash == 1
    assert rpt.n_payloads_with_invalid_hash == 0


def test_verify_valid_multi_evidence_bundle_is_valid() -> None:
    a = _make_evidence(detector_event_id="a", days_offset=0)
    b = _make_evidence(detector_event_id="b", days_offset=1)
    c = _make_evidence(detector_event_id="c", days_offset=2)
    bundle = _build_valid_bundle(a, b, c)
    rpt = verify_bundle(bundle, clock=_fixed_clock)
    assert rpt.is_valid is True
    assert rpt.n_payloads_with_valid_hash == 3


def test_verify_report_carries_bundle_id() -> None:
    bundle = _build_valid_bundle()
    rpt = verify_bundle(bundle, clock=_fixed_clock)
    assert rpt.bundle_id == bundle.bundle_id


def test_verify_report_versioning_field_v01() -> None:
    bundle = _build_valid_bundle()
    rpt = verify_bundle(bundle, clock=_fixed_clock)
    assert rpt.verifier_engine_version == VERIFIER_ENGINE_VERSION == "0.1.0"


def test_verify_all_individual_checks_pass_for_valid_bundle() -> None:
    bundle = _build_valid_bundle(_make_evidence(detector_event_id="x"))
    rpt = verify_bundle(bundle, clock=_fixed_clock)
    assert rpt.context_id_recomputes_correctly is True
    assert rpt.source_catalog_signature_recomputes_correctly is True
    assert rpt.bundle_payload_signature_recomputes_correctly is True
    assert rpt.bundle_signature_recomputes_correctly is True
    assert rpt.bundle_id_is_alias_of_bundle_signature is True


# --- Detección de tampering ------------------------------------------


def _swap_payload_in_bundle(bundle: EvidenceBundle, new_payload: dict) -> EvidenceBundle:
    """Reconstruye un bundle con un payload alterado y firmas conservadas
    (simula tampering: el atacante cambió el payload pero las firmas viejas
    no fueron recalculadas)."""
    bp_original = bundle.evidence_payloads[0]
    de_tampered = bp_original.derived_evidence.model_copy(update={
        "honesty_payload": new_payload,
    })
    bp_tampered = BundledEvidence(
        evidence_id=bp_original.evidence_id,
        derived_evidence=de_tampered,
        recomputed_payload_hash=bp_original.recomputed_payload_hash,  # NO recomputado
        payload_integrity_verified_at_build=True,
    )
    return bundle.model_copy(update={
        "evidence_payloads": [bp_tampered, *bundle.evidence_payloads[1:]],
        "n_evidence_payloads": bundle.n_evidence_payloads,
    })


def test_verify_detects_payload_hash_mismatch() -> None:
    bundle = _build_valid_bundle(_make_evidence(detector_event_id="x"))
    tampered = _swap_payload_in_bundle(bundle, {"detection_method_name": "TAMPERED"})
    rpt = verify_bundle(tampered, clock=_fixed_clock)
    assert rpt.is_valid is False
    types = [f.failure_type for f in rpt.integrity_failures]
    assert "payload_hash_mismatch" in types


def test_verify_detects_bundle_payload_signature_mismatch_on_tampered_bundle() -> None:
    """Cuando el payload cambia, el bundle_payload_signature recomputado difiere."""
    bundle = _build_valid_bundle(_make_evidence(detector_event_id="x"))
    tampered = _swap_payload_in_bundle(bundle, {"detection_method_name": "TAMPERED"})
    rpt = verify_bundle(tampered, clock=_fixed_clock)
    types = [f.failure_type for f in rpt.integrity_failures]
    assert "bundle_payload_signature_mismatch" in types


def test_verify_detects_bundle_signature_mismatch_when_bundle_payload_signature_altered() -> None:
    bundle = _build_valid_bundle(_make_evidence(detector_event_id="x"))
    tampered = bundle.model_copy(update={"bundle_payload_signature": "0" * 64})
    rpt = verify_bundle(tampered, clock=_fixed_clock)
    assert rpt.is_valid is False
    types = [f.failure_type for f in rpt.integrity_failures]
    # bundle_signature también debe fallar porque depende del payload signature
    assert "bundle_signature_mismatch" in types


def test_verify_detects_context_id_mismatch() -> None:
    bundle = _build_valid_bundle(_make_evidence(detector_event_id="x"))
    tampered_ctx = bundle.context.model_copy(update={"context_id": "0" * 64})
    tampered = bundle.model_copy(update={"context": tampered_ctx})
    rpt = verify_bundle(tampered, clock=_fixed_clock)
    assert rpt.is_valid is False
    types = [f.failure_type for f in rpt.integrity_failures]
    assert "context_id_mismatch" in types


def test_verify_detects_source_catalog_signature_mismatch() -> None:
    bundle = _build_valid_bundle(_make_evidence(detector_event_id="x"))
    tampered_ctx = bundle.context.model_copy(update={
        "source_catalog_signature": "0" * 64,
    })
    tampered = bundle.model_copy(update={"context": tampered_ctx})
    rpt = verify_bundle(tampered, clock=_fixed_clock)
    assert rpt.is_valid is False
    types = [f.failure_type for f in rpt.integrity_failures]
    assert "source_catalog_signature_mismatch" in types


def test_verify_detects_evidence_id_missing_from_payloads() -> None:
    """Si el payload list pierde una referencia que el context sí declara."""
    a = _make_evidence(detector_event_id="a")
    b = _make_evidence(detector_event_id="b", days_offset=1)
    bundle = _build_valid_bundle(a, b)
    # Quitamos un payload pero el context lo sigue referenciando
    tampered = bundle.model_copy(update={
        "evidence_payloads": [bundle.evidence_payloads[0]],
        "n_evidence_payloads": 1,
    })
    rpt = verify_bundle(tampered, clock=_fixed_clock)
    assert rpt.is_valid is False
    types = [f.failure_type for f in rpt.integrity_failures]
    assert "evidence_id_missing_from_payloads" in types


def test_verify_detects_evidence_id_unexpected_in_payloads() -> None:
    """Si el payload list tiene un id que el context no declara."""
    a = _make_evidence(detector_event_id="a")
    bundle = _build_valid_bundle(a)
    # Construir un payload extra
    extra_evidence = _make_evidence(detector_event_id="EXTRA", days_offset=5)
    extra_bp = BundledEvidence(
        evidence_id=extra_evidence.evidence_id,
        derived_evidence=extra_evidence,
        recomputed_payload_hash=compute_payload_hash(extra_evidence.honesty_payload),
        payload_integrity_verified_at_build=True,
    )
    tampered = bundle.model_copy(update={
        "evidence_payloads": [*bundle.evidence_payloads, extra_bp],
        "n_evidence_payloads": bundle.n_evidence_payloads + 1,
    })
    rpt = verify_bundle(tampered, clock=_fixed_clock)
    assert rpt.is_valid is False
    types = [f.failure_type for f in rpt.integrity_failures]
    assert "evidence_id_unexpected_in_payloads" in types


# --- El verifier nunca lanza ----------------------------------------


def test_verify_never_raises_on_tampered_bundle() -> None:
    bundle = _build_valid_bundle(_make_evidence(detector_event_id="x"))
    tampered = _swap_payload_in_bundle(bundle, {"x": 1})
    # No try/except: el test confía que la función completa sin lanzar.
    rpt = verify_bundle(tampered, clock=_fixed_clock)
    assert isinstance(rpt, BundleVerificationReport)


def test_verify_never_raises_on_signature_corruption() -> None:
    bundle = _build_valid_bundle(_make_evidence(detector_event_id="x"))
    tampered = bundle.model_copy(update={
        "bundle_signature": bundle.bundle_signature,  # mantiene alias
        # el alias hard invariant prevent corrupting bundle_id/bundle_signature
        # separately at the model layer; corrupt indirectly via payload_signature
        "bundle_payload_signature": "deadbeef" * 8,
    })
    rpt = verify_bundle(tampered, clock=_fixed_clock)
    assert isinstance(rpt, BundleVerificationReport)


# --- Determinismo del reporte ---------------------------------------


def test_verify_report_reproducible_across_runs() -> None:
    bundle = _build_valid_bundle(_make_evidence(detector_event_id="x"))
    a = verify_bundle(bundle, clock=_fixed_clock)
    b = verify_bundle(bundle, clock=_fixed_clock)
    assert a.model_dump(mode="json") == b.model_dump(mode="json")


def test_verify_report_clock_only_affects_verified_at() -> None:
    bundle = _build_valid_bundle(_make_evidence(detector_event_id="x"))

    def early() -> datetime:
        return datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)

    def late() -> datetime:
        return datetime(2027, 1, 1, 0, 0, tzinfo=timezone.utc)
    a = verify_bundle(bundle, clock=early)
    b = verify_bundle(bundle, clock=late)
    assert a.is_valid == b.is_valid
    assert a.bundle_id == b.bundle_id
    assert a.integrity_failures == b.integrity_failures
    assert a.verified_at != b.verified_at


def test_verify_report_roundtrip() -> None:
    bundle = _build_valid_bundle(_make_evidence(detector_event_id="x"))
    rpt = verify_bundle(bundle, clock=_fixed_clock)
    raw = rpt.model_dump(mode="json")
    rehydrated = BundleVerificationReport.model_validate(raw)
    assert rehydrated.model_dump(mode="json") == raw


# --- Múltiples fallos enumerados -----------------------------------


def test_verify_aggregates_multiple_failures() -> None:
    """Tampering en varios campos → todos los fallos en una sola pasada."""
    bundle = _build_valid_bundle(_make_evidence(detector_event_id="x"))
    tampered_ctx = bundle.context.model_copy(update={
        "context_id": "0" * 64,
        "source_catalog_signature": "0" * 64,
    })
    tampered = bundle.model_copy(update={"context": tampered_ctx})
    rpt = verify_bundle(tampered, clock=_fixed_clock)
    types = {f.failure_type for f in rpt.integrity_failures}
    assert "context_id_mismatch" in types
    assert "source_catalog_signature_mismatch" in types


# --- Ciclo build + verify es self-cerrado --------------------------


def test_build_then_verify_always_valid_on_fresh_bundle() -> None:
    """Cualquier bundle recién construido debe verificar como valid."""
    evs = [
        _make_evidence(detector_event_id="a", days_offset=0),
        _make_evidence(detector_event_id="b", days_offset=1),
        _make_evidence(detector_event_id="c", days_offset=2),
    ]
    bundle = _build_valid_bundle(*evs)
    rpt = verify_bundle(bundle, clock=_fixed_clock)
    assert rpt.is_valid is True
    assert rpt.integrity_failures == []
