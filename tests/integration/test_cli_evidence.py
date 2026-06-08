"""CLI integration tests para ``orbital-sentinel evidence`` (ADR-0029)."""

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
    """Catálogo con 25 OrbitalElements + shift en mean_motion en índice 21.

    Suficiente para que anomalías y maniobras detecten algo.
    """
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
def catalog_with_two_tles_only(tmp_path: Path) -> Path:
    """Catálogo con solo 2 OrbitalElements: muy poca historia."""
    normalized_root = tmp_path / "normalized"
    (tmp_path / "raw").mkdir(parents=True, exist_ok=True)
    elements = [
        make_element(
            days_offset=0.0, tle_hash="a" * 64,
            content_hash_source="z" * 64, tle_index=0,
        ),
        make_element(
            days_offset=1.0, tle_hash="b" * 64,
            content_hash_source="z" * 64, tle_index=1,
        ),
    ]
    OrbitalElementsRepository(normalized_root).insert_many(elements)
    return tmp_path


@pytest.fixture
def empty_catalog(tmp_path: Path) -> Path:
    (tmp_path / "raw").mkdir(parents=True, exist_ok=True)
    (tmp_path / "normalized").mkdir(parents=True, exist_ok=True)
    return tmp_path


def _common(catalog: Path, norad: int = 12345) -> list[str]:
    return [
        "evidence", str(norad),
        "--baseline-days", "30",
        "--threshold-sigma", "3.0",
        "--raw-root", str(catalog / "raw"),
        "--normalized-root", str(catalog / "normalized"),
        "--detections-root", str(catalog / "derived" / "conjunctions"),
    ]


# --- CLI behaviour ----------------------------------------------------


def test_cli_evidence_emits_valid_json(catalog_with_shifted_series: Path) -> None:
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = cli_main(_common(catalog_with_shifted_series))
    assert rc == 0
    out = json.loads(buf.getvalue())
    assert out["norad_cat_id"] == 12345
    assert "evidence" in out
    assert out["schema_version"] == "0.1.0"
    assert out["catalog_engine_version"] == "0.1.0"
    assert out["n_evidence_returned"] == len(out["evidence"])


def test_cli_evidence_finds_anomaly_and_maneuver_in_shifted_series(
    catalog_with_shifted_series: Path,
) -> None:
    buf = io.StringIO()
    with redirect_stdout(buf):
        cli_main(_common(catalog_with_shifted_series))
    out = json.loads(buf.getvalue())
    detectors = {ev["source_detector"] for ev in out["evidence"]}
    # En una serie con shift sintético, ambos detectores estadísticos
    # deberían disparar al menos un evento.
    assert "anomaly_detection_v01" in detectors
    assert "maneuver_detection_v01" in detectors


def test_cli_evidence_filter_by_detector_anomaly(
    catalog_with_shifted_series: Path,
) -> None:
    buf = io.StringIO()
    with redirect_stdout(buf):
        cli_main([*_common(catalog_with_shifted_series), "--detector", "anomaly"])
    out = json.loads(buf.getvalue())
    detectors = {ev["source_detector"] for ev in out["evidence"]}
    assert detectors.issubset({"anomaly_detection_v01"})


def test_cli_evidence_filter_by_detector_maneuver(
    catalog_with_shifted_series: Path,
) -> None:
    buf = io.StringIO()
    with redirect_stdout(buf):
        cli_main([*_common(catalog_with_shifted_series), "--detector", "maneuver"])
    out = json.loads(buf.getvalue())
    detectors = {ev["source_detector"] for ev in out["evidence"]}
    assert detectors.issubset({"maneuver_detection_v01"})


def test_cli_evidence_empty_catalog_returns_empty(empty_catalog: Path) -> None:
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = cli_main(_common(empty_catalog))
    assert rc == 0
    out = json.loads(buf.getvalue())
    assert out["n_evidence_returned"] == 0
    assert out["evidence"] == []


def test_cli_evidence_insufficient_series_returns_empty(
    catalog_with_two_tles_only: Path,
) -> None:
    """Con 2 TLEs y baseline_days≥5, detectores no detectan; catálogo vacío."""
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = cli_main(_common(
            catalog_with_two_tles_only,
            norad=make_element().norad_cat_id,
        ))
    assert rc == 0
    out = json.loads(buf.getvalue())
    assert out["n_evidence_returned"] == 0


def test_cli_evidence_filter_by_epoch_range(
    catalog_with_shifted_series: Path,
) -> None:
    """Filtro --from/--to debe respetarse."""
    buf = io.StringIO()
    far_future = (EPOCH + timedelta(days=1000)).isoformat().replace("+00:00", "Z")
    with redirect_stdout(buf):
        cli_main([*_common(catalog_with_shifted_series), "--from", far_future])
    out = json.loads(buf.getvalue())
    assert out["n_evidence_returned"] == 0


def test_cli_evidence_event_carries_honesty_payload(
    catalog_with_shifted_series: Path,
) -> None:
    buf = io.StringIO()
    with redirect_stdout(buf):
        cli_main(_common(catalog_with_shifted_series))
    out = json.loads(buf.getvalue())
    assert out["evidence"]
    for ev in out["evidence"]:
        assert isinstance(ev["honesty_payload"], dict)
        assert "detection_method_name" in ev["honesty_payload"]
        assert ev["is_apparent_not_confirmed"] is True


def test_cli_evidence_no_classification_language(
    catalog_with_shifted_series: Path,
) -> None:
    """ADR-0029 prohíbe lenguaje de clasificación/riesgo en el output."""
    forbidden = {
        "likely", "probably", "suspicious", "dangerous", "malicious",
        "threat", "attack", "intent", "operator_action", "risk_score",
        "confidence_percentage", "danger_level", "recommendation",
    }
    buf = io.StringIO()
    with redirect_stdout(buf):
        cli_main(_common(catalog_with_shifted_series))
    raw = buf.getvalue().lower()
    for word in forbidden:
        assert word not in raw, f"palabra prohibida en output: {word!r}"


def test_cli_evidence_reproducibility(catalog_with_shifted_series: Path) -> None:
    """Dos invocaciones consecutivas producen los mismos evidence_ids."""
    buf1 = io.StringIO()
    buf2 = io.StringIO()
    with redirect_stdout(buf1):
        cli_main(_common(catalog_with_shifted_series))
    with redirect_stdout(buf2):
        cli_main(_common(catalog_with_shifted_series))
    out1 = json.loads(buf1.getvalue())
    out2 = json.loads(buf2.getvalue())
    ids1 = [e["evidence_id"] for e in out1["evidence"]]
    ids2 = [e["evidence_id"] for e in out2["evidence"]]
    assert ids1 == ids2


def test_cli_evidence_unknown_detector_choice_rejected(
    catalog_with_shifted_series: Path,
) -> None:
    """argparse rechaza --detector con valor fuera del choices."""
    with pytest.raises(SystemExit) as exc:
        cli_main([
            *_common(catalog_with_shifted_series),
            "--detector", "not_a_detector",
        ])
    assert exc.value.code == 2


def test_cli_evidence_object_id_matches_requested_norad(
    catalog_with_shifted_series: Path,
) -> None:
    buf = io.StringIO()
    with redirect_stdout(buf):
        cli_main(_common(catalog_with_shifted_series))
    out = json.loads(buf.getvalue())
    for ev in out["evidence"]:
        assert ev["object_id"] == 12345
