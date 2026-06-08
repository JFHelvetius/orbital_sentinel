"""CLI integration tests para `orbital-sentinel passes` (ADR-0023 Fase 5)."""

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


@pytest.fixture
def populated_catalog(tmp_path: Path) -> Path:
    """Crea un catálogo de Raw + Normalized con ISS Vallado 2008-09-20."""
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
    snapshots = TLESnapshotsRepository(raw_root)
    snapshots.insert(snap)
    elements = normalize_snapshot(snap, derived_at=DERIVED_AT_FIXED)
    OrbitalElementsRepository(normalized_root).insert_many(elements)
    return tmp_path


def test_cli_passes_emits_valid_json(populated_catalog: Path) -> None:
    """`passes` emite JSON parseable con el shape esperado."""
    args = [
        "passes", "25544",
        "--observer", "19.4326,-99.1332,2240",
        "--from", EPOCH.isoformat().replace("+00:00", "Z"),
        "--to", (EPOCH + timedelta(hours=2)).isoformat().replace("+00:00", "Z"),
        "--step", "0.5",
        "--min-elevation", "10.0",
        "--raw-root", str(populated_catalog / "raw"),
        "--normalized-root", str(populated_catalog / "normalized"),
    ]
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = cli_main(args)
    assert rc == 0
    output = json.loads(buf.getvalue())
    # Campos clave declarados por ADR-0023
    assert output["norad_cat_id"] == 25544
    assert output["frame_model"] == "spherical_earth_geocentric_topocentric_v1"
    assert output["gmst_model"] == "iau_1982_ut1_equals_utc_v1"
    assert output["culmination_method"] == "parabolic_local_fit_v1"
    assert output["schema_version"] == "0.1.0"
    assert output["engine_version"] == "0.1.0"
    assert "passes" in output and isinstance(output["passes"], list)
    assert output["n_passes"] == len(output["passes"])


def test_cli_passes_invalid_observer_format(populated_catalog: Path) -> None:
    """Observer con formato inválido → exit 2 (argparse error)."""
    args = [
        "passes", "25544",
        "--observer", "not_three_numbers",
        "--from", EPOCH.isoformat().replace("+00:00", "Z"),
        "--to", (EPOCH + timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
        "--step", "1.0",
        "--raw-root", str(populated_catalog / "raw"),
        "--normalized-root", str(populated_catalog / "normalized"),
    ]
    with pytest.raises(SystemExit) as exc_info:
        cli_main(args)
    assert exc_info.value.code == 2


def test_cli_passes_observer_lat_out_of_range(populated_catalog: Path) -> None:
    """lat=91 → ValueError en predict_passes → exit 2 vía main()."""
    args = [
        "passes", "25544",
        "--observer", "91.0,0.0,0.0",
        "--from", EPOCH.isoformat().replace("+00:00", "Z"),
        "--to", (EPOCH + timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
        "--step", "1.0",
        "--raw-root", str(populated_catalog / "raw"),
        "--normalized-root", str(populated_catalog / "normalized"),
    ]
    rc = cli_main(args)
    assert rc == 2


def test_cli_passes_missing_norad(populated_catalog: Path) -> None:
    """NORAD ausente → OrbitalSentinelError → exit 1."""
    args = [
        "passes", "99999999",
        "--observer", "0.0,0.0,0.0",
        "--from", EPOCH.isoformat().replace("+00:00", "Z"),
        "--to", (EPOCH + timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
        "--step", "1.0",
        "--raw-root", str(populated_catalog / "raw"),
        "--normalized-root", str(populated_catalog / "normalized"),
    ]
    rc = cli_main(args)
    assert rc == 1
