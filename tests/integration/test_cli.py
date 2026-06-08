"""Tests integración de la CLI v0.

Se ejercen los **núcleos testeables** (`_serialize_ingest`, `run_propagate`) y
el `main()` con argv inyectado. Sin red: el `CelesTrakSource` se instancia con
un `FakeTransport` directamente en los tests, no a través de la CLI por
default (que usaría `UrllibTransport`).

Para tests de la wiring completa de `main()`, se inyecta el transporte
mediante una sustitución puntual de `_make_ingest_pipeline`.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from orbital_sentinel.catalog import (
    OrbitalElementsRepository,
    TLESnapshotsRepository,
)
from orbital_sentinel.core.errors import OrbitalSentinelError
from orbital_sentinel.ingestion.sources import CelesTrakSource, FetchCache
from orbital_sentinel.orchestration import IngestPipeline
from orbital_sentinel.orchestration import cli as cli_module
from orbital_sentinel.orchestration.cli import (
    _parse_iso_datetime,
    _serialize_ephemeris,
    _serialize_ingest,
    main,
    run_propagate,
)

ISS_TLE = (
    b"ISS (ZARYA)\n"
    b"1 25544U 98067A   08264.51782528 -.00002182  00000-0 -11606-4 0  2927\n"
    b"2 25544  51.6416 247.4627 0006703 130.5360 325.0288 15.72125391563537\n"
)
EPOCH = datetime(2008, 9, 20, 12, 25, 40, tzinfo=timezone.utc)


class FakeTransport:
    def __init__(self, response_bytes: bytes) -> None:
        self.response_bytes = response_bytes
        self.calls: list[tuple[str, dict[str, str]]] = []

    def get(
        self, url: str, *, headers: dict[str, str], timeout: float = 30.0
    ) -> bytes:
        self.calls.append((url, dict(headers)))
        return self.response_bytes


def _build_real_pipeline(tmp_path: Path, payload: bytes = ISS_TLE) -> IngestPipeline:
    cache = FetchCache(tmp_path / "cache")
    source = CelesTrakSource(cache=cache, transport=FakeTransport(payload))
    snapshots = TLESnapshotsRepository(tmp_path / "raw")
    elements = OrbitalElementsRepository(tmp_path / "normalized")
    return IngestPipeline(source=source, snapshots=snapshots, elements=elements)


# --- _parse_iso_datetime --------------------------------------------------


def test_parse_iso_z_suffix() -> None:
    dt = _parse_iso_datetime("2008-09-20T12:00:00Z")
    assert dt == datetime(2008, 9, 20, 12, 0, tzinfo=timezone.utc)


def test_parse_iso_offset_converted_to_utc() -> None:
    dt = _parse_iso_datetime("2008-09-20T14:00:00+02:00")
    assert dt == datetime(2008, 9, 20, 12, 0, tzinfo=timezone.utc)


def test_parse_iso_rejects_naive() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        _parse_iso_datetime("2008-09-20T12:00:00")


def test_parse_iso_rejects_garbage() -> None:
    with pytest.raises(ValueError, match="inválido"):
        _parse_iso_datetime("not-a-timestamp")


# --- _serialize_ingest ----------------------------------------------------


def test_serialize_ingest_is_json_compatible(tmp_path: Path) -> None:
    pipeline = _build_real_pipeline(tmp_path)
    result = pipeline.ingest("stations")
    payload = _serialize_ingest(result)
    # Debe ser dumpable a JSON sin custom encoders
    serialized = json.dumps(payload)
    parsed = json.loads(serialized)
    assert parsed["dataset"] == "stations"
    assert parsed["snapshot_written"] is True
    assert parsed["elements_written"] == 1  # ISS TLE = 1 elemento
    assert parsed["is_new"] is True
    assert len(parsed["snapshot_content_hash"]) == 64


# --- run_propagate (núcleo) -----------------------------------------------


def test_run_propagate_after_ingest(tmp_path: Path) -> None:
    pipeline = _build_real_pipeline(tmp_path)
    pipeline.ingest("stations")

    snapshots = TLESnapshotsRepository(tmp_path / "raw")
    elements = OrbitalElementsRepository(tmp_path / "normalized")

    output = run_propagate(
        snapshots,
        elements,
        norad_cat_id=25544,
        from_time=EPOCH,
        to_time=EPOCH + timedelta(minutes=10),
        step_minutes=5.0,
    )

    assert output["norad_cat_id"] == 25544
    assert output["n_points"] == 3  # 0, 5, 10 minutos
    assert len(output["ephemerides"]) == 3
    for ephem in output["ephemerides"]:
        assert len(ephem["position_teme_km"]) == 3
        assert len(ephem["velocity_teme_km_s"]) == 3
        assert ephem["sgp4_error_code"] == 0
        # Sanidad: ISS está en LEO
        import math

        r = ephem["position_teme_km"]
        r_mag = math.sqrt(r[0] ** 2 + r[1] ** 2 + r[2] ** 2)
        assert 6600 < r_mag < 7100


def test_run_propagate_carries_traceability_fields(tmp_path: Path) -> None:
    pipeline = _build_real_pipeline(tmp_path)
    pipeline.ingest("stations")

    snapshots = TLESnapshotsRepository(tmp_path / "raw")
    elements = OrbitalElementsRepository(tmp_path / "normalized")

    output = run_propagate(
        snapshots, elements,
        norad_cat_id=25544,
        from_time=EPOCH, to_time=EPOCH, step_minutes=1.0,
    )
    assert "tle_content_hash" in output["element"]
    assert "content_hash_source" in output["element"]
    assert "engine_version" in output["propagator"]


def test_run_propagate_fails_when_norad_unknown(tmp_path: Path) -> None:
    snapshots = TLESnapshotsRepository(tmp_path / "raw")
    elements = OrbitalElementsRepository(tmp_path / "normalized")
    with pytest.raises(OrbitalSentinelError, match="no está en el catálogo"):
        run_propagate(
            snapshots, elements,
            norad_cat_id=99999,
            from_time=EPOCH, to_time=EPOCH + timedelta(hours=1),
            step_minutes=10.0,
        )


def test_run_propagate_rejects_too_many_points(tmp_path: Path) -> None:
    pipeline = _build_real_pipeline(tmp_path)
    pipeline.ingest("stations")
    snapshots = TLESnapshotsRepository(tmp_path / "raw")
    elements = OrbitalElementsRepository(tmp_path / "normalized")
    with pytest.raises(ValueError, match="máximo"):
        run_propagate(
            snapshots, elements,
            norad_cat_id=25544,
            from_time=EPOCH,
            to_time=EPOCH + timedelta(days=365),
            step_minutes=0.1,  # ~5_256_000 puntos
        )


def test_run_propagate_rejects_negative_step(tmp_path: Path) -> None:
    snapshots = TLESnapshotsRepository(tmp_path / "raw")
    elements = OrbitalElementsRepository(tmp_path / "normalized")
    with pytest.raises(ValueError, match="positivo"):
        run_propagate(
            snapshots, elements,
            norad_cat_id=25544,
            from_time=EPOCH, to_time=EPOCH + timedelta(hours=1),
            step_minutes=-1.0,
        )


def test_run_propagate_rejects_inverted_window(tmp_path: Path) -> None:
    snapshots = TLESnapshotsRepository(tmp_path / "raw")
    elements = OrbitalElementsRepository(tmp_path / "normalized")
    with pytest.raises(ValueError, match="--to debe ser"):
        run_propagate(
            snapshots, elements,
            norad_cat_id=25544,
            from_time=EPOCH + timedelta(hours=1),
            to_time=EPOCH,
            step_minutes=10.0,
        )


# --- _serialize_ephemeris -------------------------------------------------


def test_serialize_ephemeris_is_json_compatible(tmp_path: Path) -> None:
    pipeline = _build_real_pipeline(tmp_path)
    pipeline.ingest("stations")
    snapshots = TLESnapshotsRepository(tmp_path / "raw")
    elements = OrbitalElementsRepository(tmp_path / "normalized")
    element = elements.find_latest_by_norad_id(25544)
    assert element is not None
    snapshot = snapshots.get(element.content_hash_source)
    assert snapshot is not None

    from orbital_sentinel.propagation import Sgp4Propagator

    [ephem] = Sgp4Propagator().propagate(element, snapshot, [EPOCH])
    payload = _serialize_ephemeris(ephem)
    json.dumps(payload)  # debe no lanzar


# --- main() end-to-end con argv -----------------------------------------


def test_main_missing_required_arg_exits_2(tmp_path: Path, capsys) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["ingest"])
    assert exc.value.code == 2


def test_main_propagate_norad_unknown_returns_1(
    tmp_path: Path, capsys
) -> None:
    rc = main(
        [
            "propagate",
            "99999",
            "--from",
            "2008-09-20T12:00:00Z",
            "--to",
            "2008-09-20T13:00:00Z",
            "--step",
            "10",
            "--raw-root",
            str(tmp_path / "raw"),
            "--normalized-root",
            str(tmp_path / "normalized"),
        ]
    )
    assert rc == 1
    captured = capsys.readouterr()
    err = json.loads(captured.err)
    assert err["error"] == "OrbitalSentinelError"


def test_main_ingest_with_injected_pipeline(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    """Sustituimos `_make_ingest_pipeline` para inyectar FakeTransport sin red."""

    def fake_make(args):
        return _build_real_pipeline(tmp_path)

    monkeypatch.setattr(cli_module, "_make_ingest_pipeline", fake_make)
    rc = main(
        [
            "ingest",
            "stations",
            "--cache-root",
            str(tmp_path / "cache"),
            "--raw-root",
            str(tmp_path / "raw"),
            "--normalized-root",
            str(tmp_path / "normalized"),
        ]
    )
    assert rc == 0
    captured = capsys.readouterr()
    out = json.loads(captured.out)
    assert out["dataset"] == "stations"
    assert out["snapshot_written"] is True


def test_main_plot_groundtrack_end_to_end(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    """ingest → plot-groundtrack produce un PNG válido."""

    def fake_make(args):
        return _build_real_pipeline(tmp_path)

    monkeypatch.setattr(cli_module, "_make_ingest_pipeline", fake_make)
    main(
        [
            "ingest", "stations",
            "--cache-root", str(tmp_path / "cache"),
            "--raw-root", str(tmp_path / "raw"),
            "--normalized-root", str(tmp_path / "normalized"),
        ]
    )
    capsys.readouterr()

    out_png = tmp_path / "iss_track.png"
    rc = main(
        [
            "plot-groundtrack",
            "25544",
            "--from", "2008-09-20T12:25:40Z",
            "--to", "2008-09-20T13:35:40Z",
            "--step", "5",
            "--output", str(out_png),
            "--raw-root", str(tmp_path / "raw"),
            "--normalized-root", str(tmp_path / "normalized"),
        ]
    )
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["norad_cat_id"] == 25544
    assert out["n_points"] == 15  # 0..70 minutos / 5 = 15 pasos inclusivos
    assert "uncertainty_note" in out
    assert out_png.exists()
    assert out_png.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")


def test_main_conjunction_end_to_end(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    """ingest multi-TLE → conjunction(ISS, GEO) produce JSON con provenance doble."""
    multi_fixture = (
        Path(__file__).resolve().parent.parent
        / "fixtures"
        / "tle"
        / "multi_stations.txt"
    ).read_bytes()

    def fake_make(args):
        return _build_real_pipeline(tmp_path, payload=multi_fixture)

    monkeypatch.setattr(cli_module, "_make_ingest_pipeline", fake_make)
    main(
        [
            "ingest", "stations",
            "--cache-root", str(tmp_path / "cache"),
            "--raw-root", str(tmp_path / "raw"),
            "--normalized-root", str(tmp_path / "normalized"),
        ]
    )
    capsys.readouterr()

    rc = main(
        [
            "conjunction",
            "25544", "99999",
            "--from", "2008-09-20T12:25:40Z",
            "--to", "2008-09-20T13:25:40Z",
            "--step", "5",
            "--raw-root", str(tmp_path / "raw"),
            "--normalized-root", str(tmp_path / "normalized"),
        ]
    )
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["norad_a"] == 25544
    assert out["norad_b"] == 99999
    assert "miss_distance_km" in out
    assert out["miss_distance_km"] > 30000  # LEO vs GEO
    assert "sgp4_uncertainty_baseline_km" in out
    assert "tca_resolution_minutes" in out
    assert out["tca_resolution_minutes"] == 5.0
    # Provenance doble
    assert "element_a_content_hash_source" in out
    assert "element_b_content_hash_source" in out


def test_main_screen_end_to_end(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    """ingest multi-TLE → screen ISS+GEO con threshold 1000 km.

    ISS LEO vs GEO 99999 → 1 par total, filtrado por apogee/perigee, 0 detections.
    """
    multi_fixture = (
        Path(__file__).resolve().parent.parent
        / "fixtures"
        / "tle"
        / "multi_stations.txt"
    ).read_bytes()

    def fake_make(args):
        return _build_real_pipeline(tmp_path, payload=multi_fixture)

    monkeypatch.setattr(cli_module, "_make_ingest_pipeline", fake_make)
    main(
        [
            "ingest", "stations",
            "--cache-root", str(tmp_path / "cache"),
            "--raw-root", str(tmp_path / "raw"),
            "--normalized-root", str(tmp_path / "normalized"),
        ]
    )
    capsys.readouterr()

    rc = main(
        [
            "screen",
            "--norad-ids", "25544,99999",
            "--from", "2008-09-20T12:25:40Z",
            "--to", "2008-09-20T14:25:40Z",
            "--step", "10",
            "--threshold-km", "1000",
            "--raw-root", str(tmp_path / "raw"),
            "--normalized-root", str(tmp_path / "normalized"),
        ]
    )
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["n_objects"] == 2
    assert out["n_pairs_total"] == 1
    assert out["n_pairs_filtered_out"] == 1
    assert out["n_pairs_screened"] == 0
    assert out["n_detections"] == 0
    assert out["apogee_perigee_filter_enabled"] is True
    assert "schema_version" in out
    assert "engine_version" in out


def test_main_screen_no_filter_analyzes_pair(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    """Con --no-apogee-perigee-filter el par LEO-vs-GEO se analiza igualmente."""
    multi_fixture = (
        Path(__file__).resolve().parent.parent
        / "fixtures"
        / "tle"
        / "multi_stations.txt"
    ).read_bytes()

    def fake_make(args):
        return _build_real_pipeline(tmp_path, payload=multi_fixture)

    monkeypatch.setattr(cli_module, "_make_ingest_pipeline", fake_make)
    main(
        [
            "ingest", "stations",
            "--cache-root", str(tmp_path / "cache"),
            "--raw-root", str(tmp_path / "raw"),
            "--normalized-root", str(tmp_path / "normalized"),
        ]
    )
    capsys.readouterr()

    rc = main(
        [
            "screen",
            "--norad-ids", "25544,99999",
            "--from", "2008-09-20T12:25:40Z",
            "--to", "2008-09-20T13:25:40Z",
            "--step", "10",
            "--threshold-km", "1000",
            "--no-apogee-perigee-filter",
            "--raw-root", str(tmp_path / "raw"),
            "--normalized-root", str(tmp_path / "normalized"),
        ]
    )
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["n_pairs_filtered_out"] == 0
    assert out["n_pairs_screened"] == 1
    assert out["n_detections"] == 0  # miss > 30 000 km > threshold 1000


def test_main_screen_rejects_duplicate_norad_ids(
    tmp_path: Path, capsys
) -> None:
    """_parse_norad_id_list rechaza duplicados → argparse hace sys.exit(2)."""
    with pytest.raises(SystemExit) as exc:
        main(
            [
                "screen",
                "--norad-ids", "25544,25544",
                "--from", "2008-09-20T12:25:40Z",
                "--to", "2008-09-20T12:35:40Z",
                "--step", "2",
                "--threshold-km", "1",
                "--raw-root", str(tmp_path / "raw"),
                "--normalized-root", str(tmp_path / "normalized"),
            ]
        )
    assert exc.value.code == 2


def test_main_screen_persist_and_list_detections(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    """Flujo completo: ingest → screen --persist → detections.

    Con ISS vs GEO 99999 y threshold suficientemente alto para detectar.
    """
    multi_fixture = (
        Path(__file__).resolve().parent.parent
        / "fixtures"
        / "tle"
        / "multi_stations.txt"
    ).read_bytes()

    def fake_make(args):
        return _build_real_pipeline(tmp_path, payload=multi_fixture)

    monkeypatch.setattr(cli_module, "_make_ingest_pipeline", fake_make)
    main(
        [
            "ingest", "stations",
            "--cache-root", str(tmp_path / "cache"),
            "--raw-root", str(tmp_path / "raw"),
            "--normalized-root", str(tmp_path / "normalized"),
        ]
    )
    capsys.readouterr()

    # Threshold 40 000 km cubre la separación LEO-GEO (~35 000 km)
    rc = main(
        [
            "screen",
            "--norad-ids", "25544,99999",
            "--from", "2008-09-20T12:25:40Z",
            "--to", "2008-09-20T14:25:40Z",
            "--step", "10",
            "--threshold-km", "40000",
            "--no-apogee-perigee-filter",
            "--persist",
            "--raw-root", str(tmp_path / "raw"),
            "--normalized-root", str(tmp_path / "normalized"),
            "--detections-root", str(tmp_path / "detections"),
        ]
    )
    assert rc == 0
    screen_out = json.loads(capsys.readouterr().out)
    assert screen_out["n_detections"] == 1
    assert screen_out["n_persisted"] == 1

    # Re-correr screen → idempotente, 0 nuevos persistidos
    rc2 = main(
        [
            "screen",
            "--norad-ids", "25544,99999",
            "--from", "2008-09-20T12:25:40Z",
            "--to", "2008-09-20T14:25:40Z",
            "--step", "10",
            "--threshold-km", "40000",
            "--no-apogee-perigee-filter",
            "--persist",
            "--raw-root", str(tmp_path / "raw"),
            "--normalized-root", str(tmp_path / "normalized"),
            "--detections-root", str(tmp_path / "detections"),
        ]
    )
    assert rc2 == 0
    screen_out2 = json.loads(capsys.readouterr().out)
    assert screen_out2["n_detections"] == 1
    assert screen_out2["n_persisted"] == 0  # idempotencia

    # detections --norad 25544 lista la detección persistida
    rc3 = main(
        [
            "detections",
            "--norad", "25544",
            "--detections-root", str(tmp_path / "detections"),
        ]
    )
    assert rc3 == 0
    det_out = json.loads(capsys.readouterr().out)
    assert det_out["n_total"] == 1
    assert det_out["n_returned"] == 1
    assert det_out["filter_norad"] == 25544
    assert len(det_out["detections"]) == 1
    persisted = det_out["detections"][0]
    assert persisted["norad_a"] in (25544, 99999)
    assert persisted["norad_b"] in (25544, 99999)
    assert "detection_content_hash" in persisted
    assert "persistence_schema_version" in persisted


def test_main_propagate_end_to_end(tmp_path: Path, capsys, monkeypatch) -> None:
    """Ingestar primero (con monkeypatch) y luego propagar (sin red)."""

    def fake_make(args):
        return _build_real_pipeline(tmp_path)

    monkeypatch.setattr(cli_module, "_make_ingest_pipeline", fake_make)
    # Ingesta
    rc1 = main(
        [
            "ingest",
            "stations",
            "--cache-root",
            str(tmp_path / "cache"),
            "--raw-root",
            str(tmp_path / "raw"),
            "--normalized-root",
            str(tmp_path / "normalized"),
        ]
    )
    assert rc1 == 0
    capsys.readouterr()  # vaciar buffer

    # Propagar
    rc2 = main(
        [
            "propagate",
            "25544",
            "--from",
            "2008-09-20T12:25:40Z",
            "--to",
            "2008-09-20T12:35:40Z",
            "--step",
            "5",
            "--raw-root",
            str(tmp_path / "raw"),
            "--normalized-root",
            str(tmp_path / "normalized"),
        ]
    )
    assert rc2 == 0
    out = json.loads(capsys.readouterr().out)
    assert out["norad_cat_id"] == 25544
    assert out["n_points"] == 3
