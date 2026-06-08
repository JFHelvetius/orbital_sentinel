"""CLI integration tests para ``orbital-sentinel explain`` (ADR-0033)."""

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
def catalog_with_shifted_series(tmp_path: Path) -> Path:
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
    return tmp_path


def _bundle_json(catalog: Path, norad: int = 12345) -> str:
    buf = io.StringIO()
    with redirect_stdout(buf):
        cli_main([
            "bundle", str(norad),
            "--baseline-days", "30", "--threshold-sigma", "3.0",
            "--raw-root", str(catalog / "raw"),
            "--normalized-root", str(catalog / "normalized"),
            "--detections-root", str(catalog / "derived" / "conjunctions"),
        ])
    return buf.getvalue()


def _agent_input_json(catalog: Path, norad: int = 12345) -> str:
    bundle_json = _bundle_json(catalog, norad)
    buf = io.StringIO()
    with _redirect_stdin(io.StringIO(bundle_json)), redirect_stdout(buf):
        cli_main([
            "agent-input", "-", "--consumer-class", "explanation_agent_v01",
        ])
    return buf.getvalue()


# --- Comportamiento base -----------------------------------------


def test_cli_explain_emits_valid_artifact_shape(
    catalog_with_shifted_series: Path,
) -> None:
    ai = _agent_input_json(catalog_with_shifted_series)
    buf = io.StringIO()
    with _redirect_stdin(io.StringIO(ai)), redirect_stdout(buf):
        rc = cli_main(["explain", "-"])
    assert rc == 0
    art = json.loads(buf.getvalue())
    for field in (
        "explanation_id", "source_agent_input_id", "source_bundle_id",
        "referenced_evidence_ids", "explanation_text", "generation_metadata",
        "audit_record", "schema_version", "explanation_engine_version",
        "generated_at",
    ):
        assert field in art
    assert art["schema_version"] == "0.1.0"
    assert art["explanation_engine_version"] == "0.1.0"


def test_cli_explain_audit_record_references_source(
    catalog_with_shifted_series: Path,
) -> None:
    ai_json_str = _agent_input_json(catalog_with_shifted_series)
    ai_data = json.loads(ai_json_str)
    buf = io.StringIO()
    with _redirect_stdin(io.StringIO(ai_json_str)), redirect_stdout(buf):
        cli_main(["explain", "-"])
    art = json.loads(buf.getvalue())
    audit = art["audit_record"]
    assert audit["agent_input_id"] == ai_data["agent_input_id"]
    assert audit["bundle_id"] == ai_data["bundle"]["bundle_id"]
    assert audit["explanation_id"] == art["explanation_id"]


def test_cli_explain_from_file(
    catalog_with_shifted_series: Path, tmp_path: Path,
) -> None:
    ai_path = tmp_path / "agent_input.json"
    ai_path.write_text(_agent_input_json(catalog_with_shifted_series), encoding="utf-8")
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = cli_main(["explain", str(ai_path)])
    assert rc == 0
    art = json.loads(buf.getvalue())
    assert "explanation_id" in art


# --- Determinismo y trazabilidad ---------------------------------


def test_cli_explain_id_reproducible_across_runs(
    catalog_with_shifted_series: Path, tmp_path: Path,
) -> None:
    ai_path = tmp_path / "agent_input.json"
    ai_path.write_text(_agent_input_json(catalog_with_shifted_series), encoding="utf-8")
    out1 = io.StringIO()
    out2 = io.StringIO()
    with redirect_stdout(out1):
        cli_main(["explain", str(ai_path)])
    with redirect_stdout(out2):
        cli_main(["explain", str(ai_path)])
    a = json.loads(out1.getvalue())
    b = json.loads(out2.getvalue())
    assert a["explanation_id"] == b["explanation_id"]
    assert a["referenced_evidence_ids"] == b["referenced_evidence_ids"]
    assert a["explanation_text"] == b["explanation_text"]


# --- Pipeline end-to-end -----------------------------------------


def test_cli_full_pipeline_bundle_agent_input_explain(
    catalog_with_shifted_series: Path,
) -> None:
    """bundle → agent-input → explain cierra el ciclo determinista hasta el agente."""
    bundle_json_str = _bundle_json(catalog_with_shifted_series)
    ai_buf = io.StringIO()
    with _redirect_stdin(io.StringIO(bundle_json_str)), redirect_stdout(ai_buf):
        cli_main(["agent-input", "-",
                  "--consumer-class", "explanation_agent_v01"])
    art_buf = io.StringIO()
    with _redirect_stdin(io.StringIO(ai_buf.getvalue())), redirect_stdout(art_buf):
        rc = cli_main(["explain", "-"])
    assert rc == 0
    art = json.loads(art_buf.getvalue())
    bundle_data = json.loads(bundle_json_str)
    assert art["source_bundle_id"] == bundle_data["bundle_id"]


# --- Lenguaje prohibido ------------------------------------------


def test_cli_explain_no_interpretive_language(
    catalog_with_shifted_series: Path,
) -> None:
    forbidden = (
        "probably", "likely", "suggests", "implies", "could be",
        "might mean", "suspicious", "dangerous", "malicious", "threat_level",
        "risk_level", "recommendation", "should investigate", "confidence_percentage",
    )
    ai = _agent_input_json(catalog_with_shifted_series)
    buf = io.StringIO()
    with _redirect_stdin(io.StringIO(ai)), redirect_stdout(buf):
        cli_main(["explain", "-"])
    raw = buf.getvalue().lower()
    for word in forbidden:
        assert word not in raw, f"palabra prohibida en explain output: {word!r}"


def test_cli_explain_text_contains_evidence_says_pattern(
    catalog_with_shifted_series: Path,
) -> None:
    """Las líneas factuales SIEMPRE arrancan con 'Evidence'."""
    ai = _agent_input_json(catalog_with_shifted_series)
    buf = io.StringIO()
    with _redirect_stdin(io.StringIO(ai)), redirect_stdout(buf):
        cli_main(["explain", "-"])
    art = json.loads(buf.getvalue())
    if art["referenced_evidence_ids"]:
        for line in art["explanation_text"].split("\n"):
            if line.strip():
                assert line.startswith("Evidence")
