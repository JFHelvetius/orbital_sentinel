"""CLI integration tests para `orbital-sentinel maneuvers` (ADR-0027)."""

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
def catalog_with_series(tmp_path: Path) -> Path:
    """Catálogo con 25 OrbitalElements del NORAD 12345 + un salto en transición 20."""
    normalized_root = tmp_path / "normalized"
    raw_root = tmp_path / "raw"
    raw_root.mkdir(parents=True, exist_ok=True)

    elements = []
    for i in range(25):
        injected = 1e-2 if i > 20 else 0.0
        elements.append(
            make_element(
                days_offset=float(i),
                mean_motion=15.5 + 1e-7 * i + injected,
                tle_hash=f"{i:064x}",
                content_hash_source="c" * 64,
                tle_index=i,
            )
        )
    OrbitalElementsRepository(normalized_root).insert_many(elements)
    return tmp_path


def _common_args(catalog: Path, norad: int = 12345) -> list[str]:
    return [
        "maneuvers", str(norad),
        "--baseline-days", "30",
        "--threshold-sigma", "3.0",
        "--raw-root", str(catalog / "raw"),
        "--normalized-root", str(catalog / "normalized"),
    ]


# --- C1 ---------------------------------------------------------------


def test_c1_cli_maneuvers_emits_valid_json(catalog_with_series: Path) -> None:
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = cli_main(_common_args(catalog_with_series))
    assert rc == 0
    out = json.loads(buf.getvalue())
    assert out["norad_cat_id"] == 12345
    assert out["schema_version"] == "0.1.0"
    assert out["engine_version"] == "0.1.0"
    assert "events" in out and isinstance(out["events"], list)
    assert out["n_events"] == len(out["events"])


# --- C2 ---------------------------------------------------------------


def test_c2_cli_maneuvers_detects_synthetic_event(catalog_with_series: Path) -> None:
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = cli_main(_common_args(catalog_with_series))
    assert rc == 0
    out = json.loads(buf.getvalue())
    assert out["n_events"] >= 1
    event = out["events"][0]
    assert event["dominant_component"] == "mean_motion"


# --- C3 ---------------------------------------------------------------


def test_c3_cli_maneuvers_missing_norad_exit_2(catalog_with_series: Path) -> None:
    rc = cli_main([
        "maneuvers", "99999999",
        "--raw-root", str(catalog_with_series / "raw"),
        "--normalized-root", str(catalog_with_series / "normalized"),
    ])
    assert rc == 2


# --- C4 ---------------------------------------------------------------


def test_c4_cli_maneuvers_insufficient_series_exit_2(tmp_path: Path) -> None:
    """Catálogo con 1 solo OrbitalElement para el NORAD pedido → exit 2."""
    normalized_root = tmp_path / "normalized"
    (tmp_path / "raw").mkdir(parents=True, exist_ok=True)
    el = make_element(
        days_offset=0.0, tle_hash="a" * 64, content_hash_source="c" * 64, tle_index=0,
    )
    OrbitalElementsRepository(normalized_root).insert_many([el])
    rc = cli_main([
        "maneuvers", str(el.norad_cat_id),
        "--raw-root", str(tmp_path / "raw"),
        "--normalized-root", str(normalized_root),
    ])
    assert rc == 2


# --- C5 ---------------------------------------------------------------


def test_c5_cli_maneuvers_honesty_fields_in_output(catalog_with_series: Path) -> None:
    buf = io.StringIO()
    with redirect_stdout(buf):
        cli_main(_common_args(catalog_with_series))
    out = json.loads(buf.getvalue())
    assert out["detection_method_name"] == "element_jump_z_score_v1"
    assert out["is_apparent_not_confirmed"] is True
    assert "baseline_window_days" in out
    assert "detection_threshold_sigma" in out
    assert "min_baseline_samples" in out
    assert "sigma_floor" in out
