"""CLI integration tests para ``orbital-sentinel anomalies`` (ADR-0028)."""

from __future__ import annotations

import io
import json
from contextlib import redirect_stdout
from pathlib import Path

import pytest

from orbital_sentinel.catalog.orbital_elements import OrbitalElementsRepository
from orbital_sentinel.orchestration.cli import main as cli_main
from tests.unit.test_maneuver_series import make_element


@pytest.fixture
def catalog_with_shifted_series(tmp_path: Path) -> Path:
    """Catálogo con 25 OrbitalElements + shift de mean_motion en índice 21."""
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


def _common(catalog: Path, norad: int = 12345) -> list[str]:
    return [
        "anomalies", str(norad),
        "--baseline-days", "30",
        "--threshold-sigma", "3.0",
        "--raw-root", str(catalog / "raw"),
        "--normalized-root", str(catalog / "normalized"),
    ]


def test_cli_anomalies_emits_valid_json(catalog_with_shifted_series: Path) -> None:
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = cli_main(_common(catalog_with_shifted_series))
    assert rc == 0
    out = json.loads(buf.getvalue())
    assert out["norad_cat_id"] == 12345
    assert out["schema_version"] == "0.1.0"
    assert out["analysis_engine_version"] == "0.1.0"
    assert "events" in out and isinstance(out["events"], list)
    assert out["total_anomalies_found"] == len(out["events"])
    assert out["total_objects_analyzed"] == 1


def test_cli_anomalies_detects_synthetic_shift(catalog_with_shifted_series: Path) -> None:
    buf = io.StringIO()
    with redirect_stdout(buf):
        cli_main(_common(catalog_with_shifted_series))
    out = json.loads(buf.getvalue())
    assert out["total_anomalies_found"] >= 1


def test_cli_anomalies_missing_norad_exit_2(catalog_with_shifted_series: Path) -> None:
    rc = cli_main([
        "anomalies", "99999999",
        "--raw-root", str(catalog_with_shifted_series / "raw"),
        "--normalized-root", str(catalog_with_shifted_series / "normalized"),
    ])
    assert rc == 2


def test_cli_anomalies_insufficient_series_exit_2(tmp_path: Path) -> None:
    normalized_root = tmp_path / "normalized"
    (tmp_path / "raw").mkdir(parents=True, exist_ok=True)
    el = make_element(days_offset=0.0, tle_hash="a" * 64, content_hash_source="z" * 64)
    OrbitalElementsRepository(normalized_root).insert_many([el])
    rc = cli_main([
        "anomalies", str(el.norad_cat_id),
        "--raw-root", str(tmp_path / "raw"),
        "--normalized-root", str(normalized_root),
    ])
    assert rc == 2


def test_cli_anomalies_honesty_fields_present(
    catalog_with_shifted_series: Path,
) -> None:
    buf = io.StringIO()
    with redirect_stdout(buf):
        cli_main(_common(catalog_with_shifted_series))
    out = json.loads(buf.getvalue())
    cfg = out["configuration_used"]
    assert cfg["detection_method_name"] == "self_baseline_z_score_v1"
    assert cfg["baseline_window_days"] == 30.0
    assert cfg["threshold_sigma"] == 3.0
    assert cfg["min_baseline_samples"] == 5
    assert "sigma_floor" in cfg
    assert "features_used" in cfg
    assert out["is_apparent_not_confirmed"] is True


def test_cli_anomalies_event_has_no_classification_language(
    catalog_with_shifted_series: Path,
) -> None:
    """ADR-0028 prohíbe lenguaje de clasificación. Ningún evento debe
    contener strings como 'likely', 'probably', 'suspicious', 'dangerous',
    'malicious', 'threat', 'attack'.
    """
    forbidden = {
        "likely", "probably", "suspicious", "dangerous", "malicious",
        "threat", "attack", "intent", "operator_action", "risk_score",
        "confidence", "probability",
    }
    buf = io.StringIO()
    with redirect_stdout(buf):
        cli_main(_common(catalog_with_shifted_series))
    raw = buf.getvalue().lower()
    for word in forbidden:
        assert word not in raw, f"palabra prohibida en output: {word!r}"


def test_cli_anomalies_threshold_silences(tmp_path: Path) -> None:
    """Threshold gigante sobre serie con ruido → 0 anomalías reportadas.

    Necesita una baseline con varianza no nula para que el umbral actúe como
    filtro real (serie perfectamente plana produce z=±inf por σ→0).
    """
    normalized_root = tmp_path / "normalized"
    (tmp_path / "raw").mkdir(parents=True, exist_ok=True)
    noise = [0.0, 1e-7, -2e-7, 5e-7, -1e-7, 3e-7, -4e-7, 1e-7, 2e-7, -3e-7,
             2e-7, -1e-7, 3e-7, -2e-7, 1e-7, -3e-7, 2e-7, -1e-7, 4e-7, -2e-7,
             1e-7, 3e-7, -3e-7, 2e-7, -1e-7]
    elements = []
    for i in range(25):
        bump = 5e-6 if i >= 22 else 0.0
        elements.append(
            make_element(
                days_offset=float(i),
                mean_motion=15.5 + noise[i] + bump,
                tle_hash=f"{i:064x}",
                content_hash_source="n" * 64,
                tle_index=i,
            )
        )
    OrbitalElementsRepository(normalized_root).insert_many(elements)
    rc_buf = io.StringIO()
    with redirect_stdout(rc_buf):
        cli_main([
            "anomalies", str(elements[0].norad_cat_id),
            "--baseline-days", "30",
            "--threshold-sigma", "1000",
            "--raw-root", str(tmp_path / "raw"),
            "--normalized-root", str(normalized_root),
        ])
    out = json.loads(rc_buf.getvalue())
    assert out["total_anomalies_found"] == 0
