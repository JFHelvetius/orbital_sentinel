"""CLI integration tests para ADR-0036/0037/0038 (Phase 6)."""

from __future__ import annotations

import io
import json
import sys
from contextlib import contextmanager, redirect_stdout
from datetime import datetime, timezone
from pathlib import Path

import pytest

from orbital_sentinel.catalog.orbital_elements import OrbitalElementsRepository
from orbital_sentinel.orchestration.cli import main as cli_main
from tests.unit.test_maneuver_series import make_element


@contextmanager
def _redirect_stdin(new_stdin):  # type: ignore[no-untyped-def]
    old = sys.stdin
    sys.stdin = new_stdin
    try:
        yield
    finally:
        sys.stdin = old


EPOCH = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def phase5_artifacts(tmp_path: Path) -> dict[str, Path]:
    """Genera bundle → agent_input → artifact → claim_registry vía CLI."""
    normalized_root = tmp_path / "normalized"
    raw_root = tmp_path / "raw"
    raw_root.mkdir(parents=True, exist_ok=True)
    elements = []
    for i in range(25):
        bump = 1e-2 if i >= 21 else 0.0
        elements.append(make_element(
            days_offset=float(i), mean_motion=15.5 + bump,
            tle_hash=f"{i:064x}", content_hash_source="d" * 64, tle_index=i,
        ))
    OrbitalElementsRepository(normalized_root).insert_many(elements)
    bundle_buf = io.StringIO()
    with redirect_stdout(bundle_buf):
        cli_main([
            "bundle", "12345",
            "--baseline-days", "30", "--threshold-sigma", "3.0",
            "--raw-root", str(raw_root),
            "--normalized-root", str(normalized_root),
            "--detections-root", str(tmp_path / "derived" / "conjunctions"),
        ])
    bundle_path = tmp_path / "bundle.json"
    bundle_path.write_text(bundle_buf.getvalue(), encoding="utf-8")
    ai_buf = io.StringIO()
    with _redirect_stdin(io.StringIO(bundle_buf.getvalue())), redirect_stdout(ai_buf):
        cli_main(["agent-input", "-", "--consumer-class", "explanation_agent_v01"])
    ai_path = tmp_path / "agent_input.json"
    ai_path.write_text(ai_buf.getvalue(), encoding="utf-8")
    art_buf = io.StringIO()
    with _redirect_stdin(io.StringIO(ai_buf.getvalue())), redirect_stdout(art_buf):
        cli_main(["explain", "-"])
    art_path = tmp_path / "artifact.json"
    art_path.write_text(art_buf.getvalue(), encoding="utf-8")
    cr_buf = io.StringIO()
    with redirect_stdout(cr_buf):
        cli_main([
            "claim-registry", str(art_path), "--agent-input-file", str(ai_path),
        ])
    cr_path = tmp_path / "claim_registry.json"
    cr_path.write_text(cr_buf.getvalue(), encoding="utf-8")
    return {
        "bundle": bundle_path,
        "agent_input": ai_path,
        "artifact": art_path,
        "claim_registry": cr_path,
    }


# --- hypothesis-registry --------------------------------------


def test_cli_hypothesis_registry_emits_valid(
    phase5_artifacts: dict[str, Path], tmp_path: Path,
) -> None:
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = cli_main([
            "hypothesis-registry", str(phase5_artifacts["claim_registry"]),
            "--agent-input-file", str(phase5_artifacts["agent_input"]),
        ])
    assert rc == 0
    reg = json.loads(buf.getvalue())
    assert reg["registry_id"] == reg["registry_hash"]
    assert reg["registry_emit_reason"] in {"claim_registry_populated", "empty_claim_registry"}


