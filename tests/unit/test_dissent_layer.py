"""Tests del Dissent Layer (ADR-0041)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from orbital_sentinel.analytics.dissent import (
    DissentVerificationReport,
    build_dissent_ledger,
    build_dissent_record,
    verify_dissent_ledger,
)
from orbital_sentinel.core.errors import DissentLedgerBuilderError

CLK = datetime(2026, 6, 7, 12, 0, tzinfo=timezone.utc)
TARGET_CASE_ID = "A" * 64
TARGET_CASE_SIG = "A" * 64


def _clock() -> datetime:
    return CLK


def _record(  # type: ignore[no-untyped-def]
    *, idx: int = 0, dissent_type: str = "methodological_objection",
    basis: list[str] | None = None,
    referenced: str = "",
):
    return build_dissent_record(
        target_case_id=TARGET_CASE_ID,
        target_case_signature=TARGET_CASE_SIG,
        dissent_index=idx,
        dissent_type=dissent_type,  # type: ignore[arg-type]
        dissent_basis_evidence_ids=basis,
        referenced_alternative_case_id=referenced,
        clock=_clock,
    )


# --- Build records --------------------------------------------


def test_build_dissent_record_deterministic() -> None:
    r1 = _record()
    r2 = _record()
    assert r1.dissent_id == r2.dissent_id


def test_build_dissent_record_clock_only_affects_emitted_at() -> None:
    def early() -> datetime:
        return datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)

    def late() -> datetime:
        return datetime(2027, 1, 1, 0, 0, tzinfo=timezone.utc)
    r1 = build_dissent_record(
        target_case_id=TARGET_CASE_ID,
        target_case_signature=TARGET_CASE_SIG,
        dissent_index=0,
        dissent_type="methodological_objection",
        clock=early,
    )
    r2 = build_dissent_record(
        target_case_id=TARGET_CASE_ID,
        target_case_signature=TARGET_CASE_SIG,
        dissent_index=0,
        dissent_type="methodological_objection",
        clock=late,
    )
    assert r1.dissent_id == r2.dissent_id
    assert r1.emitted_at != r2.emitted_at


# --- Build ledger ---------------------------------------------


def test_build_empty_ledger() -> None:
    led = build_dissent_ledger(
        target_case_id=TARGET_CASE_ID,
        target_case_signature=TARGET_CASE_SIG,
        records=[],
        clock=_clock,
    )
    assert led.n_records == 0
    assert led.ledger_emit_reason == "empty_ledger"
    assert led.ledger_id == led.ledger_hash


def test_build_single_record_ledger() -> None:
    r = _record()
    led = build_dissent_ledger(
        target_case_id=TARGET_CASE_ID,
        target_case_signature=TARGET_CASE_SIG,
        records=[r],
        clock=_clock,
    )
    assert led.n_records == 1
    assert led.ledger_emit_reason == "records_present"


def test_build_multi_record_ledger_indices_sequential() -> None:
    r0 = _record(idx=0)
    r1 = _record(idx=1, dissent_type="scope_disagreement")
    led = build_dissent_ledger(
        target_case_id=TARGET_CASE_ID,
        target_case_signature=TARGET_CASE_SIG,
        records=[r0, r1],
        clock=_clock,
    )
    assert led.n_records == 2


def test_build_ledger_rejects_target_mismatch() -> None:
    r = build_dissent_record(
        target_case_id="B" * 64,
        target_case_signature="B" * 64,
        dissent_index=0,
        dissent_type="methodological_objection",
        clock=_clock,
    )
    with pytest.raises(DissentLedgerBuilderError, match="different case"):
        build_dissent_ledger(
            target_case_id=TARGET_CASE_ID,
            target_case_signature=TARGET_CASE_SIG,
            records=[r],
            clock=_clock,
        )


def test_build_ledger_rejects_non_sequential_indices() -> None:
    r = _record(idx=5)
    with pytest.raises(DissentLedgerBuilderError, match="sequential"):
        build_dissent_ledger(
            target_case_id=TARGET_CASE_ID,
            target_case_signature=TARGET_CASE_SIG,
            records=[r],
            clock=_clock,
        )


# --- Verifier valid path --------------------------------------


def test_verify_empty_ledger_valid() -> None:
    led = build_dissent_ledger(
        target_case_id=TARGET_CASE_ID,
        target_case_signature=TARGET_CASE_SIG,
        records=[],
        clock=_clock,
    )
    rpt = verify_dissent_ledger(led, clock=_clock)
    assert rpt.is_valid is True
    assert rpt.findings == []


def test_verify_single_record_valid() -> None:
    r = _record()
    led = build_dissent_ledger(
        target_case_id=TARGET_CASE_ID,
        target_case_signature=TARGET_CASE_SIG,
        records=[r],
        clock=_clock,
    )
    rpt = verify_dissent_ledger(led, clock=_clock)
    assert rpt.is_valid is True
    assert rpt.findings == []


def test_verify_all_checks_pass() -> None:
    r = _record()
    led = build_dissent_ledger(
        target_case_id=TARGET_CASE_ID,
        target_case_signature=TARGET_CASE_SIG,
        records=[r],
        clock=_clock,
    )
    rpt = verify_dissent_ledger(led, clock=_clock)
    assert rpt.ledger_id_is_alias_of_ledger_hash is True
    assert rpt.ledger_hash_recomputes_correctly is True
    assert rpt.all_dissent_ids_recompute_correctly is True
    assert rpt.no_duplicate_dissent_ids is True
    assert rpt.dissent_indices_sequential is True
    assert rpt.target_case_consistent_across_records is True
    assert rpt.dissent_type_index_consistent is True
    assert rpt.all_required_fields_present_for_type is True
    assert rpt.dissent_layer_engine_version_consistent is True


# --- Required-field rules -----------------------------------


def test_verify_detects_factual_correction_without_basis() -> None:
    r = _record(dissent_type="factual_correction")
    led = build_dissent_ledger(
        target_case_id=TARGET_CASE_ID,
        target_case_signature=TARGET_CASE_SIG,
        records=[r],
        clock=_clock,
    )
    rpt = verify_dissent_ledger(led, clock=_clock)
    types = [f.finding_type for f in rpt.findings]
    assert "factual_correction_requires_basis_evidence" in types


def test_verify_detects_missing_evidence_without_basis() -> None:
    r = _record(dissent_type="missing_evidence")
    led = build_dissent_ledger(
        target_case_id=TARGET_CASE_ID,
        target_case_signature=TARGET_CASE_SIG,
        records=[r],
        clock=_clock,
    )
    rpt = verify_dissent_ledger(led, clock=_clock)
    types = [f.finding_type for f in rpt.findings]
    assert "missing_evidence_requires_basis_evidence" in types


def test_verify_detects_alternative_explanation_without_referenced_case() -> None:
    r = _record(dissent_type="alternative_explanation")
    led = build_dissent_ledger(
        target_case_id=TARGET_CASE_ID,
        target_case_signature=TARGET_CASE_SIG,
        records=[r],
        clock=_clock,
    )
    rpt = verify_dissent_ledger(led, clock=_clock)
    types = [f.finding_type for f in rpt.findings]
    assert "alternative_explanation_requires_referenced_case" in types


def test_factual_correction_with_basis_valid() -> None:
    r = _record(
        dissent_type="factual_correction",
        basis=["evidence_xyz"],
    )
    led = build_dissent_ledger(
        target_case_id=TARGET_CASE_ID,
        target_case_signature=TARGET_CASE_SIG,
        records=[r],
        clock=_clock,
    )
    rpt = verify_dissent_ledger(led, clock=_clock)
    assert rpt.is_valid is True


def test_alternative_explanation_with_referenced_case_valid() -> None:
    r = _record(
        dissent_type="alternative_explanation",
        referenced="C" * 64,
    )
    led = build_dissent_ledger(
        target_case_id=TARGET_CASE_ID,
        target_case_signature=TARGET_CASE_SIG,
        records=[r],
        clock=_clock,
    )
    rpt = verify_dissent_ledger(led, clock=_clock)
    assert rpt.is_valid is True


# --- Verifier nunca lanza -----------------------------------


def test_verify_never_raises() -> None:
    led = build_dissent_ledger(
        target_case_id=TARGET_CASE_ID,
        target_case_signature=TARGET_CASE_SIG,
        records=[],
        clock=_clock,
    )
    rpt = verify_dissent_ledger(led, clock=_clock)
    assert isinstance(rpt, DissentVerificationReport)


# --- Determinismo del reporte -------------------------------


def test_verify_report_reproducible() -> None:
    r = _record()
    led = build_dissent_ledger(
        target_case_id=TARGET_CASE_ID,
        target_case_signature=TARGET_CASE_SIG,
        records=[r],
        clock=_clock,
    )
    a = verify_dissent_ledger(led, clock=_clock)
    b = verify_dissent_ledger(led, clock=_clock)
    assert a.model_dump(mode="json") == b.model_dump(mode="json")


def test_verify_clock_only_affects_verified_at() -> None:
    r = _record()
    led = build_dissent_ledger(
        target_case_id=TARGET_CASE_ID,
        target_case_signature=TARGET_CASE_SIG,
        records=[r],
        clock=_clock,
    )

    def early() -> datetime:
        return datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)

    def late() -> datetime:
        return datetime(2027, 1, 1, 0, 0, tzinfo=timezone.utc)
    a = verify_dissent_ledger(led, clock=early)
    b = verify_dissent_ledger(led, clock=late)
    assert a.verification_hash == b.verification_hash
    assert a.verified_at != b.verified_at
