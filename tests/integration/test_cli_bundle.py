"""CLI integration tests para ``orbital-sentinel bundle`` y
``orbital-sentinel verify-bundle`` (ADR-0031)."""

from __future__ import annotations

import io
import json
import sys
from contextlib import contextmanager, redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from orbital_sentinel.catalog.orbital_elements import OrbitalElementsRepository
from orbital_sentinel.orchestration.cli import main as cli_main
from tests.unit.test_maneuver_series import make_element


@contextmanager
def _redirect_stdin(new_stdin):  # type: ignore[no-untyped-def]
    """contextlib no provee redirect_stdin; lo implementamos localmente."""
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


@pytest.fixture
def empty_catalog(tmp_path: Path) -> Path:
    (tmp_path / "raw").mkdir(parents=True, exist_ok=True)
    (tmp_path / "normalized").mkdir(parents=True, exist_ok=True)
    return tmp_path


def _bundle_args(catalog: Path, norad: int = 12345) -> list[str]:
    return [
        "bundle", str(norad),
        "--baseline-days", "30",
        "--threshold-sigma", "3.0",
        "--raw-root", str(catalog / "raw"),
        "--normalized-root", str(catalog / "normalized"),
        "--detections-root", str(catalog / "derived" / "conjunctions"),
    ]


def _capture_bundle(catalog: Path, norad: int = 12345) -> dict:
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = cli_main(_bundle_args(catalog, norad))
    assert rc == 0
    return json.loads(buf.getvalue())


# --- CLI bundle: shape -----------------------------------------------


def test_cli_bundle_emits_valid_json_shape(catalog_with_shifted_series: Path) -> None:
    out = _capture_bundle(catalog_with_shifted_series)
    assert out["object_id"] == 12345
    assert out["schema_version"] == "0.1.0"
    assert out["bundle_engine_version"] == "0.1.0"
    assert "bundle_id" in out
    assert "bundle_signature" in out
    assert "bundle_payload_signature" in out
    assert "context" in out
    assert "evidence_payloads" in out
    assert out["n_evidence_payloads"] == len(out["evidence_payloads"])


def test_cli_bundle_bundle_id_equals_bundle_signature(
    catalog_with_shifted_series: Path,
) -> None:
    """Hard invariant ADR-0031 visible en el output JSON."""
    out = _capture_bundle(catalog_with_shifted_series)
    assert out["bundle_id"] == out["bundle_signature"]


def test_cli_bundle_empty_catalog_produces_empty_bundle(empty_catalog: Path) -> None:
    out = _capture_bundle(empty_catalog)
    assert out["n_evidence_payloads"] == 0
    assert out["evidence_payloads"] == []


def test_cli_bundle_carries_full_context_embedded(
    catalog_with_shifted_series: Path,
) -> None:
    out = _capture_bundle(catalog_with_shifted_series)
    ctx = out["context"]
    assert ctx["object_id"] == 12345
    assert "context_id" in ctx
    assert "evidence_references" in ctx


def test_cli_bundle_payload_count_matches_context_references(
    catalog_with_shifted_series: Path,
) -> None:
    out = _capture_bundle(catalog_with_shifted_series)
    assert out["n_evidence_payloads"] == len(out["context"]["evidence_references"])


# --- CLI bundle: determinismo ----------------------------------------


def test_cli_bundle_signature_reproducible_across_runs(
    catalog_with_shifted_series: Path,
) -> None:
    a = _capture_bundle(catalog_with_shifted_series)
    b = _capture_bundle(catalog_with_shifted_series)
    assert a["bundle_signature"] == b["bundle_signature"]
    assert a["bundle_id"] == b["bundle_id"]
    assert a["bundle_payload_signature"] == b["bundle_payload_signature"]


# --- CLI bundle: filtros opcionales ---------------------------------


def test_cli_bundle_filter_by_detector_maneuver(
    catalog_with_shifted_series: Path,
) -> None:
    buf = io.StringIO()
    with redirect_stdout(buf):
        cli_main([*_bundle_args(catalog_with_shifted_series), "--detector", "maneuver"])
    out = json.loads(buf.getvalue())
    for bp in out["evidence_payloads"]:
        assert bp["derived_evidence"]["source_detector"] == "maneuver_detection_v01"


def test_cli_bundle_filter_far_future_returns_empty(
    catalog_with_shifted_series: Path,
) -> None:
    far_future = (EPOCH + timedelta(days=1000)).isoformat().replace("+00:00", "Z")
    buf = io.StringIO()
    with redirect_stdout(buf):
        cli_main([*_bundle_args(catalog_with_shifted_series), "--from", far_future])
    out = json.loads(buf.getvalue())
    assert out["n_evidence_payloads"] == 0


# --- CLI verify-bundle: ciclo bundle â†’ verify cierra como vÃ¡lido ----


