"""CLI integration tests para ADR-0039/0040/0041 (Phase 7)."""

from __future__ import annotations

import hashlib
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


@pytest.fixture
def phase6_artifacts(tmp_path: Path) -> dict[str, Path]:
    """Genera todo el pipeline hasta investigation case."""
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
    bb = io.StringIO()
    with redirect_stdout(bb):
        cli_main([
            "bundle", "12345",
            "--baseline-days", "30", "--threshold-sigma", "3.0",
            "--raw-root", str(raw_root),
            "--normalized-root", str(normalized_root),
            "--detections-root", str(tmp_path / "derived" / "conjunctions"),
        ])
    bp = tmp_path / "bundle.json"
    bp.write_text(bb.getvalue(), encoding="utf-8")
    aib = io.StringIO()
    with _redirect_stdin(io.StringIO(bb.getvalue())), redirect_stdout(aib):
        cli_main(["agent-input", "-", "--consumer-class", "explanation_agent_v01"])
    aip = tmp_path / "agent_input.json"
    aip.write_text(aib.getvalue(), encoding="utf-8")
    ab = io.StringIO()
    with _redirect_stdin(io.StringIO(aib.getvalue())), redirect_stdout(ab):
        cli_main(["explain", "-"])
    ap = tmp_path / "artifact.json"
    ap.write_text(ab.getvalue(), encoding="utf-8")
    crb = io.StringIO()
    with redirect_stdout(crb):
        cli_main(["claim-registry", str(ap), "--agent-input-file", str(aip)])
    crp = tmp_path / "cr.json"
    crp.write_text(crb.getvalue(), encoding="utf-8")
    hrb = io.StringIO()
    with redirect_stdout(hrb):
        cli_main([
            "hypothesis-registry", str(crp), "--agent-input-file", str(aip),
        ])
    hrp = tmp_path / "hr.json"
    hrp.write_text(hrb.getvalue(), encoding="utf-8")
    chb = io.StringIO()
    with redirect_stdout(chb):
        cli_main([
            "evidence-chain", str(hrp),
            "--claim-registry-file", str(crp),
            "--explanation-artifact-file", str(ap),
            "--agent-input-file", str(aip),
        ])
    chp = tmp_path / "chain.json"
    chp.write_text(chb.getvalue(), encoding="utf-8")
    icb = io.StringIO()
    with redirect_stdout(icb):
        cli_main([
            "investigation-case", str(chp),
            "--hypothesis-registry-file", str(hrp),
            "--claim-registry-file", str(crp),
            "--explanation-artifact-file", str(ap),
            "--agent-input-file", str(aip),
            "--bundle-file", str(bp),
        ])
    icp = tmp_path / "case.json"
    icp.write_text(icb.getvalue(), encoding="utf-8")
    return {
        "bundle": bp, "agent_input": aip, "artifact": ap,
        "claim_registry": crp, "hypothesis_registry": hrp,
        "chain": chp, "case": icp,
    }


# --- revoke-artifact + verify-revocation-ledger ----------------


def test_cli_revoke_artifact_emits_valid_ledger(
    phase6_artifacts: dict[str, Path],
) -> None:
    case = json.loads(phase6_artifacts["case"].read_text(encoding="utf-8"))
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = cli_main([
            "revoke-artifact",
            "--target-artifact-type", "investigation_case",
            "--target-artifact-id", case["case_id"],
            "--target-artifact-signature", case["case_signature"],
            "--reason", "voluntary_withdrawal",
        ])
    assert rc == 0
    led = json.loads(buf.getvalue())
    assert led["ledger_id"] == led["ledger_hash"]
    assert led["n_records"] == 1
    assert led["records"][0]["target_artifact_id"] == case["case_id"]


def test_cli_verify_revocation_ledger_valid(
    phase6_artifacts: dict[str, Path], tmp_path: Path,
) -> None:
    case = json.loads(phase6_artifacts["case"].read_text(encoding="utf-8"))
    led_buf = io.StringIO()
    with redirect_stdout(led_buf):
        cli_main([
            "revoke-artifact",
            "--target-artifact-type", "investigation_case",
            "--target-artifact-id", case["case_id"],
            "--target-artifact-signature", case["case_signature"],
            "--reason", "voluntary_withdrawal",
        ])
    led_path = tmp_path / "rev.json"
    led_path.write_text(led_buf.getvalue(), encoding="utf-8")
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = cli_main(["verify-revocation-ledger", str(led_path), "--strict"])
    assert rc == 0
    rpt = json.loads(buf.getvalue())
    assert rpt["is_valid"] is True