def test_cli_hypothesis_registry_from_stdin(
    phase5_artifacts: dict[str, Path],
) -> None:
    cr_raw = phase5_artifacts["claim_registry"].read_text(encoding="utf-8")
    buf = io.StringIO()
    with _redirect_stdin(io.StringIO(cr_raw)), redirect_stdout(buf):
        rc = cli_main([
            "hypothesis-registry", "-",
            "--agent-input-file", str(phase5_artifacts["agent_input"]),
        ])
    assert rc == 0
    reg = json.loads(buf.getvalue())
    assert reg["registry_id"] == reg["registry_hash"]


# --- verify-hypothesis-registry --------------------------------


def test_cli_verify_hypothesis_registry_valid(
    phase5_artifacts: dict[str, Path], tmp_path: Path,
) -> None:
    hyp_buf = io.StringIO()
    with redirect_stdout(hyp_buf):
        cli_main([
            "hypothesis-registry", str(phase5_artifacts["claim_registry"]),
            "--agent-input-file", str(phase5_artifacts["agent_input"]),
        ])
    hyp_path = tmp_path / "hyp.json"
    hyp_path.write_text(hyp_buf.getvalue(), encoding="utf-8")
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = cli_main([
            "verify-hypothesis-registry", str(hyp_path),
            "--claim-registry-file", str(phase5_artifacts["claim_registry"]),
            "--agent-input-file", str(phase5_artifacts["agent_input"]),
        ])
    assert rc == 0
    rpt = json.loads(buf.getvalue())
    assert rpt["is_valid"] is True


# --- evidence-chain --------------------------------------------


def test_cli_evidence_chain_emits_valid(
    phase5_artifacts: dict[str, Path], tmp_path: Path,
) -> None:
    hyp_buf = io.StringIO()
    with redirect_stdout(hyp_buf):
        cli_main([
            "hypothesis-registry", str(phase5_artifacts["claim_registry"]),
            "--agent-input-file", str(phase5_artifacts["agent_input"]),
        ])
    hyp_path = tmp_path / "hyp.json"
    hyp_path.write_text(hyp_buf.getvalue(), encoding="utf-8")
    chain_buf = io.StringIO()
    with redirect_stdout(chain_buf):
        rc = cli_main([
            "evidence-chain", str(hyp_path),
            "--claim-registry-file", str(phase5_artifacts["claim_registry"]),
            "--explanation-artifact-file", str(phase5_artifacts["artifact"]),
            "--agent-input-file", str(phase5_artifacts["agent_input"]),
        ])
    assert rc == 0
    chain = json.loads(chain_buf.getvalue())
    assert chain["chain_id"] == chain["chain_hash"]


# --- verify-evidence-chain --------------------------------------


def test_cli_verify_evidence_chain_valid(
    phase5_artifacts: dict[str, Path], tmp_path: Path,
) -> None:
    hyp_buf = io.StringIO()
    with redirect_stdout(hyp_buf):
        cli_main([
            "hypothesis-registry", str(phase5_artifacts["claim_registry"]),
            "--agent-input-file", str(phase5_artifacts["agent_input"]),
        ])
    hyp_path = tmp_path / "hyp.json"
    hyp_path.write_text(hyp_buf.getvalue(), encoding="utf-8")
    chain_buf = io.StringIO()
    with redirect_stdout(chain_buf):
        cli_main([
            "evidence-chain", str(hyp_path),
            "--claim-registry-file", str(phase5_artifacts["claim_registry"]),
            "--explanation-artifact-file", str(phase5_artifacts["artifact"]),
            "--agent-input-file", str(phase5_artifacts["agent_input"]),
        ])
    chain_path = tmp_path / "chain.json"
    chain_path.write_text(chain_buf.getvalue(), encoding="utf-8")
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = cli_main([
            "verify-evidence-chain", str(chain_path),
            "--hypothesis-registry-file", str(hyp_path),
            "--claim-registry-file", str(phase5_artifacts["claim_registry"]),
            "--explanation-artifact-file", str(phase5_artifacts["artifact"]),
            "--agent-input-file", str(phase5_artifacts["agent_input"]),
        ])
    assert rc == 0
    rpt = json.loads(buf.getvalue())
    assert rpt["is_valid"] is True


