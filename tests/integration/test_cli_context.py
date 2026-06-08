"""CLI integration tests para ``orbital-sentinel context`` (ADR-0030)."""

from __future__ import annotations

import io
import json
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from orbital_sentinel.catalog.orbital_elements import OrbitalElementsRepository
from orbital_sentinel.orchestration.cli import main as cli_main
from tests.unit.test_maneuver_series import make_element

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


def _common(catalog: Path, norad: int = 12345) -> list[str]:
    return [
        "context", str(norad),
        "--baseline-days", "30",
        "--threshold-sigma", "3.0",
        "--raw-root", str(catalog / "raw"),
        "--normalized-root", str(catalog / "normalized"),
        "--detections-root", str(catalog / "derived" / "conjunctions"),
    ]


# --- Comportamiento general ----------------------------------------


def test_cli_context_emits_valid_json(catalog_with_shifted_series: Path) -> None:
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = cli_main(_common(catalog_with_shifted_series))
    assert rc == 0
    out = json.loads(buf.getvalue())
    assert out["object_id"] == 12345
    assert out["schema_version"] == "0.1.0"
    assert out["explanation_engine_version"] == "0.1.0"
    assert "context_id" in out
    assert "source_catalog_signature" in out


def test_cli_context_detector_summaries_always_three(
    catalog_with_shifted_series: Path,
) -> None:
    buf = io.StringIO()
    with redirect_stdout(buf):
        cli_main(_common(catalog_with_shifted_series))
    out = json.loads(buf.getvalue())
    detectors = [s["source_detector"] for s in out["detector_summaries"]]
    assert detectors == [
        "anomaly_detection_v01",
        "conjunction_detection_v01",
        "maneuver_detection_v01",
    ]


def test_cli_context_with_empty_catalog(empty_catalog: Path) -> None:
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = cli_main(_common(empty_catalog))
    assert rc == 0
    out = json.loads(buf.getvalue())
    assert out["n_evidence_total"] == 0
    assert out["evidence_references"] == []
    assert out["timeline"]["entries"] == []
    assert out["coverage_window_start"] is None
    assert out["coverage_window_end"] is None
    assert out["coverage_duration_seconds"] is None
    # Detector summaries siempre presentes con n_events=0
    assert len(out["detector_summaries"]) == 3
    assert all(s["n_events"] == 0 for s in out["detector_summaries"])


def test_cli_context_carries_honesty_payload_hash(
    catalog_with_shifted_series: Path,
) -> None:
    buf = io.StringIO()
    with redirect_stdout(buf):
        cli_main(_common(catalog_with_shifted_series))
    out = json.loads(buf.getvalue())
    assert out["evidence_references"]
    for ref in out["evidence_references"]:
        assert "honesty_payload_hash" in ref
        assert len(ref["honesty_payload_hash"]) == 64


# --- Determinismo ------------------------------------------------


def test_cli_context_id_reproducible_across_invocations(
    catalog_with_shifted_series: Path,
) -> None:
    buf1 = io.StringIO()
    buf2 = io.StringIO()
    with redirect_stdout(buf1):
        cli_main(_common(catalog_with_shifted_series))
    with redirect_stdout(buf2):
        cli_main(_common(catalog_with_shifted_series))
    out1 = json.loads(buf1.getvalue())
    out2 = json.loads(buf2.getvalue())
    assert out1["context_id"] == out2["context_id"]
    assert out1["source_catalog_signature"] == out2["source_catalog_signature"]


def test_cli_context_evidence_ids_match_between_runs(
    catalog_with_shifted_series: Path,
) -> None:
    buf1 = io.StringIO()
    buf2 = io.StringIO()
    with redirect_stdout(buf1):
        cli_main(_common(catalog_with_shifted_series))
    with redirect_stdout(buf2):
        cli_main(_common(catalog_with_shifted_series))
    out1 = json.loads(buf1.getvalue())
    out2 = json.loads(buf2.getvalue())
    ids1 = [r["evidence_id"] for r in out1["evidence_references"]]
    ids2 = [r["evidence_id"] for r in out2["evidence_references"]]
    assert ids1 == ids2


# --- Filtros -----------------------------------------------------


