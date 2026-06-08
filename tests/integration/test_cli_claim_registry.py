"""CLI integration tests para ``claim-registry`` y ``verify-claim-registry`` (ADR-0035)."""

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
        cli_main([
            "agent-input", "-", "--consumer-class", "explanation_agent_v01",
        ])
    ai_path = tmp_path / "agent_input.json"
    ai_path.write_text(ai_buf.getvalue(), encoding="utf-8")
    art_buf = io.StringIO()
    with _redirect_stdin(io.StringIO(ai_buf.getvalue())), redirect_stdout(art_buf):
        cli_main(["explain", "-"])
    art_path = tmp_path / "artifact.json"
    art_path.write_text(art_buf.getvalue(), encoding="utf-8")
    return {"bundle": bundle_path, "agent_input": ai_path, "artifact": art_path}


# --- claim-registry build ----------------------------------------


def test_cli_claim_registry_emits_valid_registry(
    pipeline_artifacts: dict[str, Path],
) -> None:
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = cli_main([
            "claim-registry", str(pipeline_artifacts["artifact"]),
            "--agent-input-file", str(pipeline_artifacts["agent_input"]),
        ])
    assert rc == 0
    reg = json.loads(buf.getvalue())
    assert reg["registry_id"] == reg["registry_hash"]
    assert reg["n_claims"] == len(reg["claims"])
    assert reg["registry_emit_reason"] in {"evidence_bundle", "empty_bundle"}


def test_cli_claim_registry_from_stdin(pipeline_artifacts: dict[str, Path]) -> None:
    art_raw = pipeline_artifacts["artifact"].read_text(encoding="utf-8")
    buf = io.StringIO()
    with _redirect_stdin(io.StringIO(art_raw)), redirect_stdout(buf):
        rc = cli_main([
            "claim-registry", "-",
            "--agent-input-file", str(pipeline_artifacts["agent_input"]),
        ])
    assert rc == 0
    reg = json.loads(buf.getvalue())
    assert reg["registry_id"] == reg["registry_hash"]


def test_cli_claim_registry_emits_full_shape(
    pipeline_artifacts: dict[str, Path],
) -> None:
    buf = io.StringIO()
    with redirect_stdout(buf):
        cli_main([
            "claim-registry", str(pipeline_artifacts["artifact"]),
            "--agent-input-file", str(pipeline_artifacts["agent_input"]),
        ])
    reg = json.loads(buf.getvalue())
    for field in (
        "registry_id", "registry_hash",
        "source_explanation_id", "source_bundle_id", "source_agent_input_id",
        "source_model_identifier", "source_explanation_engine_version",
        "n_claims", "claims",
        "claim_to_evidence_index", "evidence_to_claim_index",
        "registry_emit_reason",
        "schema_version", "claim_layer_engine_version",
        "derived_at",
    ):
        assert field in reg


# --- verify-claim-registry valid path ---------------------------


def test_cli_verify_claim_registry_valid(pipeline_artifacts: dict[str, Path]) -> None:
    reg_buf = io.StringIO()
    with redirect_stdout(reg_buf):
        cli_main([
            "claim-registry", str(pipeline_artifacts["artifact"]),
            "--agent-input-file", str(pipeline_artifacts["agent_input"]),
        ])
    reg_path = pipeline_artifacts["artifact"].parent / "registry.json"
    reg_path.write_text(reg_buf.getvalue(), encoding="utf-8")
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = cli_main([
            "verify-claim-registry", str(reg_path),
            "--agent-input-file", str(pipeline_artifacts["agent_input"]),
            "--explanation-artifact-file", str(pipeline_artifacts["artifact"]),
        ])
    assert rc == 0
    rpt = json.loads(buf.getvalue())
    assert rpt["is_valid"] is True
    assert rpt["findings"] == []


def test_cli_verify_claim_registry_from_stdin(
    pipeline_artifacts: dict[str, Path],
) -> None:
    reg_buf = io.StringIO()
    with redirect_stdout(reg_buf):
        cli_main([
            "claim-registry", str(pipeline_artifacts["artifact"]),
            "--agent-input-file", str(pipeline_artifacts["agent_input"]),
        ])
    reg_raw = reg_buf.getvalue()
    buf = io.StringIO()
    with _redirect_stdin(io.StringIO(reg_raw)), redirect_stdout(buf):
        rc = cli_main([
            "verify-claim-registry", "-",
            "--agent-input-file", str(pipeline_artifacts["agent_input"]),
            "--explanation-artifact-file", str(pipeline_artifacts["artifact"]),
        ])
    assert rc == 0
    rpt = json.loads(buf.getvalue())
    assert rpt["is_valid"] is True


def test_cli_verify_claim_registry_emits_full_shape(
    pipeline_artifacts: dict[str, Path], tmp_path: Path,
) -> None:
    reg_buf = io.StringIO()
    with redirect_stdout(reg_buf):
        cli_main([
            "claim-registry", str(pipeline_artifacts["artifact"]),
            "--agent-input-file", str(pipeline_artifacts["agent_input"]),
        ])
    reg_path = tmp_path / "registry.json"
    reg_path.write_text(reg_buf.getvalue(), encoding="utf-8")
    buf = io.StringIO()
    with redirect_stdout(buf):
        cli_main([
            "verify-claim-registry", str(reg_path),
            "--agent-input-file", str(pipeline_artifacts["agent_input"]),
            "--explanation-artifact-file", str(pipeline_artifacts["artifact"]),
        ])
    rpt = json.loads(buf.getvalue())
    for field in (
        "registry_id", "is_valid",
        "n_claims_verified", "n_claims_with_findings", "n_findings",
        "forward_index_consistent", "reverse_index_consistent",
        "all_supporting_evidence_in_bundle",
        "all_referenced_evidence_covered",
        "all_claim_ids_recompute_correctly",
        "registry_id_is_alias_of_registry_hash",
        "all_source_ids_match",
        "all_claim_texts_match_explanation",
        "source_model_supported",
        "findings", "verification_hash",
        "verifier_engine_version", "schema_version", "verified_at",
    ):
        assert field in rpt


