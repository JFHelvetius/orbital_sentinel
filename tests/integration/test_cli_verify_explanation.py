"""CLI integration tests para ``orbital-sentinel verify-explanation`` (ADR-0034)."""

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
def pipeline_artifacts(tmp_path: Path) -> dict[str, Path]:
    normalized_root = tmp_path / "normalized"
    raw_root = tmp_path / "raw"
    raw_root.mkdir(parents=True, exist_ok=True)
    elements = []
    for i in range(25):
        bump = 1e-2 if i >= 21 else 0.0
        elements.append(
            make_element(
                days_offset=float(i),
                mean_motion=15.5 + bump,
                tle_hash=f"{i:064x}",
                content_hash_source="d" * 64,
                tle_index=i,
            )
        )
    OrbitalElementsRepository(normalized_root).insert_many(elements)
    # bundle
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
    # agent-input
    ai_buf = io.StringIO()
    with _redirect_stdin(io.StringIO(bundle_buf.getvalue())), redirect_stdout(ai_buf):
        cli_main([
            "agent-input", "-", "--consumer-class", "explanation_agent_v01",
        ])
    ai_path = tmp_path / "agent_input.json"
    ai_path.write_text(ai_buf.getvalue(), encoding="utf-8")
    # explain
    art_buf = io.StringIO()
    with _redirect_stdin(io.StringIO(ai_buf.getvalue())), redirect_stdout(art_buf):
        cli_main(["explain", "-"])
    art_path = tmp_path / "artifact.json"
    art_path.write_text(art_buf.getvalue(), encoding="utf-8")
    return {"bundle": bundle_path, "agent_input": ai_path, "artifact": art_path}


# --- Valid path ---------------------------------------------------


def test_cli_verify_explanation_valid_pipeline(pipeline_artifacts: dict[str, Path]) -> None:
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = cli_main([
            "verify-explanation", str(pipeline_artifacts["artifact"]),
            "--agent-input-file", str(pipeline_artifacts["agent_input"]),
        ])
    assert rc == 0
    rpt = json.loads(buf.getvalue())
    assert rpt["is_valid"] is True
    assert rpt["findings"] == []


def test_cli_verify_explanation_emits_full_shape(
    pipeline_artifacts: dict[str, Path],
) -> None:
    buf = io.StringIO()
    with redirect_stdout(buf):
        cli_main([
            "verify-explanation", str(pipeline_artifacts["artifact"]),
            "--agent-input-file", str(pipeline_artifacts["agent_input"]),
        ])
    rpt = json.loads(buf.getvalue())
    for field in (
        "explanation_id", "bundle_id", "agent_input_id", "is_valid",
        "referenced_evidence_count", "n_orphan_references", "n_findings",
        "explanation_id_recomputes_correctly", "audit_explanation_id_matches",
        "audit_bundle_id_matches", "audit_agent_input_id_matches",
        "prompt_hash_consistent_metadata_audit",
        "referenced_audit_ids_consistent",
        "source_bundle_id_matches_agent_input",
        "source_agent_input_id_matches_agent_input",
        "findings", "verification_hash", "verifier_engine_version",
        "schema_version", "verified_at",
    ):
        assert field in rpt


def test_cli_verify_explanation_from_stdin(pipeline_artifacts: dict[str, Path]) -> None:
    artifact_raw = pipeline_artifacts["artifact"].read_text(encoding="utf-8")
    buf = io.StringIO()
    with _redirect_stdin(io.StringIO(artifact_raw)), redirect_stdout(buf):
        rc = cli_main([
            "verify-explanation", "-",
            "--agent-input-file", str(pipeline_artifacts["agent_input"]),
        ])
    assert rc == 0
    rpt = json.loads(buf.getvalue())
    assert rpt["is_valid"] is True


# --- Tampering detection ----------------------------------------


def test_cli_verify_explanation_strict_exits_1_on_tampered(
    pipeline_artifacts: dict[str, Path], tmp_path: Path,
) -> None:
    artifact_data = json.loads(pipeline_artifacts["artifact"].read_text(encoding="utf-8"))
    artifact_data["source_bundle_id"] = "0" * 64
    tampered_path = tmp_path / "tampered_artifact.json"
    tampered_path.write_text(json.dumps(artifact_data), encoding="utf-8")
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = cli_main([
            "verify-explanation", str(tampered_path),
            "--agent-input-file", str(pipeline_artifacts["agent_input"]),
            "--strict",
        ])
    assert rc == 1
    rpt = json.loads(buf.getvalue())
    assert rpt["is_valid"] is False
    assert len(rpt["findings"]) > 0


def test_cli_verify_explanation_without_strict_exits_0_on_tampered(
    pipeline_artifacts: dict[str, Path], tmp_path: Path,
) -> None:
    artifact_data = json.loads(pipeline_artifacts["artifact"].read_text(encoding="utf-8"))
    artifact_data["source_bundle_id"] = "0" * 64
    tampered_path = tmp_path / "tampered_artifact.json"
    tampered_path.write_text(json.dumps(artifact_data), encoding="utf-8")
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = cli_main([
            "verify-explanation", str(tampered_path),
            "--agent-input-file", str(pipeline_artifacts["agent_input"]),
        ])
    assert rc == 0  # sin --strict, exit 0 con reporte
    rpt = json.loads(buf.getvalue())
    assert rpt["is_valid"] is False


# --- Full end-to-end pipeline ----------------------------------


def test_cli_full_pipeline_ends_with_valid_verification(
    pipeline_artifacts: dict[str, Path],
) -> None:
    """bundle → agent-input → explain → verify-explanation cierra el ciclo total."""
    buf = io.StringIO()
    with redirect_stdout(buf):
        cli_main([
            "verify-explanation", str(pipeline_artifacts["artifact"]),
            "--agent-input-file", str(pipeline_artifacts["agent_input"]),
        ])
    rpt = json.loads(buf.getvalue())
    assert rpt["is_valid"] is True
    assert rpt["verification_hash"]
