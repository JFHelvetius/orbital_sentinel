"""CLI integration tests para `scan`, `best`, `conflicts` (ADRs 0024 + 0025)."""

from __future__ import annotations

import hashlib
import io
import json
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from orbital_sentinel.catalog import TLESnapshot, TLESnapshotsRepository
from orbital_sentinel.catalog.normalizers import normalize_snapshot
from orbital_sentinel.catalog.orbital_elements import OrbitalElementsRepository
from orbital_sentinel.orchestration.cli import main as cli_main

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "tle"
EPOCH = datetime(2008, 9, 20, 12, 25, 40, tzinfo=timezone.utc)
DERIVED_AT_FIXED = datetime(2026, 6, 6, 12, 0, tzinfo=timezone.utc)
CDMX = "19.4326,-99.1332,2240"


@pytest.fixture
def populated_catalog(tmp_path: Path) -> Path:
    """Catálogo Raw+Normalized con ISS Vallado 2008-09-20 (NORAD 25544)."""
    raw_root = tmp_path / "raw"
    normalized_root = tmp_path / "normalized"
    text = (FIXTURES / "iss_vallado_2008.txt").read_text(encoding="ascii")
    encoded = text.encode("ascii")
    snap = TLESnapshot(
        content_hash=hashlib.sha256(encoded).hexdigest(),
        source="celestrak",
        dataset="stations",
        url="https://example/",
        fetched_at=DERIVED_AT_FIXED,
        raw_text=text,
        n_bytes=len(encoded),
    )
    TLESnapshotsRepository(raw_root).insert(snap)
    OrbitalElementsRepository(normalized_root).insert_many(
        normalize_snapshot(snap, derived_at=DERIVED_AT_FIXED)
    )
    return tmp_path


def _common_args(catalog: Path, hours: int = 6) -> list[str]:
    return [
        "--observer", CDMX,
        "--norad-ids", "25544",
        "--from", EPOCH.isoformat().replace("+00:00", "Z"),
        "--to", (EPOCH + timedelta(hours=hours)).isoformat().replace("+00:00", "Z"),
        "--step", "0.5",
        "--min-elevation", "10.0",
        "--raw-root", str(catalog / "raw"),
        "--normalized-root", str(catalog / "normalized"),
    ]


# --- scan ----------------------------------------------------------------


def test_cli_scan_emits_valid_json_with_observatory_shape(populated_catalog: Path) -> None:
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = cli_main(["scan", *_common_args(populated_catalog)])
    assert rc == 0
    out = json.loads(buf.getvalue())
    # Identidad declarada
    assert out["observer_lat_deg"] == 19.4326
    # Counts coherentes
    assert out["n_satellites_input"] == 1
    assert out["n_satellites_scanned"] + out["n_satellites_skipped_geometric"] == 1
    # Honesty fields
    assert out["frame_model"] == "spherical_earth_geocentric_topocentric_v1"
    assert out["solar_position_model"] == "vallado_2008_low_precision_v1"
    assert out["shadow_model"] == "cylindrical_earth_shadow_v1"
    # Versioning
    assert out["schema_version"] == "0.1.0"
    assert out["engine_version"] == "0.1.0"
    # UsefulPassFilter declarado en el output
    assert "useful_pass_filter" in out
    assert out["useful_pass_filter"]["useful_pass_filter_version"] == "0.1.0"


def test_cli_scan_with_twilight_and_illumination_filters(populated_catalog: Path) -> None:
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = cli_main([
            "scan", *_common_args(populated_catalog, hours=24),
            "--require-twilight", "civil",
            "--require-illuminated",
        ])
    assert rc == 0
    out = json.loads(buf.getvalue())
    assert out["useful_pass_filter"]["require_observer_in_twilight_or_darker"] is True
    assert out["useful_pass_filter"]["minimum_twilight_phase"] == "civil"
    assert out["useful_pass_filter"]["require_satellite_illuminated"] is True
    assert out["n_useful_passes_total"] <= out["n_passes_total"]


# --- best ----------------------------------------------------------------


def test_cli_best_orders_by_criterion(populated_catalog: Path) -> None:
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = cli_main([
            "best", *_common_args(populated_catalog, hours=24),
            "--criterion", "max_elevation",
            "--limit", "3",
        ])
    assert rc == 0
    out = json.loads(buf.getvalue())
    assert out["criterion"] == "max_elevation"
    assert out["n_returned"] == len(out["ranked"])
    # Orden descendente por elevación máxima
    if len(out["ranked"]) >= 2:
        values = [r["criterion_value"] for r in out["ranked"]]
        assert values == sorted(values, reverse=True)
    # Rank consecutivo desde 1
    for i, r in enumerate(out["ranked"], start=1):
        assert r["rank"] == i


# --- conflicts ----------------------------------------------------------


def test_cli_conflicts_empty_with_single_satellite(populated_catalog: Path) -> None:
    """Con un solo NORAD no puede haber conflictos (pares require distinct)."""
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = cli_main([
            "conflicts", *_common_args(populated_catalog, hours=24),
        ])
    assert rc == 0
    out = json.loads(buf.getvalue())
    assert out["n_conflicts"] == 0
    assert out["conflicts"] == []


# --- Failure modes -------------------------------------------------------


def test_cli_scan_missing_norad_returns_exit_1(populated_catalog: Path) -> None:
    rc = cli_main([
        "scan",
        "--observer", CDMX,
        "--norad-ids", "99999999",
        "--from", EPOCH.isoformat().replace("+00:00", "Z"),
        "--to", (EPOCH + timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
        "--step", "1.0",
        "--raw-root", str(populated_catalog / "raw"),
        "--normalized-root", str(populated_catalog / "normalized"),
    ])
    assert rc == 1


def test_cli_best_requires_criterion(populated_catalog: Path) -> None:
    """argparse rechaza ausencia de --criterion → exit 2."""
    with pytest.raises(SystemExit) as exc:
        cli_main([
            "best", *_common_args(populated_catalog),
        ])
    assert exc.value.code == 2