def test_cli_context_filter_by_detector_maneuver(
    catalog_with_shifted_series: Path,
) -> None:
    buf = io.StringIO()
    with redirect_stdout(buf):
        cli_main([*_common(catalog_with_shifted_series), "--detector", "maneuver"])
    out = json.loads(buf.getvalue())
    for ref in out["evidence_references"]:
        assert ref["source_detector"] == "maneuver_detection_v01"


def test_cli_context_filter_by_detector_anomaly(
    catalog_with_shifted_series: Path,
) -> None:
    buf = io.StringIO()
    with redirect_stdout(buf):
        cli_main([*_common(catalog_with_shifted_series), "--detector", "anomaly"])
    out = json.loads(buf.getvalue())
    for ref in out["evidence_references"]:
        assert ref["source_detector"] == "anomaly_detection_v01"


def test_cli_context_filter_excludes_with_high_from(
    catalog_with_shifted_series: Path,
) -> None:
    far_future = (EPOCH + timedelta(days=1000)).isoformat().replace("+00:00", "Z")
    buf = io.StringIO()
    with redirect_stdout(buf):
        cli_main([*_common(catalog_with_shifted_series), "--from", far_future])
    out = json.loads(buf.getvalue())
    assert out["n_evidence_total"] == 0


def test_cli_context_filter_excludes_with_low_to(
    catalog_with_shifted_series: Path,
) -> None:
    far_past = EPOCH.isoformat().replace("+00:00", "Z")
    buf = io.StringIO()
    with redirect_stdout(buf):
        cli_main([*_common(catalog_with_shifted_series), "--to", far_past])
    out = json.loads(buf.getvalue())
    assert out["n_evidence_total"] == 0


def test_cli_context_unknown_detector_choice_rejected(
    catalog_with_shifted_series: Path,
) -> None:
    with pytest.raises(SystemExit) as exc:
        cli_main([*_common(catalog_with_shifted_series), "--detector", "not_real"])
    assert exc.value.code == 2


# --- Lenguaje prohibido -----------------------------------------


def test_cli_context_no_interpretive_language(
    catalog_with_shifted_series: Path,
) -> None:
    """El JSON output no debe contener vocabulario interpretativo prohibido.

    Notas:
    * ``score`` aparece SOLO como sustring legítimo en ``anomaly_score`` y
      ``z_score_*`` (campos honesty del detector). Buscamos las palabras
      como tokens aislados con guion bajo o espacio.
    """
    forbidden = (
        "likely", "probably", "suspicious", "dangerous", "malicious",
        "threat", "attack", "intent", "operator_action", "risk_score",
        "confidence_percentage", "danger_level", "recommendation",
        "explanation_text", "narrative",
    )
    buf = io.StringIO()
    with redirect_stdout(buf):
        cli_main(_common(catalog_with_shifted_series))
    raw = buf.getvalue().lower()
    for word in forbidden:
        assert word not in raw, f"palabra prohibida en output: {word!r}"


# --- Trazabilidad y consistencia interna -----------------------


def test_cli_context_n_total_matches_references(
    catalog_with_shifted_series: Path,
) -> None:
    buf = io.StringIO()
    with redirect_stdout(buf):
        cli_main(_common(catalog_with_shifted_series))
    out = json.loads(buf.getvalue())
    assert out["n_evidence_total"] == len(out["evidence_references"])


def test_cli_context_timeline_matches_references_count(
    catalog_with_shifted_series: Path,
) -> None:
    buf = io.StringIO()
    with redirect_stdout(buf):
        cli_main(_common(catalog_with_shifted_series))
    out = json.loads(buf.getvalue())
    assert out["timeline"]["n_entries"] == out["n_evidence_total"]


def test_cli_context_object_id_consistent(
    catalog_with_shifted_series: Path,
) -> None:
    buf = io.StringIO()
    with redirect_stdout(buf):
        cli_main(_common(catalog_with_shifted_series))
    out = json.loads(buf.getvalue())
    for ref in out["evidence_references"]:
        assert ref["object_id"] == 12345


def test_cli_context_exit_zero_on_empty_catalog(empty_catalog: Path) -> None:
    """Catálogo vacío es estado válido (no es error)."""
    rc = cli_main(_common(empty_catalog))
    assert rc == 0