def test_cli_verify_revocation_ledger_from_stdin(
    phase6_artifacts: dict[str, Path],
) -> None:
    case = json.loads(phase6_artifacts["case"].read_text(encoding="utf-8"))
    led_buf = io.StringIO()
    with redirect_stdout(led_buf):
        cli_main([
            "revoke-artifact",
            "--target-artifact-type", "investigation_case",
            "--target-artifact-id", case["case_id"],
            "--target-artifact-signature", case["case_signature"],
            "--reason", "voluntary_withdrawal",
        ])
    buf = io.StringIO()
    with _redirect_stdin(io.StringIO(led_buf.getvalue())), redirect_stdout(buf):
        rc = cli_main(["verify-revocation-ledger", "-"])
    assert rc == 0


# --- external-source-registry + verify ------------------------


def test_cli_external_source_registry_valid(
    phase6_artifacts: dict[str, Path], tmp_path: Path,
) -> None:
    bundle = json.loads(phase6_artifacts["bundle"].read_text(encoding="utf-8"))
    evidence_ids = [bp["evidence_id"] for bp in bundle["evidence_payloads"]]
    # Construir un record dummy y mapping
    fetched_at = datetime(2024, 1, 1, 6, 0, tzinfo=timezone.utc)
    payload = b"DUMMY_TLE_FIXTURE"
    payload_hash = hashlib.sha256(payload).hexdigest()
    # Compute source_record_id via library
    from orbital_sentinel.analytics.external_sources import (
        build_external_source_record,
    )
    rec = build_external_source_record(
        source_provider="test_fixture",
        source_url="file:///dummy.txt",
        source_dataset_identifier="dummy.txt",
        fetched_at=fetched_at,
        source_payload_hash=payload_hash,
        source_payload_size_bytes=len(payload),
        source_content_type="tle_text",
    )
    records_doc = {
        "records": [rec.model_dump(mode="json")],
        "evidence_to_source_record_mapping": {
            ev: [rec.source_record_id] for ev in evidence_ids
        },
    }
    records_path = tmp_path / "records.json"
    records_path.write_text(json.dumps(records_doc), encoding="utf-8")
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = cli_main([
            "external-source-registry", str(phase6_artifacts["bundle"]),
            "--records-file", str(records_path),
        ])
    assert rc == 0
    reg = json.loads(buf.getvalue())
    assert reg["registry_id"] == reg["registry_hash"]
    assert reg["source_bundle_id"] == bundle["bundle_id"]
    reg_path = tmp_path / "src.json"
    reg_path.write_text(buf.getvalue(), encoding="utf-8")
    vbuf = io.StringIO()
    with redirect_stdout(vbuf):
        rc = cli_main([
            "verify-external-source-registry", str(reg_path),
            "--bundle-file", str(phase6_artifacts["bundle"]),
            "--strict",
        ])
    assert rc == 0
    rpt = json.loads(vbuf.getvalue())
    assert rpt["is_valid"] is True


# --- dissent-record + dissent-ledger + verify ------------------