# --- Tampering detection ---------------------------------------


@pytest.fixture
def second_pipeline_artifacts(tmp_path: Path) -> dict[str, Path]:
    """Pipeline alternativo (NORAD distinto) para tests de swap-tampering."""
    sub = tmp_path / "alt"
    sub.mkdir()
    normalized_root = sub / "normalized"
    raw_root = sub / "raw"
    raw_root.mkdir(parents=True, exist_ok=True)
    elements = []
    for i in range(25):
        bump = 1e-2 if i >= 21 else 0.0
        elements.append(
            make_element(
                norad=99999, days_offset=float(i),
                mean_motion=14.2 + bump,
                tle_hash=f"{(i + 100):064x}",
                content_hash_source="e" * 64,
                tle_index=i + 100,
            )
        )
    OrbitalElementsRepository(normalized_root).insert_many(elements)
    bundle_buf = io.StringIO()
    with redirect_stdout(bundle_buf):
        cli_main([
            "bundle", "99999",
            "--baseline-days", "30", "--threshold-sigma", "3.0",
            "--raw-root", str(raw_root),
            "--normalized-root", str(normalized_root),
            "--detections-root", str(sub / "derived" / "conjunctions"),
        ])
    ai_buf = io.StringIO()
    with _redirect_stdin(io.StringIO(bundle_buf.getvalue())), redirect_stdout(ai_buf):
        cli_main([
            "agent-input", "-", "--consumer-class", "explanation_agent_v01",
        ])
    ai_path = sub / "agent_input.json"
    ai_path.write_text(ai_buf.getvalue(), encoding="utf-8")
    art_buf = io.StringIO()
    with _redirect_stdin(io.StringIO(ai_buf.getvalue())), redirect_stdout(art_buf):
        cli_main(["explain", "-"])
    art_path = sub / "artifact.json"
    art_path.write_text(art_buf.getvalue(), encoding="utf-8")
    return {"agent_input": ai_path, "artifact": art_path}


def test_cli_verify_claim_registry_strict_exits_1_on_swapped_artifact(
    pipeline_artifacts: dict[str, Path],
    second_pipeline_artifacts: dict[str, Path],
    tmp_path: Path,
) -> None:
    """Registry de A verificado con artifact de B — fallo de source IDs."""
    reg_buf = io.StringIO()
    with redirect_stdout(reg_buf):
        cli_main([
            "claim-registry", str(pipeline_artifacts["artifact"]),
            "--agent-input-file", str(pipeline_artifacts["agent_input"]),
        ])
    reg_path = tmp_path / "registry.json"
    reg_path.write_text(reg_buf.getvalue(), encoding="utf-8")
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = cli_main([
            "verify-claim-registry", str(reg_path),
            "--agent-input-file", str(second_pipeline_artifacts["agent_input"]),
            "--explanation-artifact-file", str(second_pipeline_artifacts["artifact"]),
            "--strict",
        ])
    assert rc == 1
    rpt = json.loads(buf.getvalue())
    assert rpt["is_valid"] is False
    assert len(rpt["findings"]) > 0


def test_cli_verify_claim_registry_without_strict_exits_0_on_swapped_artifact(
    pipeline_artifacts: dict[str, Path],
    second_pipeline_artifacts: dict[str, Path],
    tmp_path: Path,
) -> None:
    reg_buf = io.StringIO()
    with redirect_stdout(reg_buf):
        cli_main([
            "claim-registry", str(pipeline_artifacts["artifact"]),
            "--agent-input-file", str(pipeline_artifacts["agent_input"]),
        ])
    reg_path = tmp_path / "registry.json"
    reg_path.write_text(reg_buf.getvalue(), encoding="utf-8")
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = cli_main([
            "verify-claim-registry", str(reg_path),
            "--agent-input-file", str(second_pipeline_artifacts["agent_input"]),
            "--explanation-artifact-file", str(second_pipeline_artifacts["artifact"]),
        ])
    assert rc == 0
    rpt = json.loads(buf.getvalue())
    assert rpt["is_valid"] is False


# --- Full chain ------------------------------------------------


def test_cli_full_pipeline_ends_with_valid_claim_verification(
    pipeline_artifacts: dict[str, Path], tmp_path: Path,
) -> None:
    """bundle → agent-input → explain → claim-registry → verify-claim-registry."""
    reg_buf = io.StringIO()
    with redirect_stdout(reg_buf):
        cli_main([
            "claim-registry", str(pipeline_artifacts["artifact"]),
            "--agent-input-file", str(pipeline_artifacts["agent_input"]),
        ])
    reg_path = tmp_path / "registry.json"
    reg_path.write_text(reg_buf.getvalue(), encoding="utf-8")
    buf = io.StringIO()
    with redirect_stdout(buf):
        cli_main([
            "verify-claim-registry", str(reg_path),
            "--agent-input-file", str(pipeline_artifacts["agent_input"]),
            "--explanation-artifact-file", str(pipeline_artifacts["artifact"]),
        ])
    rpt = json.loads(buf.getvalue())
    assert rpt["is_valid"] is True
    assert rpt["verification_hash"]
