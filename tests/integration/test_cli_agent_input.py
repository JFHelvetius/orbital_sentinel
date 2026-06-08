"""CLI integration tests para ``orbital-sentinel agent-input`` (ADR-0032)."""

from __future__ import annotations

import io
import json
import sys
from contextlib import contextmanager, redirect_stderr, redirect_stdout
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


def _capture_bundle_json(catalog: Path, norad: int = 12345) -> str:
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


# --- Construcción exitosa via CLI ---------------------------------


def test_cli_agent_input_from_stdin_valid_bundle(
    catalog_with_shifted_series: Path,
) -> None:
    bundle_json = _capture_bundle_json(catalog_with_shifted_series)
    out_buf = io.StringIO()
    with _redirect_stdin(io.StringIO(bundle_json)), redirect_stdout(out_buf):
        rc = cli_main([
            "agent-input", "-", "--consumer-class", "explanation_agent_v01",
        ])
    assert rc == 0
    ai = json.loads(out_buf.getvalue())
    assert ai["declared_consumer_class"] == "explanation_agent_v01"
    assert ai["contract_schema_version"] == "0.1.0"
    assert ai["verification_report"]["is_valid"] is True


def test_cli_agent_input_from_file(
    catalog_with_shifted_series: Path, tmp_path: Path,
) -> None:
    bundle_json = _capture_bundle_json(catalog_with_shifted_series)
    bundle_path = tmp_path / "bundle.json"
    bundle_path.write_text(bundle_json, encoding="utf-8")
    out_buf = io.StringIO()
    with redirect_stdout(out_buf):
        rc = cli_main([
            "agent-input", str(bundle_path),
            "--consumer-class", "audit_consumer_v01",
        ])
    assert rc == 0
    ai = json.loads(out_buf.getvalue())
    assert ai["declared_consumer_class"] == "audit_consumer_v01"


def test_cli_agent_input_emits_full_shape(
    catalog_with_shifted_series: Path,
) -> None:
    bundle_json = _capture_bundle_json(catalog_with_shifted_series)
    out_buf = io.StringIO()
    with _redirect_stdin(io.StringIO(bundle_json)), redirect_stdout(out_buf):
        cli_main(["agent-input", "-", "--consumer-class", "report_exporter_v01"])
    ai = json.loads(out_buf.getvalue())
    for field in (
        "agent_input_id", "bundle", "verification_report",
        "declared_consumer_class", "contract_schema_version",
        "contract_engine_version", "contract_acceptance_at",
    ):
        assert field in ai


def test_cli_agent_input_id_reproducible(
    catalog_with_shifted_series: Path, tmp_path: Path,
) -> None:
    bundle_json = _capture_bundle_json(catalog_with_shifted_series)
    bundle_path = tmp_path / "bundle.json"
    bundle_path.write_text(bundle_json, encoding="utf-8")
    out1 = io.StringIO()
    out2 = io.StringIO()
    with redirect_stdout(out1):
        cli_main(["agent-input", str(bundle_path),
                  "--consumer-class", "api_endpoint_v01"])
    with redirect_stdout(out2):
        cli_main(["agent-input", str(bundle_path),
                  "--consumer-class", "api_endpoint_v01"])
    a = json.loads(out1.getvalue())
    b = json.loads(out2.getvalue())
    assert a["agent_input_id"] == b["agent_input_id"]


# --- Rechazo de bundles inválidos --------------------------------


def test_cli_agent_input_rejects_tampered_bundle_with_exit_1(
    catalog_with_shifted_series: Path, tmp_path: Path,
) -> None:
    bundle_json = _capture_bundle_json(catalog_with_shifted_series)
    data = json.loads(bundle_json)
    data["bundle_payload_signature"] = "0" * 64
    bundle_path = tmp_path / "tampered.json"
    bundle_path.write_text(json.dumps(data), encoding="utf-8")
    out_buf = io.StringIO()
    err_buf = io.StringIO()
    with redirect_stdout(out_buf), redirect_stderr(err_buf):
        rc = cli_main([
            "agent-input", str(bundle_path),
            "--consumer-class", "explanation_agent_v01",
        ])
    assert rc == 1
    report = json.loads(err_buf.getvalue())
    assert report["is_valid"] is False
    assert out_buf.getvalue() == ""  # stdout vacío en rechazo


def test_cli_agent_input_rejects_unknown_consumer_class(
    catalog_with_shifted_series: Path, tmp_path: Path,
) -> None:
    bundle_json = _capture_bundle_json(catalog_with_shifted_series)
    bundle_path = tmp_path / "bundle.json"
    bundle_path.write_text(bundle_json, encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        cli_main(["agent-input", str(bundle_path),
                  "--consumer-class", "not_a_real_consumer"])
    assert exc.value.code == 2


def test_cli_pipe_bundle_to_agent_input_full_cycle(
    catalog_with_shifted_series: Path,
) -> None:
    """bundle → agent-input cierra el ciclo determinista."""
    bundle_json = _capture_bundle_json(catalog_with_shifted_series)
    out_buf = io.StringIO()
    with _redirect_stdin(io.StringIO(bundle_json)), redirect_stdout(out_buf):
        rc = cli_main(["agent-input", "-",
                       "--consumer-class", "explanation_agent_v01"])
    assert rc == 0
    ai = json.loads(out_buf.getvalue())
    # bundle embebido literal preserva su content-addressable identity
    assert ai["bundle"]["bundle_id"] == json.loads(bundle_json)["bundle_id"]


def test_cli_agent_input_no_interpretive_language(
    catalog_with_shifted_series: Path,
) -> None:
    forbidden = ("likely", "probably", "suspicious", "dangerous",
                 "threat_level", "risk_level", "recommendation")
    bundle_json = _capture_bundle_json(catalog_with_shifted_series)
    out_buf = io.StringIO()
    with _redirect_stdin(io.StringIO(bundle_json)), redirect_stdout(out_buf):
        cli_main(["agent-input", "-",
                  "--consumer-class", "explanation_agent_v01"])
    raw = out_buf.getvalue().lower()
    for word in forbidden:
        assert word not in raw
