"""Tests del Revocation Layer (ADR-0039)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from orbital_sentinel.analytics.revocations import (
    RevocationVerificationReport,
    build_revocation_ledger,
    build_revocation_record,
    is_artifact_revoked,
    verify_revocation_ledger,
)
from orbital_sentinel.core.errors import RevocationLedgerBuilderError

CLK = datetime(2026, 6, 7, 12, 0, tzinfo=timezone.utc)


def _clock() -> datetime:
    return CLK


# --- Build records --------------------------------------------


def test_build_revocation_record_minimal() -> None:
    r = build_revocation_record(
        target_artifact_type="investigation_case",
        target_artifact_id="A" * 64,
        target_artifact_signature="A" * 64,
        revocation_reason="voluntary_withdrawal",
        clock=_clock,
    )
    assert r.target_artifact_id == "A" * 64
    assert r.revocation_reason == "voluntary_withdrawal"
    assert r.supporting_evidence_ids == []


def test_build_revocation_record_with_superseding() -> None:
    r = build_revocation_record(
        target_artifact_type="investigation_case",
        target_artifact_id="A" * 64,
        target_artifact_signature="A" * 64,
        revocation_reason="superseded_by_corrected_upstream",
        superseding_artifact_id="B" * 64,
        clock=_clock,
    )
    assert r.superseding_artifact_id == "B" * 64


def test_build_revocation_record_deterministic() -> None:
    r1 = build_revocation_record(
        target_artifact_type="claim_registry",
        target_artifact_id="A" * 64,
        target_artifact_signature="A" * 64,
        revocation_reason="retracted_by_emitter",
        clock=_clock,
    )
    r2 = build_revocation_record(
        target_artifact_type="claim_registry",
        target_artifact_id="A" * 64,
        target_artifact_signature="A" * 64,
        revocation_reason="retracted_by_emitter",
        clock=_clock,
    )
    assert r1.revocation_id == r2.revocation_id


def test_build_revocation_record_clock_only_affects_emitted_at() -> None:
    def early() -> datetime:
        return datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)

    def late() -> datetime:
        return datetime(2027, 1, 1, 0, 0, tzinfo=timezone.utc)
    r1 = build_revocation_record(
        target_artifact_type="claim_registry",
        target_artifact_id="A" * 64,
        target_artifact_signature="A" * 64,
        revocation_reason="retracted_by_emitter",
        clock=early,
    )
    r2 = build_revocation_record(
        target_artifact_type="claim_registry",
        target_artifact_id="A" * 64,
        target_artifact_signature="A" * 64,
        revocation_reason="retracted_by_emitter",
        clock=late,
    )
    assert r1.revocation_id == r2.revocation_id
    assert r1.emitted_at != r2.emitted_at


# --- Build ledger --------------------------------------------


def test_build_empty_ledger() -> None:
    led = build_revocation_ledger([], clock=_clock)
    assert led.n_records == 0
    assert led.ledger_id == led.ledger_hash
    assert led.ledger_emit_reason == "empty_ledger"


def test_build_single_record_ledger() -> None:
    r = build_revocation_record(
        target_artifact_type="evidence_bundle",
        target_artifact_id="A" * 64,
        target_artifact_signature="A" * 64,
        revocation_reason="voluntary_withdrawal",
        clock=_clock,
    )
    led = build_revocation_ledger([r], clock=_clock)
    assert led.n_records == 1
    assert led.ledger_emit_reason == "records_present"
    assert led.ledger_id == led.ledger_hash


def test_build_ledger_rejects_duplicate_targets() -> None:
    r1 = build_revocation_record(
        target_artifact_type="evidence_bundle",
        target_artifact_id="A" * 64,
        target_artifact_signature="A" * 64,
        revocation_reason="voluntary_withdrawal",
        clock=_clock,
    )
    r2 = build_revocation_record(
        target_artifact_type="evidence_bundle",
        target_artifact_id="A" * 64,
        target_artifact_signature="A" * 64,
        revocation_reason="retracted_by_emitter",
        clock=_clock,
    )
    with pytest.raises(RevocationLedgerBuilderError, match="Duplicate"):
        build_revocation_ledger([r1, r2], clock=_clock)


# --- Verifier valid path ---------------------------------------


def test_verify_empty_ledger_valid() -> None:
    led = build_revocation_ledger([], clock=_clock)
    rpt = verify_revocation_ledger(led, clock=_clock)
    assert rpt.is_valid is True
    assert rpt.findings == []


def test_verify_single_record_ledger_valid() -> None:
    r = build_revocation_record(
        target_artifact_type="evidence_bundle",
        target_artifact_id="A" * 64,
        target_artifact_signature="A" * 64,
        revocation_reason="voluntary_withdrawal",
        clock=_clock,
    )
    led = build_revocation_ledger([r], clock=_clock)
    rpt = verify_revocation_ledger(led, clock=_clock)
    assert rpt.is_valid is True
    assert rpt.findings == []
    assert rpt.n_records_verified == 1


def test_verify_all_checks_pass() -> None:
    r = build_revocation_record(
        target_artifact_type="evidence_bundle",
        target_artifact_id="A" * 64,
        target_artifact_signature="A" * 64,
        revocation_reason="voluntary_withdrawal",
        clock=_clock,
    )
    led = build_revocation_ledger([r], clock=_clock)
    rpt = verify_revocation_ledger(led, clock=_clock)
    assert rpt.ledger_id_is_alias_of_ledger_hash is True
    assert rpt.ledger_hash_recomputes_correctly is True
    assert rpt.all_revocation_ids_recompute_correctly is True
    assert rpt.no_duplicate_revocation_ids is True
    assert rpt.no_duplicate_target_artifact_ids is True
    assert rpt.target_index_consistent is True
    assert rpt.revocation_layer_engine_version_consistent is True


# --- Verifier never raises ------------------------------------


def test_verify_never_raises() -> None:
    led = build_revocation_ledger([], clock=_clock)
    rpt = verify_revocation_ledger(led, clock=_clock)
    assert isinstance(rpt, RevocationVerificationReport)


# --- Determinismo del reporte -------------------------------


def test_verify_report_reproducible() -> None:
    r = build_revocation_record(
        target_artifact_type="evidence_bundle",
        target_artifact_id="A" * 64,
        target_artifact_signature="A" * 64,
        revocation_reason="voluntary_withdrawal",
        clock=_clock,
    )
    led = build_revocation_ledger([r], clock=_clock)
    a = verify_revocation_ledger(led, clock=_clock)
    b = verify_revocation_ledger(led, clock=_clock)
    assert a.model_dump(mode="json") == b.model_dump(mode="json")


def test_verify_clock_only_affects_verified_at() -> None:
    r = build_revocation_record(
        target_artifact_type="evidence_bundle",
        target_artifact_id="A" * 64,
        target_artifact_signature="A" * 64,
        revocation_reason="voluntary_withdrawal",
        clock=_clock,
    )
    led = build_revocation_ledger([r], clock=_clock)

    def early() -> datetime:
        return datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)

    def late() -> datetime:
        return datetime(2027, 1, 1, 0, 0, tzinfo=timezone.utc)
    a = verify_revocation_ledger(led, clock=early)
    b = verify_revocation_ledger(led, clock=late)
    assert a.verification_hash == b.verification_hash
    assert a.verified_at != b.verified_at


# --- is_artifact_revoked helper -----------------------------


def test_is_artifact_revoked_returns_record() -> None:
    r = build_revocation_record(
        target_artifact_type="evidence_bundle",
        target_artifact_id="A" * 64,
        target_artifact_signature="A" * 64,
        revocation_reason="voluntary_withdrawal",
        clock=_clock,
    )
    led = build_revocation_ledger([r], clock=_clock)
    found = is_artifact_revoked(led, artifact_id="A" * 64)
    assert found is not None
    assert found.revocation_id == r.revocation_id


def test_is_artifact_revoked_returns_none_when_absent() -> None:
    led = build_revocation_ledger([], clock=_clock)
    assert is_artifact_revoked(led, artifact_id="ZZZ") is None


# --- Required-field rules ----------------------------------


def test_verify_detects_integrity_violation_without_basis() -> None:
    """integrity_violation_discovered requires supporting evidence."""
    r = build_revocation_record(
        target_artifact_type="evidence_bundle",
        target_artifact_id="A" * 64,
        target_artifact_signature="A" * 64,
        revocation_reason="integrity_violation_discovered",
        clock=_clock,
    )
    led = build_revocation_ledger([r], clock=_clock)
    rpt = verify_revocation_ledger(led, clock=_clock)
    types = [f.finding_type for f in rpt.findings]
    assert "supporting_evidence_required_for_reason" in types


def test_verify_detects_superseded_without_superseding_id() -> None:
    r = build_revocation_record(
        target_artifact_type="evidence_bundle",
        target_artifact_id="A" * 64,
        target_artifact_signature="A" * 64,
        revocation_reason="superseded_by_corrected_upstream",
        clock=_clock,
    )
    led = build_revocation_ledger([r], clock=_clock)
    rpt = verify_revocation_ledger(led, clock=_clock)
    types = [f.finding_type for f in rpt.findings]
    assert "superseding_artifact_id_required_for_reason" in types
