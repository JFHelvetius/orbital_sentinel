"""CLI integration tests para ``orbital-sentinel self-verify`` (ADR-0013 enmienda 2)."""

from __future__ import annotations

import io
import json
import time
from contextlib import redirect_stdout

from orbital_sentinel.orchestration.cli import main as cli_main


def test_cli_self_verify_canonical_install_returns_zero() -> None:
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = cli_main(["self-verify"])
    assert rc == 0
    report = json.loads(buf.getvalue())
    assert report["is_valid"] is True
    assert report["n_mismatches"] == 0


def test_cli_self_verify_strict_returns_zero_on_canonical() -> None:
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = cli_main(["self-verify", "--strict"])
    assert rc == 0


def test_cli_self_verify_emits_full_shape() -> None:
    buf = io.StringIO()
    with redirect_stdout(buf):
        cli_main(["self-verify"])
    report = json.loads(buf.getvalue())
    for field in (
        "contract_version", "frozen_at", "is_valid",
        "n_hashes_verified", "n_mismatches", "adrs_covered",
        "mismatches", "package_version", "verified_at",
    ):
        assert field in report, f"missing field: {field}"


def test_cli_self_verify_contract_version_is_semver() -> None:
    buf = io.StringIO()
    with redirect_stdout(buf):
        cli_main(["self-verify"])
    report = json.loads(buf.getvalue())
    parts = report["contract_version"].split(".")
    assert len(parts) == 3
    for p in parts:
        assert p.isdigit()


def test_cli_self_verify_covers_all_content_addressable_adrs() -> None:
    buf = io.StringIO()
    with redirect_stdout(buf):
        cli_main(["self-verify"])
    report = json.loads(buf.getvalue())
    required = {
        "ADR-0029", "ADR-0031", "ADR-0032", "ADR-0033", "ADR-0035",
        "ADR-0036", "ADR-0037", "ADR-0038", "ADR-0039", "ADR-0040",
        "ADR-0041",
    }
    missing = required - set(report["adrs_covered"])
    assert not missing, f"missing ADRs: {sorted(missing)}"


def test_cli_self_verify_runs_in_under_three_seconds() -> None:
    """Phase 8 criterion: end users must get fast feedback."""
    buf = io.StringIO()
    t0 = time.monotonic()
    with redirect_stdout(buf):
        cli_main(["self-verify"])
    elapsed = time.monotonic() - t0
    assert elapsed < 3.0, f"self-verify took {elapsed:.2f}s, should be < 3s"


def test_cli_self_verify_takes_no_positional_args() -> None:
    """Confirma que self-verify es accessible sin contexto previo del usuario."""
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = cli_main(["self-verify"])
    assert rc == 0


def test_cli_self_verify_emits_zero_mismatches_on_canonical() -> None:
    buf = io.StringIO()
    with redirect_stdout(buf):
        cli_main(["self-verify"])
    report = json.loads(buf.getvalue())
    assert report["mismatches"] == []


def test_cli_self_verify_n_hashes_verified_is_at_least_eleven() -> None:
    """Garantía estructural: cubrimos al menos 1 hash por ADR content-addressable."""
    buf = io.StringIO()
    with redirect_stdout(buf):
        cli_main(["self-verify"])
    report = json.loads(buf.getvalue())
    assert report["n_hashes_verified"] >= 11