# --- investigation-case -----------------------------------------


def test_cli_investigation_case_emits_valid(
    phase5_artifacts: dict[str, Path], tmp_path: Path,
) -> None:
    hyp_buf = io.StringIO()
    with redirect_stdout(hyp_buf):
        cli_main([
            "hypothesis-registry", str(phase5_artifacts["claim_registry"]),
            "--agent-input-file", str(phase5_artifacts["agent_input"]),
        ])
    hyp_path = tmp_path / "hyp.json"
    hyp_path.write_text(hyp_buf.getvalue(), encoding="utf-8")
    chain_buf = io.StringIO()
    with redirect_stdout(chain_buf):
        cli_main([
            "evidence-chain", str(hyp_path),
            "--claim-registry-file", str(phase5_artifacts["claim_registry"]),
            "--explanation-artifact-file", str(phase5_artifacts["artifact"]),
            "--agent-input-file", str(phase5_artifacts["agent_input"]),
        ])
    chain_path = tmp_path / "chain.json"
    chain_path.write_text(chain_buf.getvalue(), encoding="utf-8")
    case_buf = io.StringIO()
    with redirect_stdout(case_buf):
        rc = cli_main([
            "investigation-case", str(chain_path),
            "--hypothesis-registry-file", str(hyp_path),
            "--claim-registry-file", str(phase5_artifacts["claim_registry"]),
            "--explanation-artifact-file", str(phase5_artifacts["artifact"]),
            "--agent-input-file", str(phase5_artifacts["agent_input"]),
            "--bundle-file", str(phase5_artifacts["bundle"]),
        ])
    assert rc == 0
    case = json.loads(case_buf.getvalue())
    assert case["case_id"] == case["case_signature"]


# --- verify-investigation-case ----------------------------------


def test_cli_verify_investigation_case_valid(
    phase5_artifacts: dict[str, Path], tmp_path: Path,
) -> None:
    hyp_buf = io.StringIO()
    with redirect_stdout(hyp_buf):
        cli_main([
            "hypothesis-registry", str(phase5_artifacts["claim_registry"]),
            "--agent-input-file", str(phase5_artifacts["agent_input"]),
        ])
    hyp_path = tmp_path / "hyp.json"
    hyp_path.write_text(hyp_buf.getvalue(), encoding="utf-8")
    chain_buf = io.StringIO()
    with redirect_stdout(chain_buf):
        cli_main([
            "evidence-chain", str(hyp_path),
            "--claim-registry-file", str(phase5_artifacts["claim_registry"]),
            "--explanation-artifact-file", str(phase5_artifacts["artifact"]),
            "--agent-input-file", str(phase5_artifacts["agent_input"]),
        ])
    chain_path = tmp_path / "chain.json"
    chain_path.write_text(chain_buf.getvalue(), encoding="utf-8")
    case_buf = io.StringIO()
    with redirect_stdout(case_buf):
        cli_main([
            "investigation-case", str(chain_path),
            "--hypothesis-registry-file", str(hyp_path),
            "--claim-registry-file", str(phase5_artifacts["claim_registry"]),
            "--explanation-artifact-file", str(phase5_artifacts["artifact"]),
            "--agent-input-file", str(phase5_artifacts["agent_input"]),
            "--bundle-file", str(phase5_artifacts["bundle"]),
        ])
    case_path = tmp_path / "case.json"
    case_path.write_text(case_buf.getvalue(), encoding="utf-8")
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = cli_main(["verify-investigation-case", str(case_path)])
    assert rc == 0
    rpt = json.loads(buf.getvalue())
    assert rpt["is_valid"] is True
    assert rpt["n_artifacts_verified"] == 6


