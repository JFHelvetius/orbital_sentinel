"""Demo end-to-end del ciclo completo Fase 1 + Fase 2.

Sin red (FakeTransport sobre el fixture canónico de tests). Sin persistencia en
el repo (trabaja sobre un ``tempfile.TemporaryDirectory`` que se borra al salir).

Ejecutar::

    python -m demo.v0_walkthrough

Muestra los seis pasos del ciclo arquitectónico:

1. Ingesta CelesTrak → Raw → Normalized.
2. Propagación SGP4 → Ephemeris (in-memory, ADR-0006 enmienda 1).
3. Groundtrack 2D estático → PNG (ADR-0008 / matplotlib extras).
4. Pairwise conjunction con Pc + 7 assumption fields (ADR-0020).
5. Screening N-to-N con ``--persist`` (primera Derived persistente, ADR-0019).
6. Listing de detecciones persistidas (idempotencia content-addressable).

Este script **no es código de producción**: no se cubre con tests y no debe
importarse desde ``src/``. Es la carta de presentación operacional del
proyecto post-Fase 2.
"""

from __future__ import annotations

import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from orbital_sentinel.catalog import (
    OrbitalElementsRepository,
    TLESnapshotsRepository,
)
from orbital_sentinel.ingestion.sources import CelesTrakSource, FetchCache
from orbital_sentinel.orchestration import IngestPipeline
from orbital_sentinel.orchestration.cli import (
    run_conjunction,
    run_detections,
    run_propagate,
    run_screen,
)
from orbital_sentinel.orchestration.groundtrack import plot_groundtrack
from orbital_sentinel.propagation import Sgp4Propagator

MULTI_TLE_FIXTURE = (
    Path(__file__).resolve().parent.parent
    / "tests"
    / "fixtures"
    / "tle"
    / "multi_stations.txt"
)

EPOCH = datetime(2008, 9, 20, 12, 25, 40, tzinfo=timezone.utc)


class FakeTransport:
    """Sin red. Devuelve los mismos bytes para cualquier URL solicitada."""

    def __init__(self, response: bytes) -> None:
        self._response = response

    def get(
        self, url: str, *, headers: dict[str, str], timeout: float = 30.0
    ) -> bytes:
        return self._response


def banner(title: str) -> None:
    print()
    print("=" * 70)
    print(f"  {title}")
    print("=" * 70)


def step(n: int, title: str) -> None:
    banner(f"Step {n} -- {title}")