def test_cli_dissent_full_flow(
    phase6_artifacts: dict[str, Path], tmp_path: Path,
) -> None:
    case = json.loads(phase6_artifacts["case"].read_text(encoding="utf-8"))
    # Build dissent record 0
    rec_buf = io.StringIO()
    with redirect_stdout(rec_buf):
        rc = cli_main([
            "dissent-record",
            "--target-case-id", case["case_id"],
            "--target-case-signature", case["case_signature"],
            "--dissent-index", "0",
            "--dissent-type", "methodological_objection",
        ])
    assert rc == 0
    rec_path = tmp_path / "dis_rec.json"
    rec_path.write_text(rec_buf.getvalue(), encoding="utf-8")
    # Build ledger from record
    led_buf = io.StringIO()
    with redirect_stdout(led_buf):
        rc = cli_main([
            "dissent-ledger",
            "--target-case-id", case["case_id"],
            "--target-case-signature", case["case_signature"],
            "--record-file", str(rec_path),
        ])
    assert rc == 0
    led_path = tmp_path / "dis.json"
    led_path.write_text(led_buf.getvalue(), encoding="utf-8")
    led = json.loads(led_buf.getvalue())
    assert led["target_case_id"] == case["case_id"]
    assert led["n_records"] == 1
    # Verify
    vbuf = io.StringIO()
    with redirect_stdout(vbuf):
        rc = cli_main(["verify-dissent-ledger", str(led_path), "--strict"])
    assert rc == 0
    rpt = json.loads(vbuf.getvalue())
    assert rpt["is_valid"] is True


def test_cli_dissent_ledger_empty_target_no_records(
    phase6_artifacts: dict[str, Path], tmp_path: Path,
) -> None:
    """An empty dissent ledger about a case is structurally valid."""
    case = json.loads(phase6_artifacts["case"].read_text(encoding="utf-8"))
    led_buf = io.StringIO()
    with redirect_stdout(led_buf):
        rc = cli_main([
            "dissent-ledger",
            "--target-case-id", case["case_id"],
            "--target-case-signature", case["case_signature"],
        ])
    assert rc == 0
    led = json.loads(led_buf.getvalue())
    assert led["n_records"] == 0
    assert led["ledger_emit_reason"] == "empty_ledger"


def test_cli_verify_dissent_ledger_from_stdin(
    phase6_artifacts: dict[str, Path], tmp_path: Path,
) -> None:
    case = json.loads(phase6_artifacts["case"].read_text(encoding="utf-8"))
    led_buf = io.StringIO()
    with redirect_stdout(led_buf):
        cli_main([
            "dissent-ledger",
            "--target-case-id", case["case_id"],
            "--target-case-signature", case["case_signature"],
        ])
    buf = io.StringIO()
    with _redirect_stdin(io.StringIO(led_buf.getvalue())), redirect_stdout(buf):
        rc = cli_main(["verify-dissent-ledger", "-"])
    assert rc == 0


# --- End-to-end Phase 7 ----------------------------------------


def test_cli_full_phase7_chain(
    phase6_artifacts: dict[str, Path], tmp_path: Path,
) -> None:
    """case → revoke + dissent + (optional) external_source_registry."""
    case = json.loads(phase6_artifacts["case"].read_text(encoding="utf-8"))
    # Revocation
    rev_buf = io.StringIO()
    with redirect_stdout(rev_buf):
        cli_main([
            "revoke-artifact",
            "--target-artifact-type", "investigation_case",
            "--target-artifact-id", case["case_id"],
            "--target-artifact-signature", case["case_signature"],
            "--reason", "voluntary_withdrawal",
        ])
    rev_path = tmp_path / "rev.json"
    rev_path.write_text(rev_buf.getvalue(), encoding="utf-8")
    vbuf = io.StringIO()
    with redirect_stdout(vbuf):
        rc = cli_main(["verify-revocation-ledger", str(rev_path), "--strict"])
    assert rc == 0
    # Dissent
    rec_buf = io.StringIO()
    with redirect_stdout(rec_buf):
        cli_main([
            "dissent-record",
            "--target-case-id", case["case_id"],
            "--target-case-signature", case["case_signature"],
            "--dissent-index", "0",
            "--dissent-type", "scope_disagreement",
        ])
    rec_path = tmp_path / "drec.json"
    rec_path.write_text(rec_buf.getvalue(), encoding="utf-8")
    led_buf = io.StringIO()
    with redirect_stdout(led_buf):
        cli_main([
            "dissent-ledger",
            "--target-case-id", case["case_id"],
            "--target-case-signature", case["case_signature"],
            "--record-file", str(rec_path),
        ])
    dl_path = tmp_path / "dl.json"
    dl_path.write_text(led_buf.getvalue(), encoding="utf-8")
    vbuf2 = io.StringIO()
    with redirect_stdout(vbuf2):
        rc = cli_main(["verify-dissent-ledger", str(dl_path), "--strict"])
    assert rc == 0