def test_cli_verify_investigation_case_from_stdin(
    phase5_artifacts: dict[str, Path], tmp_path: Path,
) -> None:
    hyp_buf = io.StringIO()
    with redirect_stdout(hyp_buf):
        cli_main([
            "hypothesis-registry", str(phase5_artifacts["claim_registry"]),
            "--agent-input-file", str(phase5_artifacts["agent_input"]),
        ])
    hyp_path = tmp_path / "hyp.json"
    hyp_path.write_text(hyp_buf.getvalue(), encoding="utf-8")
    chain_buf = io.StringIO()
    with redirect_stdout(chain_buf):
        cli_main([
            "evidence-chain", str(hyp_path),
            "--claim-registry-file", str(phase5_artifacts["claim_registry"]),
            "--explanation-artifact-file", str(phase5_artifacts["artifact"]),
            "--agent-input-file", str(phase5_artifacts["agent_input"]),
        ])
    chain_path = tmp_path / "chain.json"
    chain_path.write_text(chain_buf.getvalue(), encoding="utf-8")
    case_buf = io.StringIO()
    with redirect_stdout(case_buf):
        cli_main([
            "investigation-case", str(chain_path),
            "--hypothesis-registry-file", str(hyp_path),
            "--claim-registry-file", str(phase5_artifacts["claim_registry"]),
            "--explanation-artifact-file", str(phase5_artifacts["artifact"]),
            "--agent-input-file", str(phase5_artifacts["agent_input"]),
            "--bundle-file", str(phase5_artifacts["bundle"]),
        ])
    case_raw = case_buf.getvalue()
    buf = io.StringIO()
    with _redirect_stdin(io.StringIO(case_raw)), redirect_stdout(buf):
        rc = cli_main(["verify-investigation-case", "-"])
    assert rc == 0


# --- End-to-end Phase 6 -----------------------------------------


def test_cli_full_phase6_pipeline(
    phase5_artifacts: dict[str, Path], tmp_path: Path,
) -> None:
    """bundle → agent-input → explain → claim-registry →
    hypothesis-registry → evidence-chain → investigation-case →
    verify-investigation-case.
    """
    hyp_buf = io.StringIO()
    with redirect_stdout(hyp_buf):
        cli_main([
            "hypothesis-registry", str(phase5_artifacts["claim_registry"]),
            "--agent-input-file", str(phase5_artifacts["agent_input"]),
        ])
    hyp_path = tmp_path / "hyp.json"
    hyp_path.write_text(hyp_buf.getvalue(), encoding="utf-8")

    chain_buf = io.StringIO()
    with redirect_stdout(chain_buf):
        cli_main([
            "evidence-chain", str(hyp_path),
            "--claim-registry-file", str(phase5_artifacts["claim_registry"]),
            "--explanation-artifact-file", str(phase5_artifacts["artifact"]),
            "--agent-input-file", str(phase5_artifacts["agent_input"]),
        ])
    chain_path = tmp_path / "chain.json"
    chain_path.write_text(chain_buf.getvalue(), encoding="utf-8")

    case_buf = io.StringIO()
    with redirect_stdout(case_buf):
        cli_main([
            "investigation-case", str(chain_path),
            "--hypothesis-registry-file", str(hyp_path),
            "--claim-registry-file", str(phase5_artifacts["claim_registry"]),
            "--explanation-artifact-file", str(phase5_artifacts["artifact"]),
            "--agent-input-file", str(phase5_artifacts["agent_input"]),
            "--bundle-file", str(phase5_artifacts["bundle"]),
        ])
    case_path = tmp_path / "case.json"
    case_path.write_text(case_buf.getvalue(), encoding="utf-8")

    buf = io.StringIO()
    with redirect_stdout(buf):
        cli_main(["verify-investigation-case", str(case_path), "--strict"])
    rpt = json.loads(buf.getvalue())
    assert rpt["is_valid"] is True
    assert rpt["n_findings"] == 0