def main() -> int:
    if not MULTI_TLE_FIXTURE.exists():
        print(f"Fixture no encontrado: {MULTI_TLE_FIXTURE}", file=sys.stderr)
        return 1
    fixture_bytes = MULTI_TLE_FIXTURE.read_bytes()

    with tempfile.TemporaryDirectory(prefix="orbital_sentinel_v0_") as tmp:
        workspace = Path(tmp)

        banner("Orbital Sentinel v0 -- End-to-end walkthrough")
        print(f"  Workspace temp : {workspace}")
        print(f"  Fixture        : {MULTI_TLE_FIXTURE.name}  ({len(fixture_bytes)} bytes)")
        print("  El workspace y sus contenidos se borran al salir.")

        cache_root = workspace / "cache"
        raw_root = workspace / "raw"
        normalized_root = workspace / "normalized"
        det_root = workspace / "detections"
        png_path = workspace / "iss_groundtrack.png"

        # --- Step 1: Ingest ----------------------------------------------
        step(1, "Ingesta CelesTrak (sin red)")

        cache = FetchCache(cache_root)
        source = CelesTrakSource(cache=cache, transport=FakeTransport(fixture_bytes))
        snapshots = TLESnapshotsRepository(raw_root)
        elements = OrbitalElementsRepository(normalized_root)

        pipeline = IngestPipeline(
            source=source, snapshots=snapshots, elements=elements
        )
        ingest_result = pipeline.ingest("stations")
        print(f"  snapshot_written : {ingest_result.snapshot_written}")
        print(f"  elements_written : {ingest_result.elements_written}")
        print(f"  content_hash     : {ingest_result.artifact.content_hash[:24]}...")
        print()
        print(f"  Raw count        : {snapshots.count()}")
        print(f"  Normalized count : {elements.count()}")

        # --- Step 2: Propagate -------------------------------------------
        step(2, "Propagacion SGP4 -- ISS (NORAD 25544), 30 min desde epoch")

        out_prop = run_propagate(
            snapshots, elements,
            norad_cat_id=25544,
            from_time=EPOCH,
            to_time=EPOCH + timedelta(minutes=30),
            step_minutes=5.0,
        )
        print(f"  n_points           : {out_prop['n_points']}")
        print(f"  propagator engine  : {out_prop['propagator']['engine_version']}")
        print(f"  element epoch      : {out_prop['element']['epoch_datetime']}")
        first = out_prop["ephemerides"][0]
        print(f"  primer ephemeris   : t = {first['evaluation_time']}")
        print(
            "    position_teme_km : "
            f"[{first['position_teme_km'][0]:.2f}, "
            f"{first['position_teme_km'][1]:.2f}, "
            f"{first['position_teme_km'][2]:.2f}]"
        )
        print(
            "    velocity_teme    : "
            f"[{first['velocity_teme_km_s'][0]:.4f}, "
            f"{first['velocity_teme_km_s'][1]:.4f}, "
            f"{first['velocity_teme_km_s'][2]:.4f}]"
        )

        # --- Step 3: Groundtrack -----------------------------------------
        step(3, "Groundtrack 2D estatico -> PNG")

        element = elements.find_latest_by_norad_id(25544)
        assert element is not None
        snapshot = snapshots.get(element.content_hash_source)
        assert snapshot is not None
        propagator = Sgp4Propagator()
        # 50 puntos cada 2 min = ~100 minutos = ~ una orbita ISS
        times = [EPOCH + timedelta(minutes=i * 2) for i in range(50)]
        ephem = propagator.propagate(element, snapshot, times)
        plot_groundtrack(ephem, png_path, title="ISS 100-min groundtrack")
        png_size = png_path.stat().st_size
        print(f"  PNG path     : {png_path}")
        print(f"  PNG size     : {png_size:,} bytes")

        # --- Step 4: Pairwise conjunction --------------------------------
        step(4, "Pairwise conjunction -- ISS vs synthetic GEO 99999 con Pc")

        out_conj = run_conjunction(
            snapshots, elements,
            norad_a=25544,
            norad_b=99999,
            window_start=EPOCH,
            window_end=EPOCH + timedelta(hours=2),
            step_minutes=10.0,
            combined_hard_body_radius_km=0.010,  # 10 m combinados
        )
        print(f"  miss_distance_km          : {out_conj['miss_distance_km']:.3f}")
        print(f"  relative_velocity_km_s    : {out_conj['relative_velocity_km_s']:.3f}")
        print(f"  tca                       : {out_conj['tca']}")
        print(f"  tca_was_refined           : {out_conj['tca_was_refined']}")
        print(f"  tca_resolution_minutes    : {out_conj['tca_resolution_minutes']:.6f}")
        print()
        print("  --- Pc + assumption fields (ADR-0020) ---")
        print(f"  pc                        : {out_conj['pc']:.3e}")
        print(f"  combined_hard_body_radius : {out_conj['combined_hard_body_radius_km']:.4f} km")
        print(f"  combined_sigma_at_tca_km  : {out_conj['combined_sigma_at_tca_km']:.3f}")
        print(f"  covariance_model_name     : {out_conj['covariance_model_name']}")
        print(f"  covariance_baseline_sigma : {out_conj['covariance_baseline_sigma_km']:.3f}")
        print(f"  covariance_growth_per_day : {out_conj['covariance_growth_sigma_km_per_day']:.3f}")
        print(f"  pc_method                 : {out_conj['pc_method']}")
        print(f"  engine_version            : {out_conj['engine_version']}")

        # --- Step 5: Screen with persist ---------------------------------
        step(5, "Screening N-to-N con --persist (primera Derived persistida)")

        out_screen = run_screen(
            snapshots, elements,
            norad_ids=[25544, 99999],
            window_start=EPOCH,
            window_end=EPOCH + timedelta(hours=2),
            step_minutes=10.0,
            threshold_km=40000.0,
            apogee_perigee_filter=False,
            combined_hard_body_radius_km=0.010,
            persist=True,
            detections_root=det_root,
        )
        print(f"  n_objects               : {out_screen['n_objects']}")
        print(f"  n_pairs_total           : {out_screen['n_pairs_total']}")
        print(f"  n_pairs_filtered_out    : {out_screen['n_pairs_filtered_out']}")
        print(f"  n_pairs_screened        : {out_screen['n_pairs_screened']}")
        print(f"  n_detections            : {out_screen['n_detections']}")
        print(f"  n_persisted             : {out_screen['n_persisted']}")

        out_screen2 = run_screen(
            snapshots, elements,
            norad_ids=[25544, 99999],
            window_start=EPOCH,
            window_end=EPOCH + timedelta(hours=2),
            step_minutes=10.0,
            threshold_km=40000.0,
            apogee_perigee_filter=False,
            combined_hard_body_radius_km=0.010,
            persist=True,
            detections_root=det_root,
        )
        print(
            f"  segundo run n_persisted : {out_screen2['n_persisted']}   "
            "(esperado 0, idempotencia ADR-0019)"
        )

        # --- Step 6: List detections -------------------------------------
        step(6, "detections --norad 25544")

        out_det = run_detections(detections_root=det_root, norad=25544, limit=10)
        print(f"  n_total      : {out_det['n_total']}")
        print(f"  n_returned   : {out_det['n_returned']}")
        if out_det["detections"]:
            d = out_det["detections"][0]
            print()
            print("  Primera deteccion persistida:")
            print(f"    detection_content_hash : {d['detection_content_hash'][:24]}...")
            print(f"    norad_a / norad_b      : {d['norad_a']} / {d['norad_b']}")
            print(f"    miss_distance_km       : {d['miss_distance_km']:.3f}")
            print(f"    pc                     : {d['pc']:.3e}")
            print(f"    tca                    : {d['tca']}")
            print()
            print("  Triple versionado por fila (ADR-0010 en produccion):")
            print(f"    persistence_schema_version : {d['persistence_schema_version']}")
            print(f"    analysis_schema_version    : {d['analysis_schema_version']}")
            print(f"    analysis_engine_version    : {d['analysis_engine_version']}")

        # --- Summary -----------------------------------------------------
        banner("Ciclo completo Raw -> Normalized -> Derived demostrado")
        print("  Fase 1 -- ingesta + SGP4 + visualizacion           [OK]")
        print("  Fase 2 -- pairwise + screening + persist + Pc      [OK]")
        print()
        print("  Workspace temp:", workspace)
        print("  (se borra al salir)")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