def test_cli_pipe_bundle_to_verify_bundle_yields_valid(
    catalog_with_shifted_series: Path, tmp_path: Path,
) -> None:
    """bundle | verify-bundle - debe reportar is_valid=True."""
    bundle_buf = io.StringIO()
    with redirect_stdout(bundle_buf):
        cli_main(_bundle_args(catalog_with_shifted_series))
    bundle_json = bundle_buf.getvalue()
    verify_buf = io.StringIO()
    with _redirect_stdin(io.StringIO(bundle_json)), redirect_stdout(verify_buf):
        rc = cli_main(["verify-bundle", "-"])
    assert rc == 0
    report = json.loads(verify_buf.getvalue())
    assert report["is_valid"] is True
    assert report["integrity_failures"] == []


def test_cli_verify_bundle_from_file(
    catalog_with_shifted_series: Path, tmp_path: Path,
) -> None:
    bundle_path = tmp_path / "bundle.json"
    bundle_buf = io.StringIO()
    with redirect_stdout(bundle_buf):
        cli_main(_bundle_args(catalog_with_shifted_series))
    bundle_path.write_text(bundle_buf.getvalue(), encoding="utf-8")
    verify_buf = io.StringIO()
    with redirect_stdout(verify_buf):
        rc = cli_main(["verify-bundle", str(bundle_path)])
    assert rc == 0
    report = json.loads(verify_buf.getvalue())
    assert report["is_valid"] is True


def test_cli_verify_bundle_emits_report_shape(
    catalog_with_shifted_series: Path,
) -> None:
    bundle_buf = io.StringIO()
    with redirect_stdout(bundle_buf):
        cli_main(_bundle_args(catalog_with_shifted_series))
    verify_buf = io.StringIO()
    with _redirect_stdin(io.StringIO(bundle_buf.getvalue())), redirect_stdout(verify_buf):
        cli_main(["verify-bundle", "-"])
    report = json.loads(verify_buf.getvalue())
    for field in (
        "bundle_id", "is_valid", "n_payloads_total",
        "n_payloads_with_valid_hash", "n_payloads_with_invalid_hash",
        "context_id_recomputes_correctly",
        "source_catalog_signature_recomputes_correctly",
        "bundle_payload_signature_recomputes_correctly",
        "bundle_signature_recomputes_correctly",
        "bundle_id_is_alias_of_bundle_signature",
        "integrity_failures", "verifier_engine_version", "verified_at",
    ):
        assert field in report


# --- CLI verify-bundle: strict mode -------------------------------


def test_cli_verify_bundle_strict_exits_1_on_tampered_bundle(
    catalog_with_shifted_series: Path, tmp_path: Path,
) -> None:
    bundle_buf = io.StringIO()
    with redirect_stdout(bundle_buf):
        cli_main(_bundle_args(catalog_with_shifted_series))
    data = json.loads(bundle_buf.getvalue())
    # Tamper: corrompemos bundle_payload_signature â†’ mismatch
    data["bundle_payload_signature"] = "0" * 64
    bundle_path = tmp_path / "tampered.json"
    bundle_path.write_text(json.dumps(data), encoding="utf-8")
    verify_buf = io.StringIO()
    with redirect_stdout(verify_buf):
        rc = cli_main(["verify-bundle", str(bundle_path), "--strict"])
    assert rc == 1
    report = json.loads(verify_buf.getvalue())
    assert report["is_valid"] is False


def test_cli_verify_bundle_without_strict_exits_0_even_on_tampered(
    catalog_with_shifted_series: Path, tmp_path: Path,
) -> None:
    bundle_buf = io.StringIO()
    with redirect_stdout(bundle_buf):
        cli_main(_bundle_args(catalog_with_shifted_series))
    data = json.loads(bundle_buf.getvalue())
    data["bundle_payload_signature"] = "0" * 64
    bundle_path = tmp_path / "tampered.json"
    bundle_path.write_text(json.dumps(data), encoding="utf-8")
    verify_buf = io.StringIO()
    with redirect_stdout(verify_buf):
        rc = cli_main(["verify-bundle", str(bundle_path)])
    assert rc == 0  # sin --strict, exit 0 con reporte


# --- Lenguaje prohibido ------------------------------------------


def test_cli_bundle_no_interpretive_language(catalog_with_shifted_series: Path) -> None:
    forbidden = (
        "likely", "probably", "suspicious", "dangerous", "malicious",
        "threat_level", "risk_level", "recommendation", "attack_intent",
    )
    buf = io.StringIO()
    with redirect_stdout(buf):
        cli_main(_bundle_args(catalog_with_shifted_series))
    raw = buf.getvalue().lower()
    for word in forbidden:
        assert word not in raw, f"palabra prohibida en bundle output: {word!r}"

