"""CLI de Orbital Sentinel.

Expone los pipelines implementados como subcomandos de ``argparse``. La lista
autoritativa de subcomandos vive en ``_build_parser``.

Diseño deliberadamente acotado (anti-scope-creep):

* Solo argparse de la stdlib (cero dependencias nuevas).
* Solo JSON a stdout (sin formato texto, sin colores, sin tablas).
* Sin config file (todo por flags).
* Sin telemetría, sin shell completion, sin progress bars.
* Cap duro de ``MAX_PROPAGATION_POINTS`` para evitar generar millones de
  efemérides por accidente.

Posicionamiento arquitectónico: ADR-0002 enmienda 1 autoriza módulos en
``orchestration/`` a importar de cualquier plano porque son workflows de
composición. La CLI es eso por definición.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from orbital_sentinel import __version__
from orbital_sentinel.catalog import (
    OrbitalElementsRepository,
    TLESnapshotsRepository,
)
from orbital_sentinel.core.errors import OrbitalSentinelError
from orbital_sentinel.ingestion.sources import CelesTrakSource, FetchCache
from orbital_sentinel.orchestration.ingest_pipeline import (
    IngestPipeline,
    IngestResult,
)
from orbital_sentinel.propagation import Ephemeris, Sgp4Propagator

DEFAULT_DATA_ROOT = Path("data")
MAX_PROPAGATION_POINTS = 100_000
"""Tope duro: rechazamos ventanas que produzcan más puntos que esto."""


# --- Entry points --------------------------------------------------------


def main(argv: Sequence[str] | None = None) -> int:
    """Punto de entrada testeable. Devuelve exit code; no llama ``sys.exit``."""
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        rc: int = args.func(args)
        return rc
    except OrbitalSentinelError as exc:
        _emit_error(str(exc), type(exc).__name__)
        return 1
    except ValueError as exc:
        _emit_error(str(exc), "ValueError")
        return 2


def cli_entry_point() -> None:
    """Entry point para ``[project.scripts]`` en pyproject.toml."""
    sys.exit(main())


# --- Parser construction --------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="orbital-sentinel",
        description="Orbital Sentinel CLI v0",
    )
    parser.add_argument(
        "--version", action="version", version=f"orbital-sentinel {__version__}"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_ingest = sub.add_parser(
        "ingest",
        help=(
            "Ingesta TLEs desde CelesTrak: fetch + persist Raw + normalize + "
            "persist Normalized."
        ),
    )
    p_ingest.add_argument(
        "dataset",
        help="CelesTrak GROUP (e.g. 'stations', 'active') o 'catnr-<id>'.",
    )
    _add_data_root_flags(p_ingest, include_cache=True)
    p_ingest.set_defaults(func=_cmd_ingest)

    p_prop = sub.add_parser(
        "propagate",
        help="Propaga el último TLE de un NORAD ID en una ventana temporal.",
    )
    p_prop.add_argument("norad_id", type=int, help="Número de catálogo NORAD.")
    p_prop.add_argument(
        "--from",
        dest="from_time",
        required=True,
        type=_parse_iso_datetime,
        metavar="ISO_UTC",
        help="Inicio de ventana (ISO 8601 UTC, e.g. 2008-09-20T12:00:00Z).",
    )
    p_prop.add_argument(
        "--to",
        dest="to_time",
        required=True,
        type=_parse_iso_datetime,
        metavar="ISO_UTC",
        help="Fin de ventana (ISO 8601 UTC, inclusivo).",
    )
    p_prop.add_argument(
        "--step",
        dest="step_minutes",
        required=True,
        type=float,
        metavar="MINUTES",
        help="Paso en minutos (positivo, puede ser fraccional).",
    )
    _add_data_root_flags(p_prop, include_cache=False)
    p_prop.set_defaults(func=_cmd_propagate)

    p_plot = sub.add_parser(
        "plot-groundtrack",
        help="Renderiza un PNG del groundtrack del último TLE de un NORAD ID.",
    )
    p_plot.add_argument("norad_id", type=int, help="Número de catálogo NORAD.")
    p_plot.add_argument(
        "--from",
        dest="from_time",
        required=True,
        type=_parse_iso_datetime,
        metavar="ISO_UTC",
        help="Inicio de ventana (ISO 8601 UTC).",
    )
    p_plot.add_argument(
        "--to",
        dest="to_time",
        required=True,
        type=_parse_iso_datetime,
        metavar="ISO_UTC",
        help="Fin de ventana (ISO 8601 UTC, inclusivo).",
    )
    p_plot.add_argument(
        "--step",
        dest="step_minutes",
        required=True,
        type=float,
        metavar="MINUTES",
        help="Paso en minutos.",
    )
    p_plot.add_argument(
        "--output",
        dest="output_path",
        required=True,
        type=Path,
        metavar="PATH",
        help="Ruta del PNG de salida.",
    )
    _add_data_root_flags(p_plot, include_cache=False)
    p_plot.set_defaults(func=_cmd_plot_groundtrack)

    p_conj = sub.add_parser(
        "conjunction",
        help="Análisis pairwise de conjunción entre dos NORAD IDs (ADR-0016 v0.1).",
    )
    p_conj.add_argument("norad_a", type=int, help="NORAD ID del objeto A.")
    p_conj.add_argument("norad_b", type=int, help="NORAD ID del objeto B.")
    p_conj.add_argument(
        "--from",
        dest="from_time",
        required=True,
        type=_parse_iso_datetime,
        metavar="ISO_UTC",
        help="Inicio de ventana (ISO 8601 UTC).",
    )
    p_conj.add_argument(
        "--to",
        dest="to_time",
        required=True,
        type=_parse_iso_datetime,
        metavar="ISO_UTC",
        help="Fin de ventana (ISO 8601 UTC, inclusivo).",
    )
    p_conj.add_argument(
        "--step",
        dest="step_minutes",
        required=True,
        type=float,
        metavar="MINUTES",
        help="Paso de la grid uniforme en minutos.",
    )
    p_conj.add_argument(
        "--combined-radius-km",
        dest="combined_hard_body_radius_km",
        type=float,
        default=0.0,
        metavar="KM",
        help=(
            "Suma de radios físicos para Pc (ADR-0020). Default 0 = Pc=0. "
            "El caller debe declarar este valor para obtener Pc significativo."
        ),
    )
    _add_data_root_flags(p_conj, include_cache=False)
    p_conj.set_defaults(func=_cmd_conjunction)

    p_screen = sub.add_parser(
        "screen",
        help="N-to-N pairwise screening con filtro apogeo/perigeo (ADR-0018 v0.3).",
    )
    p_screen.add_argument(
        "--norad-ids",
        dest="norad_ids",
        required=True,
        type=_parse_norad_id_list,
        metavar="ID,ID,...",
        help="Lista de NORAD IDs separados por comas.",
    )
    p_screen.add_argument(
        "--from",
        dest="from_time",
        required=True,
        type=_parse_iso_datetime,
        metavar="ISO_UTC",
        help="Inicio de ventana (ISO 8601 UTC).",
    )
    p_screen.add_argument(
        "--to",
        dest="to_time",
        required=True,
        type=_parse_iso_datetime,
        metavar="ISO_UTC",
        help="Fin de ventana (ISO 8601 UTC, inclusivo).",
    )
    p_screen.add_argument(
        "--step",
        dest="step_minutes",
        required=True,
        type=float,
        metavar="MINUTES",
        help="Paso de la grid uniforme en minutos.",
    )
    p_screen.add_argument(
        "--threshold-km",
        dest="threshold_km",
        required=True,
        type=float,
        metavar="KM",
        help="Detección si miss_distance_km < threshold_km.",
    )
    p_screen.add_argument(
        "--no-apogee-perigee-filter",
        dest="apogee_perigee_filter",
        action="store_false",
        help="Desactiva el filtro previo apogeo/perigeo (analiza todos los pares).",
    )
    p_screen.add_argument(
        "--max-pairs",
        dest="max_pairs",
        type=int,
        default=None,
        metavar="N",
        help="Cap defensivo sobre n*(n-1)/2 (default 5000).",
    )
    p_screen.add_argument(
        "--combined-radius-km",
        dest="combined_hard_body_radius_km",
        type=float,
        default=0.0,
        metavar="KM",
        help=(
            "Suma de radios físicos aplicado a todas las detecciones del run "
            "(ADR-0020). Default 0 = Pc=0."
        ),
    )
    p_screen.add_argument(
        "--persist",
        dest="persist",
        action="store_true",
        help="Persiste las detecciones en data/derived/conjunctions (ADR-0019).",
    )
    p_screen.add_argument(
        "--detections-root",
        dest="detections_root",
        type=Path,
        default=DEFAULT_DATA_ROOT / "derived" / "conjunctions",
        help="Directorio de detecciones persistidas (default: data/derived/conjunctions).",
    )
    _add_data_root_flags(p_screen, include_cache=False)
    p_screen.set_defaults(func=_cmd_screen)

    p_passes = sub.add_parser(
        "passes",
        help="Predicción de pases visibles de un satélite (ADR-0023 v0.1).",
    )
    p_passes.add_argument("norad_id", type=int, help="Número de catálogo NORAD.")
    p_passes.add_argument(
        "--observer",
        dest="observer",
        required=True,
        type=_parse_observer,
        metavar="LAT,LON,ALT_M",
        help="Observador como 'lat_deg,lon_deg,alt_m' (e.g. '19.4326,-99.1332,2240').",
    )
    p_passes.add_argument(
        "--from",
        dest="from_time",
        required=True,
        type=_parse_iso_datetime,
        metavar="ISO_UTC",
        help="Inicio de ventana (ISO 8601 UTC).",
    )
    p_passes.add_argument(
        "--to",
        dest="to_time",
        required=True,
        type=_parse_iso_datetime,
        metavar="ISO_UTC",
        help="Fin de ventana (ISO 8601 UTC, inclusivo).",
    )
    p_passes.add_argument(
        "--step",
        dest="step_minutes",
        required=True,
        type=float,
        metavar="MINUTES",
        help="Paso de la grid uniforme en minutos.",
    )
    p_passes.add_argument(
        "--min-elevation",
        dest="min_elevation_deg",
        type=float,
        default=0.0,
        metavar="DEG",
        help="Umbral de visibilidad en grados (default 0.0).",
    )
    p_passes.add_argument(
        "--aos-los-tolerance",
        dest="aos_los_tolerance_seconds",
        type=float,
        default=1.0,
        metavar="SECONDS",
        help="Tolerancia de bisección AOS/LOS en segundos (default 1.0).",
    )
    _add_data_root_flags(p_passes, include_cache=False)
    p_passes.set_defaults(func=_cmd_passes)

    p_scan = sub.add_parser(
        "scan",
        help="Escanea pases de varios satélites (ADR-0025 v0.1).",
    )
    p_scan.add_argument(
        "--observer", required=True, type=_parse_observer, metavar="LAT,LON,ALT_M",
    )
    p_scan.add_argument(
        "--norad-ids", dest="norad_ids", required=True, type=_parse_norad_id_list,
        metavar="ID,ID,...",
    )
    p_scan.add_argument(
        "--from", dest="from_time", required=True, type=_parse_iso_datetime,
        metavar="ISO_UTC",
    )
    p_scan.add_argument(
        "--to", dest="to_time", required=True, type=_parse_iso_datetime,
        metavar="ISO_UTC",
    )
    p_scan.add_argument(
        "--step", dest="step_minutes", required=True, type=float, metavar="MINUTES",
    )
    p_scan.add_argument(
        "--min-elevation", dest="min_elevation_deg", type=float, default=10.0,
        metavar="DEG",
    )
    p_scan.add_argument(
        "--require-twilight", dest="require_twilight", type=str, default=None,
        choices=["civil", "nautical", "astronomical", "night"],
    )
    p_scan.add_argument(
        "--require-illuminated", dest="require_illuminated", action="store_true",
    )
    p_scan.add_argument(
        "--max-satellites", dest="max_satellites", type=int, default=5000,
    )
    _add_data_root_flags(p_scan, include_cache=False)
    p_scan.set_defaults(func=_cmd_scan)

    p_best = sub.add_parser(
        "best",
        help="Ranking de pases (ADR-0025 v0.1).",
    )
    for parser_arg in (p_best,):
        parser_arg.add_argument(
            "--observer", required=True, type=_parse_observer, metavar="LAT,LON,ALT_M",
        )
        parser_arg.add_argument(
            "--norad-ids", dest="norad_ids", required=True,
            type=_parse_norad_id_list, metavar="ID,ID,...",
        )
        parser_arg.add_argument(
            "--from", dest="from_time", required=True,
            type=_parse_iso_datetime, metavar="ISO_UTC",
        )
        parser_arg.add_argument(
            "--to", dest="to_time", required=True,
            type=_parse_iso_datetime, metavar="ISO_UTC",
        )
        parser_arg.add_argument(
            "--step", dest="step_minutes", required=True, type=float,
            metavar="MINUTES",
        )
        parser_arg.add_argument(
            "--min-elevation", dest="min_elevation_deg", type=float, default=10.0,
        )
        parser_arg.add_argument(
            "--require-twilight", dest="require_twilight", type=str, default=None,
            choices=["civil", "nautical", "astronomical", "night"],
        )
        parser_arg.add_argument(
            "--require-illuminated", dest="require_illuminated", action="store_true",
        )
        parser_arg.add_argument(
            "--max-satellites", dest="max_satellites", type=int, default=5000,
        )
    p_best.add_argument(
        "--criterion", required=True,
        choices=["max_elevation", "duration", "earliest", "latest"],
    )
    p_best.add_argument("--limit", type=int, default=None)
    _add_data_root_flags(p_best, include_cache=False)
    p_best.set_defaults(func=_cmd_best)

    p_conflicts = sub.add_parser(
        "conflicts",
        help="Detecta conflictos de pases simultáneos (ADR-0025 v0.1).",
    )
    p_conflicts.add_argument(
        "--observer", required=True, type=_parse_observer, metavar="LAT,LON,ALT_M",
    )
    p_conflicts.add_argument(
        "--norad-ids", dest="norad_ids", required=True,
        type=_parse_norad_id_list, metavar="ID,ID,...",
    )
    p_conflicts.add_argument(
        "--from", dest="from_time", required=True,
        type=_parse_iso_datetime, metavar="ISO_UTC",
    )
    p_conflicts.add_argument(
        "--to", dest="to_time", required=True,
        type=_parse_iso_datetime, metavar="ISO_UTC",
    )
    p_conflicts.add_argument(
        "--step", dest="step_minutes", required=True, type=float, metavar="MINUTES",
    )
    p_conflicts.add_argument(
        "--min-elevation", dest="min_elevation_deg", type=float, default=10.0,
    )
    p_conflicts.add_argument(
        "--overlap-threshold-seconds", dest="overlap_threshold_seconds",
        type=float, default=0.0,
    )
    p_conflicts.add_argument(
        "--max-satellites", dest="max_satellites", type=int, default=5000,
    )
    _add_data_root_flags(p_conflicts, include_cache=False)
    p_conflicts.set_defaults(func=_cmd_conflicts)

    p_man = sub.add_parser(
        "maneuvers",
        help="Detección de maniobras aparentes (ADR-0027 v0.1).",
    )
    p_man.add_argument("norad_id", type=int, help="NORAD ID del objeto.")
    p_man.add_argument(
        "--baseline-days",
        dest="baseline_window_days", type=float, default=14.0, metavar="DAYS",
        help="Ventana baseline en días (default 14.0).",
    )
    p_man.add_argument(
        "--threshold-sigma",
        dest="detection_threshold_sigma", type=float, default=3.0, metavar="SIGMA",
        help="Umbral de detección en σ (default 3.0).",
    )
    p_man.add_argument(
        "--min-baseline-samples",
        dest="min_baseline_samples", type=int, default=5, metavar="N",
        help="Mínimo de muestras en baseline (default 5).",
    )
    p_man.add_argument(
        "--engine-version",
        dest="engine_version", type=str, default=None, metavar="X.Y.Z",
        help="Filtra por engine_version del normalizador (default: mezcla).",
    )
    _add_data_root_flags(p_man, include_cache=False)
    p_man.set_defaults(func=_cmd_maneuvers)

    p_anom = sub.add_parser(
        "anomalies",
        help="Detección de desviaciones observacionales (ADR-0028 v0.1).",
    )
    p_anom.add_argument("norad_id", type=int, help="NORAD ID del objeto.")
    p_anom.add_argument(
        "--baseline-days",
        dest="baseline_window_days", type=float, default=14.0, metavar="DAYS",
    )
    p_anom.add_argument(
        "--threshold-sigma",
        dest="threshold_sigma", type=float, default=3.0, metavar="SIGMA",
    )
    p_anom.add_argument(
        "--min-baseline-samples",
        dest="min_baseline_samples", type=int, default=5, metavar="N",
    )
    p_anom.add_argument(
        "--engine-version",
        dest="engine_version", type=str, default=None, metavar="X.Y.Z",
        help="Filtra OrbitalElements por engine_version del normalizador.",
    )
    _add_data_root_flags(p_anom, include_cache=False)
    p_anom.set_defaults(func=_cmd_anomalies)

    p_evd = sub.add_parser(
        "evidence",
        help="Consolida evidencia detectada para un NORAD (ADR-0029 v0.1).",
    )
    p_evd.add_argument("norad_id", type=int, help="NORAD ID del objeto.")
    p_evd.add_argument(
        "--from", dest="from_time", type=_parse_iso_datetime, default=None,
        metavar="ISO_UTC",
        help="Filtro inferior por event_epoch.",
    )
    p_evd.add_argument(
        "--to", dest="to_time", type=_parse_iso_datetime, default=None,
        metavar="ISO_UTC",
        help="Filtro superior por event_epoch.",
    )
    p_evd.add_argument(
        "--detector", dest="detector_filter", type=str, default=None,
        choices=["maneuver", "anomaly", "conjunction"],
        help="Limita el catálogo a un detector. Default: todos.",
    )
    p_evd.add_argument(
        "--baseline-days", dest="baseline_window_days",
        type=float, default=14.0, metavar="DAYS",
    )
    p_evd.add_argument(
        "--threshold-sigma", dest="threshold_sigma",
        type=float, default=3.0, metavar="SIGMA",
    )
    p_evd.add_argument(
        "--min-baseline-samples", dest="min_baseline_samples",
        type=int, default=5, metavar="N",
    )
    p_evd.add_argument(
        "--engine-version", dest="engine_version",
        type=str, default=None, metavar="X.Y.Z",
    )
    p_evd.add_argument(
        "--detections-root", dest="detections_root",
        type=Path, default=DEFAULT_DATA_ROOT / "derived" / "conjunctions",
        metavar="PATH",
    )
    _add_data_root_flags(p_evd, include_cache=False)
    p_evd.set_defaults(func=_cmd_evidence)

    p_ctx = sub.add_parser(
        "context",
        help="Explanation context estructurado del catálogo de evidencia (ADR-0030 v0.1).",
    )
    p_ctx.add_argument("norad_id", type=int, help="NORAD ID del objeto.")
    p_ctx.add_argument(
        "--from", dest="from_time", type=_parse_iso_datetime, default=None,
        metavar="ISO_UTC",
    )
    p_ctx.add_argument(
        "--to", dest="to_time", type=_parse_iso_datetime, default=None,
        metavar="ISO_UTC",
    )
    p_ctx.add_argument(
        "--detector", dest="detector_filter", type=str, default=None,
        choices=["maneuver", "anomaly", "conjunction"],
    )
    p_ctx.add_argument(
        "--baseline-days", dest="baseline_window_days",
        type=float, default=14.0, metavar="DAYS",
    )
    p_ctx.add_argument(
        "--threshold-sigma", dest="threshold_sigma",
        type=float, default=3.0, metavar="SIGMA",
    )
    p_ctx.add_argument(
        "--min-baseline-samples", dest="min_baseline_samples",
        type=int, default=5, metavar="N",
    )
    p_ctx.add_argument(
        "--engine-version", dest="engine_version",
        type=str, default=None, metavar="X.Y.Z",
    )
    p_ctx.add_argument(
        "--detections-root", dest="detections_root",
        type=Path, default=DEFAULT_DATA_ROOT / "derived" / "conjunctions",
        metavar="PATH",
    )
    _add_data_root_flags(p_ctx, include_cache=False)
    p_ctx.set_defaults(func=_cmd_context)

    p_bdl = sub.add_parser(
        "bundle",
        help="Genera Evidence Bundle autocontenido y verificable (ADR-0031 v0.1).",
    )
    p_bdl.add_argument("norad_id", type=int, help="NORAD ID del objeto.")
    p_bdl.add_argument(
        "--from", dest="from_time", type=_parse_iso_datetime, default=None,
        metavar="ISO_UTC",
    )
    p_bdl.add_argument(
        "--to", dest="to_time", type=_parse_iso_datetime, default=None,
        metavar="ISO_UTC",
    )
    p_bdl.add_argument(
        "--detector", dest="detector_filter", type=str, default=None,
        choices=["maneuver", "anomaly", "conjunction"],
    )
    p_bdl.add_argument(
        "--baseline-days", dest="baseline_window_days",
        type=float, default=14.0, metavar="DAYS",
    )
    p_bdl.add_argument(
        "--threshold-sigma", dest="threshold_sigma",
        type=float, default=3.0, metavar="SIGMA",
    )
    p_bdl.add_argument(
        "--min-baseline-samples", dest="min_baseline_samples",
        type=int, default=5, metavar="N",
    )
    p_bdl.add_argument(
        "--engine-version", dest="engine_version",
        type=str, default=None, metavar="X.Y.Z",
    )
    p_bdl.add_argument(
        "--detections-root", dest="detections_root",
        type=Path, default=DEFAULT_DATA_ROOT / "derived" / "conjunctions",
        metavar="PATH",
    )
    _add_data_root_flags(p_bdl, include_cache=False)
    p_bdl.set_defaults(func=_cmd_bundle)

    p_vrf = sub.add_parser(
        "verify-bundle",
        help="Verifica integridad de un Evidence Bundle (ADR-0031 v0.1).",
    )
    p_vrf.add_argument(
        "bundle_file", type=str,
        help="Ruta al bundle JSON (usa '-' para stdin).",
    )
    p_vrf.add_argument(
        "--strict", dest="strict", action="store_true",
        help="Exit 1 si is_valid=False (default: exit 0 con reporte).",
    )
    p_vrf.set_defaults(func=_cmd_verify_bundle)

    p_ain = sub.add_parser(
        "agent-input",
        help="Construye AgentInput desde un bundle verificado (ADR-0032 v0.1).",
    )
    p_ain.add_argument(
        "bundle_file", type=str,
        help="Ruta al bundle JSON (usa '-' para stdin).",
    )
    p_ain.add_argument(
        "--consumer-class", dest="consumer_class", required=True,
        choices=[
            "explanation_agent_v01",
            "report_exporter_v01",
            "external_third_party_v01",
            "api_endpoint_v01",
            "audit_consumer_v01",
        ],
    )
    p_ain.set_defaults(func=_cmd_agent_input)

    p_exp = sub.add_parser(
        "explain",
        help="Genera ExplanationArtifact deterministico desde un AgentInput (ADR-0033 v0.1).",
    )
    p_exp.add_argument(
        "agent_input_file", type=str,
        help="Ruta al AgentInput JSON (usa '-' para stdin).",
    )
    p_exp.set_defaults(func=_cmd_explain)

    p_vex = sub.add_parser(
        "verify-explanation",
        help="Verifica un ExplanationArtifact contra su AgentInput (ADR-0034 v0.1).",
    )
    p_vex.add_argument(
        "artifact_file", type=str,
        help="Ruta al ExplanationArtifact JSON (usa '-' para stdin).",
    )
    p_vex.add_argument(
        "--agent-input-file", dest="agent_input_file", required=True,
        type=str, metavar="PATH",
        help="Ruta al AgentInput JSON (no se admite stdin aquí).",
    )
    p_vex.add_argument(
        "--strict", dest="strict", action="store_true",
        help="Exit 1 si is_valid=False (default: exit 0 con reporte).",
    )
    p_vex.set_defaults(func=_cmd_verify_explanation)

    p_clr = sub.add_parser(
        "claim-registry",
        help="Construye ClaimRegistry desde ExplanationArtifact + AgentInput (ADR-0035 v0.1).",
    )
    p_clr.add_argument(
        "artifact_file", type=str,
        help="Ruta al ExplanationArtifact JSON (usa '-' para stdin).",
    )
    p_clr.add_argument(
        "--agent-input-file", dest="agent_input_file", required=True,
        type=str, metavar="PATH",
        help="Ruta al AgentInput JSON (no se admite stdin aquí).",
    )
    p_clr.set_defaults(func=_cmd_claim_registry)

    p_vcr = sub.add_parser(
        "verify-claim-registry",
        help="Verifica un ClaimRegistry contra ExplanationArtifact + AgentInput (ADR-0035 v0.1).",
    )
    p_vcr.add_argument(
        "registry_file", type=str,
        help="Ruta al ClaimRegistry JSON (usa '-' para stdin).",
    )
    p_vcr.add_argument(
        "--agent-input-file", dest="agent_input_file", required=True,
        type=str, metavar="PATH",
        help="Ruta al AgentInput JSON (no se admite stdin aquí).",
    )
    p_vcr.add_argument(
        "--explanation-artifact-file", dest="artifact_file", required=True,
        type=str, metavar="PATH",
        help="Ruta al ExplanationArtifact JSON (no se admite stdin aquí).",
    )
    p_vcr.add_argument(
        "--strict", dest="strict", action="store_true",
        help="Exit 1 si is_valid=False (default: exit 0 con reporte).",
    )
    p_vcr.set_defaults(func=_cmd_verify_claim_registry)

    p_hyp = sub.add_parser(
        "hypothesis-registry",
        help="Construye HypothesisRegistry desde ClaimRegistry + AgentInput (ADR-0036 v1).",
    )
    p_hyp.add_argument(
        "claim_registry_file", type=str,
        help="Ruta al ClaimRegistry JSON (usa '-' para stdin).",
    )
    p_hyp.add_argument(
        "--agent-input-file", dest="agent_input_file", required=True,
        type=str, metavar="PATH",
        help="Ruta al AgentInput JSON.",
    )
    p_hyp.set_defaults(func=_cmd_hypothesis_registry)

    p_vhr = sub.add_parser(
        "verify-hypothesis-registry",
        help="Verifica un HypothesisRegistry contra ClaimRegistry + AgentInput (ADR-0036 v1).",
    )
    p_vhr.add_argument(
        "hypothesis_registry_file", type=str,
        help="Ruta al HypothesisRegistry JSON (usa '-' para stdin).",
    )
    p_vhr.add_argument(
        "--claim-registry-file", dest="claim_registry_file", required=True,
        type=str, metavar="PATH",
        help="Ruta al ClaimRegistry JSON.",
    )
    p_vhr.add_argument(
        "--agent-input-file", dest="agent_input_file", required=True,
        type=str, metavar="PATH",
        help="Ruta al AgentInput JSON.",
    )
    p_vhr.add_argument(
        "--strict", dest="strict", action="store_true",
        help="Exit 1 si is_valid=False.",
    )
    p_vhr.set_defaults(func=_cmd_verify_hypothesis_registry)

    p_ech = sub.add_parser(
        "evidence-chain",
        help="Construye EvidenceChain desde HypothesisRegistry + cadena (ADR-0037 v1).",
    )
    p_ech.add_argument(
        "hypothesis_registry_file", type=str,
        help="Ruta al HypothesisRegistry JSON (usa '-' para stdin).",
    )
    p_ech.add_argument(
        "--claim-registry-file", dest="claim_registry_file", required=True,
        type=str, metavar="PATH", help="Ruta al ClaimRegistry JSON.",
    )
    p_ech.add_argument(
        "--explanation-artifact-file", dest="artifact_file", required=True,
        type=str, metavar="PATH", help="Ruta al ExplanationArtifact JSON.",
    )
    p_ech.add_argument(
        "--agent-input-file", dest="agent_input_file", required=True,
        type=str, metavar="PATH", help="Ruta al AgentInput JSON.",
    )
    p_ech.set_defaults(func=_cmd_evidence_chain)

    p_vec = sub.add_parser(
        "verify-evidence-chain",
        help="Verifica un EvidenceChain contra los seis artefactos en cadena (ADR-0037 v1).",
    )
    p_vec.add_argument(
        "chain_file", type=str,
        help="Ruta al EvidenceChain JSON (usa '-' para stdin).",
    )
    p_vec.add_argument(
        "--hypothesis-registry-file", dest="hypothesis_registry_file", required=True,
        type=str, metavar="PATH", help="Ruta al HypothesisRegistry JSON.",
    )
    p_vec.add_argument(
        "--claim-registry-file", dest="claim_registry_file", required=True,
        type=str, metavar="PATH", help="Ruta al ClaimRegistry JSON.",
    )
    p_vec.add_argument(
        "--explanation-artifact-file", dest="artifact_file", required=True,
        type=str, metavar="PATH", help="Ruta al ExplanationArtifact JSON.",
    )
    p_vec.add_argument(
        "--agent-input-file", dest="agent_input_file", required=True,
        type=str, metavar="PATH", help="Ruta al AgentInput JSON.",
    )
    p_vec.add_argument(
        "--strict", dest="strict", action="store_true",
        help="Exit 1 si is_valid=False.",
    )
    p_vec.set_defaults(func=_cmd_verify_evidence_chain)

    p_ic = sub.add_parser(
        "investigation-case",
        help="Empaqueta una investigación completa portable (ADR-0038 v1).",
    )
    p_ic.add_argument(
        "chain_file", type=str,
        help="Ruta al EvidenceChain JSON (usa '-' para stdin).",
    )
    p_ic.add_argument(
        "--hypothesis-registry-file", dest="hypothesis_registry_file", required=True,
        type=str, metavar="PATH", help="Ruta al HypothesisRegistry JSON.",
    )
    p_ic.add_argument(
        "--claim-registry-file", dest="claim_registry_file", required=True,
        type=str, metavar="PATH", help="Ruta al ClaimRegistry JSON.",
    )
    p_ic.add_argument(
        "--explanation-artifact-file", dest="artifact_file", required=True,
        type=str, metavar="PATH", help="Ruta al ExplanationArtifact JSON.",
    )
    p_ic.add_argument(
        "--agent-input-file", dest="agent_input_file", required=True,
        type=str, metavar="PATH", help="Ruta al AgentInput JSON.",
    )
    p_ic.add_argument(
        "--bundle-file", dest="bundle_file", required=True,
        type=str, metavar="PATH", help="Ruta al EvidenceBundle JSON.",
    )
    p_ic.set_defaults(func=_cmd_investigation_case)

    p_vic = sub.add_parser(
        "verify-investigation-case",
        help="Verifica un InvestigationCase autocontenido (ADR-0038 v1).",
    )
    p_vic.add_argument(
        "case_file", type=str,
        help="Ruta al InvestigationCase JSON (usa '-' para stdin).",
    )
    p_vic.add_argument(
        "--strict", dest="strict", action="store_true",
        help="Exit 1 si is_valid=False.",
    )
    p_vic.set_defaults(func=_cmd_verify_investigation_case)

    p_rev = sub.add_parser(
        "revoke-artifact",
        help="Emite RevocationLedger con una revocación atómica (ADR-0039 v1).",
    )
    p_rev.add_argument(
        "--target-artifact-type", dest="target_artifact_type", required=True,
        choices=[
            "evidence_bundle", "agent_input", "explanation_artifact",
            "claim_registry", "hypothesis_registry", "evidence_chain",
            "investigation_case",
        ],
    )
    p_rev.add_argument(
        "--target-artifact-id", dest="target_artifact_id", required=True, type=str,
    )
    p_rev.add_argument(
        "--target-artifact-signature", dest="target_artifact_signature",
        required=True, type=str,
    )
    p_rev.add_argument(
        "--reason", dest="revocation_reason", required=True,
        choices=[
            "superseded_by_corrected_upstream", "retracted_by_emitter",
            "integrity_violation_discovered", "schema_obsolete",
            "voluntary_withdrawal",
        ],
    )
    p_rev.add_argument(
        "--superseding-artifact-id", dest="superseding_artifact_id",
        type=str, default="",
    )
    p_rev.add_argument(
        "--supporting-evidence-id", dest="supporting_evidence_ids",
        type=str, action="append", default=[],
        help="Puede repetirse. Cada uno es un evidence_id que justifica la revocación.",
    )
    p_rev.set_defaults(func=_cmd_revoke_artifact)

    p_vrev = sub.add_parser(
        "verify-revocation-ledger",
        help="Verifica un RevocationLedger autocontenido (ADR-0039 v1).",
    )
    p_vrev.add_argument(
        "ledger_file", type=str,
        help="Ruta al RevocationLedger JSON (usa '-' para stdin).",
    )
    p_vrev.add_argument(
        "--strict", dest="strict", action="store_true",
        help="Exit 1 si is_valid=False.",
    )
    p_vrev.set_defaults(func=_cmd_verify_revocation_ledger)

    p_src = sub.add_parser(
        "external-source-registry",
        help="Construye ExternalSourceRegistry desde bundle + records JSON (ADR-0040 v1).",
    )
    p_src.add_argument(
        "bundle_file", type=str,
        help="Ruta al EvidenceBundle JSON (usa '-' para stdin).",
    )
    p_src.add_argument(
        "--records-file", dest="records_file", required=True, type=str,
        metavar="PATH",
        help=(
            "JSON con {'records': [ExternalSourceRecord...], "
            "'evidence_to_source_record_mapping': {evidence_id: [src_id...]}}."
        ),
    )
    p_src.set_defaults(func=_cmd_external_source_registry)

    p_srcd = sub.add_parser(
        "external-source-registry-from-repos",
        help=(
            "Deriva ExternalSourceRegistry desde catalog persistido (Raw + "
            "Normalized) sin records manuales (ADR-0042 v1)."
        ),
    )
    p_srcd.add_argument(
        "bundle_file", type=str,
        help="Ruta al EvidenceBundle JSON (usa '-' para stdin).",
    )
    p_srcd.add_argument(
        "--raw-root", dest="raw_root", required=True, type=Path,
        metavar="PATH",
        help="Directorio de la capa Raw (tle_snapshots).",
    )
    p_srcd.add_argument(
        "--normalized-root", dest="normalized_root", required=True, type=Path,
        metavar="PATH",
        help="Directorio de la capa Normalized (orbital_elements).",
    )
    p_srcd.set_defaults(func=_cmd_external_source_registry_from_repos)

    p_vsrc = sub.add_parser(
        "verify-external-source-registry",
        help="Verifica ExternalSourceRegistry contra su bundle (ADR-0040 v1).",
    )
    p_vsrc.add_argument(
        "registry_file", type=str,
        help="Ruta al ExternalSourceRegistry JSON (usa '-' para stdin).",
    )
    p_vsrc.add_argument(
        "--bundle-file", dest="bundle_file", required=True, type=str,
        metavar="PATH", help="Ruta al EvidenceBundle JSON.",
    )
    p_vsrc.add_argument(
        "--strict", dest="strict", action="store_true",
        help="Exit 1 si is_valid=False.",
    )
    p_vsrc.set_defaults(func=_cmd_verify_external_source_registry)

    p_dis = sub.add_parser(
        "dissent-record",
        help="Emite un DissentRecord JSON (ADR-0041 v1).",
    )
    p_dis.add_argument(
        "--target-case-id", dest="target_case_id", required=True, type=str,
    )
    p_dis.add_argument(
        "--target-case-signature", dest="target_case_signature",
        required=True, type=str,
    )
    p_dis.add_argument(
        "--dissent-index", dest="dissent_index", required=True, type=int,
    )
    p_dis.add_argument(
        "--dissent-type", dest="dissent_type", required=True,
        choices=[
            "factual_correction", "alternative_explanation",
            "missing_evidence", "methodological_objection",
            "scope_disagreement",
        ],
    )
    p_dis.add_argument(
        "--basis-evidence-id", dest="dissent_basis_evidence_ids",
        type=str, action="append", default=[],
        help="Puede repetirse. Cada uno es un evidence_id que sustenta la disensión.",
    )
    p_dis.add_argument(
        "--referenced-alternative-case-id", dest="referenced_alternative_case_id",
        type=str, default="",
    )
    p_dis.set_defaults(func=_cmd_dissent_record)

    p_dl = sub.add_parser(
        "dissent-ledger",
        help="Empaqueta DissentRecords en un DissentLedger autocontenido (ADR-0041 v1).",
    )
    p_dl.add_argument(
        "--target-case-id", dest="target_case_id", required=True, type=str,
    )
    p_dl.add_argument(
        "--target-case-signature", dest="target_case_signature",
        required=True, type=str,
    )
    p_dl.add_argument(
        "--record-file", dest="record_files", type=str, action="append",
        default=[], metavar="PATH",
        help="Puede repetirse. Cada PATH es un DissentRecord JSON.",
    )
    p_dl.set_defaults(func=_cmd_dissent_ledger)

    p_vdl = sub.add_parser(
        "verify-dissent-ledger",
        help="Verifica un DissentLedger autocontenido (ADR-0041 v1).",
    )
    p_vdl.add_argument(
        "ledger_file", type=str,
        help="Ruta al DissentLedger JSON (usa '-' para stdin).",
    )
    p_vdl.add_argument(
        "--strict", dest="strict", action="store_true",
        help="Exit 1 si is_valid=False.",
    )
    p_vdl.set_defaults(func=_cmd_verify_dissent_ledger)

    p_sv = sub.add_parser(
        "self-verify",
        help=(
            "Verifica que esta instalación produce los hashes canónicos frozen "
            "(ADR-0013 enmienda 2). Cero argumentos. Salida JSON."
        ),
    )
    p_sv.add_argument(
        "--strict", dest="strict", action="store_true",
        help="Exit 1 si la instalación no produce los hashes canónicos.",
    )
    p_sv.set_defaults(func=_cmd_self_verify)

    p_det = sub.add_parser(
        "detections",
        help="Lista detecciones persistidas (ADR-0019 v0.4).",
    )
    p_det.add_argument(
        "--norad",
        dest="norad",
        type=int,
        default=None,
        help="Filtra por NORAD (cualquier lado, A o B).",
    )
    p_det.add_argument(
        "--limit",
        dest="limit",
        type=int,
        default=100,
        help="Máximo de detecciones devueltas (default 100).",
    )
    p_det.add_argument(
        "--detections-root",
        dest="detections_root",
        type=Path,
        default=DEFAULT_DATA_ROOT / "derived" / "conjunctions",
        help="Directorio de detecciones persistidas.",
    )
    p_det.set_defaults(func=_cmd_detections)

    return parser


def _parse_observer(s: str) -> tuple[float, float, float]:
    """Parsea 'lat_deg,lon_deg,alt_m' a una tupla de floats."""
    parts = [p.strip() for p in s.split(",")]
    if len(parts) != 3:
        raise ValueError(
            f"--observer debe ser 'lat_deg,lon_deg,alt_m'; recibido: {s!r}"
        )
    try:
        lat, lon, alt = (float(p) for p in parts)
    except ValueError as exc:
        raise ValueError(
            f"--observer componentes deben ser floats: {exc}"
        ) from exc
    return lat, lon, alt


def _parse_norad_id_list(s: str) -> list[int]:
    parts = [p.strip() for p in s.split(",") if p.strip()]
    if not parts:
        raise ValueError("--norad-ids vacía.")
    try:
        ids = [int(p) for p in parts]
    except ValueError as exc:
        raise ValueError(
            f"--norad-ids debe ser lista de enteros separados por comas: {exc}"
        ) from exc
    if len(ids) != len(set(ids)):
        raise ValueError("--norad-ids no debe contener duplicados.")
    return ids


def _add_data_root_flags(p: argparse.ArgumentParser, *, include_cache: bool) -> None:
    if include_cache:
        p.add_argument(
            "--cache-root",
            type=Path,
            default=DEFAULT_DATA_ROOT / "cache",
            help="Directorio del cache de fetch (default: data/cache).",
        )
    p.add_argument(
        "--raw-root",
        type=Path,
        default=DEFAULT_DATA_ROOT / "raw",
        help="Directorio de la capa Raw (default: data/raw).",
    )
    p.add_argument(
        "--normalized-root",
        type=Path,
        default=DEFAULT_DATA_ROOT / "normalized",
        help="Directorio de la capa Normalized (default: data/normalized).",
    )


def _parse_iso_datetime(s: str) -> datetime:
    """Parsea ISO 8601 con tz obligatoria. Acepta 'Z' como '+00:00'."""
    s_norm = s.replace("Z", "+00:00") if s.endswith("Z") else s
    try:
        dt = datetime.fromisoformat(s_norm)
    except ValueError as exc:
        raise ValueError(f"Timestamp ISO 8601 inválido: {s!r} ({exc})") from exc
    if dt.tzinfo is None:
        raise ValueError(
            f"Timestamp {s!r} debe ser timezone-aware (usar 'Z' o '+HH:MM')."
        )
    return dt.astimezone(timezone.utc)


# --- ingest ---------------------------------------------------------------


def _cmd_ingest(args: argparse.Namespace) -> int:
    pipeline = _make_ingest_pipeline(args)
    result = pipeline.ingest(args.dataset)
    output = _serialize_ingest(result)
    json.dump(output, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


def _make_ingest_pipeline(args: argparse.Namespace) -> IngestPipeline:
    cache = FetchCache(args.cache_root)
    source = CelesTrakSource(cache=cache)
    snapshots = TLESnapshotsRepository(args.raw_root)
    elements = OrbitalElementsRepository(args.normalized_root)
    return IngestPipeline(source=source, snapshots=snapshots, elements=elements)


def _serialize_ingest(result: IngestResult) -> dict[str, Any]:
    return {
        "dataset": result.artifact.dataset,
        "url": result.artifact.url,
        "fetched_at": result.artifact.fetched_at.isoformat(),
        "snapshot_content_hash": result.artifact.content_hash,
        "snapshot_written": result.snapshot_written,
        "elements_written": result.elements_written,
        "is_new": result.is_new,
    }


# --- propagate ------------------------------------------------------------


def _cmd_propagate(args: argparse.Namespace) -> int:
    snapshots = TLESnapshotsRepository(args.raw_root)
    elements = OrbitalElementsRepository(args.normalized_root)
    output = run_propagate(
        snapshots,
        elements,
        norad_cat_id=args.norad_id,
        from_time=args.from_time,
        to_time=args.to_time,
        step_minutes=args.step_minutes,
    )
    json.dump(output, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


def _propagate_norad_id(
    snapshots: TLESnapshotsRepository,
    elements: OrbitalElementsRepository,
    *,
    norad_cat_id: int,
    from_time: datetime,
    to_time: datetime,
    step_minutes: float,
) -> tuple[Any, Any, list[Ephemeris], Sgp4Propagator]:
    """Helper compartido por `propagate` y `plot-groundtrack`.

    Localiza el último element del NORAD ID, recupera el snapshot, valida la
    ventana y propaga. Devuelve ``(element, snapshot, ephemerides, propagator)``.
    """
    if step_minutes <= 0:
        raise ValueError("--step debe ser positivo.")
    if to_time < from_time:
        raise ValueError("--to debe ser >= --from.")

    element = elements.find_latest_by_norad_id(norad_cat_id)
    if element is None:
        raise OrbitalSentinelError(
            f"NORAD {norad_cat_id} no está en el catálogo Normalized. "
            f"Ingesta un dataset que lo contenga antes de propagar."
        )

    snapshot = snapshots.get(element.content_hash_source)
    if snapshot is None:
        raise OrbitalSentinelError(
            f"OrbitalElement de NORAD {norad_cat_id} apunta a un snapshot "
            f"({element.content_hash_source[:12]}...) ausente del catálogo Raw."
        )

    times = _build_time_list(from_time, to_time, step_minutes)
    if len(times) > MAX_PROPAGATION_POINTS:
        raise ValueError(
            f"La ventana solicitada produce {len(times)} puntos "
            f"(máximo {MAX_PROPAGATION_POINTS}). Reduce ventana o aumenta --step."
        )

    propagator = Sgp4Propagator()
    ephemerides = propagator.propagate(element, snapshot, times)
    return element, snapshot, ephemerides, propagator


def run_propagate(
    snapshots: TLESnapshotsRepository,
    elements: OrbitalElementsRepository,
    *,
    norad_cat_id: int,
    from_time: datetime,
    to_time: datetime,
    step_minutes: float,
) -> dict[str, Any]:
    """Núcleo testeable de ``propagate``. Sin I/O de CLI."""
    element, _snapshot, ephemerides, propagator = _propagate_norad_id(
        snapshots, elements,
        norad_cat_id=norad_cat_id,
        from_time=from_time, to_time=to_time, step_minutes=step_minutes,
    )
    return {
        "norad_cat_id": norad_cat_id,
        "element": {
            "tle_content_hash": element.tle_content_hash,
            "epoch_datetime": element.epoch_datetime.isoformat(),
            "engine_version_normalizer": element.engine_version,
            "content_hash_source": element.content_hash_source,
        },
        "propagator": {
            "name": propagator.name,
            "engine_version": propagator.engine_version,
        },
        "n_points": len(ephemerides),
        "ephemerides": [_serialize_ephemeris(e) for e in ephemerides],
    }


def _cmd_plot_groundtrack(args: argparse.Namespace) -> int:
    snapshots = TLESnapshotsRepository(args.raw_root)
    elements = OrbitalElementsRepository(args.normalized_root)
    output = run_plot_groundtrack(
        snapshots,
        elements,
        norad_cat_id=args.norad_id,
        from_time=args.from_time,
        to_time=args.to_time,
        step_minutes=args.step_minutes,
        output_path=args.output_path,
    )
    json.dump(output, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


def run_plot_groundtrack(
    snapshots: TLESnapshotsRepository,
    elements: OrbitalElementsRepository,
    *,
    norad_cat_id: int,
    from_time: datetime,
    to_time: datetime,
    step_minutes: float,
    output_path: Path,
) -> dict[str, Any]:
    """Núcleo testeable de ``plot-groundtrack``. Sin I/O de CLI."""
    from orbital_sentinel.orchestration.groundtrack import (
        UNCERTAINTY_CAPTION,
        plot_groundtrack,
    )

    element, _snapshot, ephemerides, propagator = _propagate_norad_id(
        snapshots, elements,
        norad_cat_id=norad_cat_id,
        from_time=from_time, to_time=to_time, step_minutes=step_minutes,
    )
    title = (
        f"NORAD {norad_cat_id}  "
        f"window {from_time.isoformat()} → {to_time.isoformat()}  "
        f"step {step_minutes}min"
    )
    written = plot_groundtrack(ephemerides, output_path, title=title)
    return {
        "norad_cat_id": norad_cat_id,
        "n_points": len(ephemerides),
        "output_path": str(written),
        "engine_version": propagator.engine_version,
        "element_content_hash_source": element.content_hash_source,
        "uncertainty_note": UNCERTAINTY_CAPTION,
    }


def _cmd_conjunction(args: argparse.Namespace) -> int:
    snapshots = TLESnapshotsRepository(args.raw_root)
    elements = OrbitalElementsRepository(args.normalized_root)
    output = run_conjunction(
        snapshots,
        elements,
        norad_a=args.norad_a,
        norad_b=args.norad_b,
        window_start=args.from_time,
        window_end=args.to_time,
        step_minutes=args.step_minutes,
        combined_hard_body_radius_km=args.combined_hard_body_radius_km,
    )
    json.dump(output, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


def run_conjunction(
    snapshots: TLESnapshotsRepository,
    elements: OrbitalElementsRepository,
    *,
    norad_a: int,
    norad_b: int,
    window_start: datetime,
    window_end: datetime,
    step_minutes: float,
    combined_hard_body_radius_km: float = 0.0,
) -> dict[str, Any]:
    """Núcleo testeable de ``conjunction``. Sin I/O de CLI."""
    from orbital_sentinel.analytics.conjunctions import (
        analyze_pairwise_conjunction,
    )

    element_a = elements.find_latest_by_norad_id(norad_a)
    if element_a is None:
        raise OrbitalSentinelError(
            f"NORAD {norad_a} no está en el catálogo Normalized."
        )
    snapshot_a = snapshots.get(element_a.content_hash_source)
    if snapshot_a is None:
        raise OrbitalSentinelError(
            f"Snapshot Raw de NORAD {norad_a} ausente del catálogo."
        )

    element_b = elements.find_latest_by_norad_id(norad_b)
    if element_b is None:
        raise OrbitalSentinelError(
            f"NORAD {norad_b} no está en el catálogo Normalized."
        )
    snapshot_b = snapshots.get(element_b.content_hash_source)
    if snapshot_b is None:
        raise OrbitalSentinelError(
            f"Snapshot Raw de NORAD {norad_b} ausente del catálogo."
        )

    n_times = max(1, int((window_end - window_start).total_seconds() / (step_minutes * 60)) + 1)
    if n_times > MAX_PROPAGATION_POINTS:
        raise ValueError(
            f"La ventana solicitada produce {n_times} puntos "
            f"(máximo {MAX_PROPAGATION_POINTS}). Reduce ventana o aumenta --step."
        )

    result = analyze_pairwise_conjunction(
        element_a, snapshot_a, element_b, snapshot_b,
        window_start=window_start,
        window_end=window_end,
        step_minutes=step_minutes,
        combined_hard_body_radius_km=combined_hard_body_radius_km,
    )
    return result.model_dump(mode="json")


def _cmd_screen(args: argparse.Namespace) -> int:
    snapshots = TLESnapshotsRepository(args.raw_root)
    elements = OrbitalElementsRepository(args.normalized_root)
    output = run_screen(
        snapshots,
        elements,
        norad_ids=args.norad_ids,
        window_start=args.from_time,
        window_end=args.to_time,
        step_minutes=args.step_minutes,
        threshold_km=args.threshold_km,
        apogee_perigee_filter=args.apogee_perigee_filter,
        combined_hard_body_radius_km=args.combined_hard_body_radius_km,
        max_pairs=args.max_pairs,
        persist=args.persist,
        detections_root=args.detections_root,
    )
    json.dump(output, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


def run_screen(
    snapshots: TLESnapshotsRepository,
    elements: OrbitalElementsRepository,
    *,
    norad_ids: list[int],
    window_start: datetime,
    window_end: datetime,
    step_minutes: float,
    threshold_km: float,
    apogee_perigee_filter: bool = True,
    combined_hard_body_radius_km: float = 0.0,
    max_pairs: int | None = None,
    persist: bool = False,
    detections_root: Path | None = None,
) -> dict[str, Any]:
    """Núcleo testeable de ``screen``. Sin I/O de CLI.

    Si ``persist=True``, cada detección del run se intenta insertar en
    ``ConjunctionDetectionsRepository``. La inserción es idempotente por
    content_hash; el campo ``n_persisted`` cuenta solo las nuevas.
    """
    from orbital_sentinel.analytics.conjunctions import (
        MAX_PAIRS_DEFAULT,
        ConjunctionDetection,
        ConjunctionDetectionsRepository,
        analyze_pairwise_screening,
    )

    pairs: list[tuple[Any, Any]] = []
    for nid in norad_ids:
        element = elements.find_latest_by_norad_id(nid)
        if element is None:
            raise OrbitalSentinelError(
                f"NORAD {nid} no está en el catálogo Normalized."
            )
        snapshot = snapshots.get(element.content_hash_source)
        if snapshot is None:
            raise OrbitalSentinelError(
                f"Snapshot Raw de NORAD {nid} ausente del catálogo."
            )
        pairs.append((element, snapshot))

    effective_max = max_pairs if max_pairs is not None else MAX_PAIRS_DEFAULT
    result = analyze_pairwise_screening(
        pairs,
        window_start=window_start,
        window_end=window_end,
        step_minutes=step_minutes,
        threshold_km=threshold_km,
        apogee_perigee_filter=apogee_perigee_filter,
        combined_hard_body_radius_km=combined_hard_body_radius_km,
        max_pairs=effective_max,
    )
    output = result.model_dump(mode="json")

    if persist:
        det_root = (
            detections_root
            if detections_root is not None
            else Path("data") / "derived" / "conjunctions"
        )
        det_repo = ConjunctionDetectionsRepository(det_root)
        now = datetime.now(timezone.utc)
        detections_to_persist = [
            ConjunctionDetection.from_analysis(a, persisted_at=now)
            for a in result.detections
        ]
        n_persisted = det_repo.insert_many(detections_to_persist)
        output["n_persisted"] = n_persisted
        output["detections_root"] = str(det_root)

    return output


def _cmd_passes(args: argparse.Namespace) -> int:
    snapshots = TLESnapshotsRepository(args.raw_root)
    elements = OrbitalElementsRepository(args.normalized_root)
    observer_lat, observer_lon, observer_alt = args.observer
    output = run_passes(
        snapshots, elements,
        norad_cat_id=args.norad_id,
        observer_lat_deg=observer_lat,
        observer_lon_deg=observer_lon,
        observer_alt_m=observer_alt,
        window_start=args.from_time,
        window_end=args.to_time,
        step_minutes=args.step_minutes,
        min_elevation_deg=args.min_elevation_deg,
        aos_los_tolerance_seconds=args.aos_los_tolerance_seconds,
    )
    json.dump(output, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


def run_passes(
    snapshots: TLESnapshotsRepository,
    elements: OrbitalElementsRepository,
    *,
    norad_cat_id: int,
    observer_lat_deg: float,
    observer_lon_deg: float,
    observer_alt_m: float,
    window_start: datetime,
    window_end: datetime,
    step_minutes: float,
    min_elevation_deg: float = 0.0,
    aos_los_tolerance_seconds: float = 1.0,
) -> dict[str, Any]:
    """Núcleo testeable de ``passes``. Sin I/O de CLI."""
    from orbital_sentinel.analytics.passes import predict_passes

    element = elements.find_latest_by_norad_id(norad_cat_id)
    if element is None:
        raise OrbitalSentinelError(
            f"NORAD {norad_cat_id} no está en el catálogo Normalized."
        )
    snapshot = snapshots.get(element.content_hash_source)
    if snapshot is None:
        raise OrbitalSentinelError(
            f"Snapshot Raw de NORAD {norad_cat_id} ausente del catálogo."
        )
    result = predict_passes(
        element, snapshot,
        observer_lat_deg=observer_lat_deg,
        observer_lon_deg=observer_lon_deg,
        observer_alt_m=observer_alt_m,
        window_start=window_start,
        window_end=window_end,
        step_minutes=step_minutes,
        min_elevation_deg=min_elevation_deg,
        aos_los_tolerance_seconds=aos_los_tolerance_seconds,
    )
    return result.model_dump(mode="json")


def _collect_pairs(
    snapshots: TLESnapshotsRepository,
    elements: OrbitalElementsRepository,
    norad_ids: list[int],
) -> list[tuple[Any, Any]]:
    pairs: list[tuple[Any, Any]] = []
    for nid in norad_ids:
        element = elements.find_latest_by_norad_id(nid)
        if element is None:
            raise OrbitalSentinelError(
                f"NORAD {nid} no está en el catálogo Normalized."
            )
        snapshot = snapshots.get(element.content_hash_source)
        if snapshot is None:
            raise OrbitalSentinelError(
                f"Snapshot Raw de NORAD {nid} ausente del catálogo."
            )
        pairs.append((element, snapshot))
    return pairs


def _make_useful_filter(
    require_twilight: str | None, require_illuminated: bool
) -> Any:  # UsefulPassFilter, lazy import para minimizar acoplamiento
    from orbital_sentinel.analytics.observatory import UsefulPassFilter
    from orbital_sentinel.analytics.solar import TwilightPhase

    if require_twilight is None and not require_illuminated:
        return UsefulPassFilter(
            require_observer_in_twilight_or_darker=False,
            require_satellite_illuminated=False,
        )
    return UsefulPassFilter(
        require_observer_in_twilight_or_darker=require_twilight is not None,
        minimum_twilight_phase=(
            TwilightPhase(require_twilight) if require_twilight else TwilightPhase.CIVIL
        ),
        require_satellite_illuminated=require_illuminated,
    )


def _cmd_scan(args: argparse.Namespace) -> int:
    from orbital_sentinel.analytics.observatory import scan_observatory

    snapshots = TLESnapshotsRepository(args.raw_root)
    elements = OrbitalElementsRepository(args.normalized_root)
    observer_lat, observer_lon, observer_alt = args.observer
    pairs = _collect_pairs(snapshots, elements, args.norad_ids)
    filter_ = _make_useful_filter(args.require_twilight, args.require_illuminated)
    scan = scan_observatory(
        pairs,
        observer_lat_deg=observer_lat,
        observer_lon_deg=observer_lon,
        observer_alt_m=observer_alt,
        window_start=args.from_time,
        window_end=args.to_time,
        step_minutes=args.step_minutes,
        min_elevation_deg=args.min_elevation_deg,
        useful_pass_filter=filter_,
        max_satellites=args.max_satellites,
    )
    json.dump(scan.model_dump(mode="json"), sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


def _cmd_best(args: argparse.Namespace) -> int:
    from orbital_sentinel.analytics.observatory import (
        RankingCriterion,
        rank_passes,
        scan_observatory,
    )

    snapshots = TLESnapshotsRepository(args.raw_root)
    elements = OrbitalElementsRepository(args.normalized_root)
    observer_lat, observer_lon, observer_alt = args.observer
    pairs = _collect_pairs(snapshots, elements, args.norad_ids)
    filter_ = _make_useful_filter(args.require_twilight, args.require_illuminated)
    scan = scan_observatory(
        pairs,
        observer_lat_deg=observer_lat,
        observer_lon_deg=observer_lon,
        observer_alt_m=observer_alt,
        window_start=args.from_time,
        window_end=args.to_time,
        step_minutes=args.step_minutes,
        min_elevation_deg=args.min_elevation_deg,
        useful_pass_filter=filter_,
        max_satellites=args.max_satellites,
    )
    ranked = rank_passes(
        scan, criterion=RankingCriterion(args.criterion), limit=args.limit,
    )
    output = {
        "criterion": args.criterion,
        "n_returned": len(ranked),
        "ranked": [r.model_dump(mode="json", by_alias=True) for r in ranked],
    }
    json.dump(output, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


def _cmd_conflicts(args: argparse.Namespace) -> int:
    from orbital_sentinel.analytics.observatory import (
        detect_pass_conflicts,
        scan_observatory,
    )

    snapshots = TLESnapshotsRepository(args.raw_root)
    elements = OrbitalElementsRepository(args.normalized_root)
    observer_lat, observer_lon, observer_alt = args.observer
    pairs = _collect_pairs(snapshots, elements, args.norad_ids)
    scan = scan_observatory(
        pairs,
        observer_lat_deg=observer_lat,
        observer_lon_deg=observer_lon,
        observer_alt_m=observer_alt,
        window_start=args.from_time,
        window_end=args.to_time,
        step_minutes=args.step_minutes,
        min_elevation_deg=args.min_elevation_deg,
        max_satellites=args.max_satellites,
    )
    conflicts = detect_pass_conflicts(
        scan, overlap_threshold_seconds=args.overlap_threshold_seconds,
    )
    output = {
        "n_conflicts": len(conflicts),
        "conflicts": [c.model_dump(mode="json") for c in conflicts],
    }
    json.dump(output, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


def _cmd_maneuvers(args: argparse.Namespace) -> int:
    from orbital_sentinel.analytics.maneuvers import (
        OrbitalElementSeries,
        detect_maneuvers,
    )

    elements_repo = OrbitalElementsRepository(args.normalized_root)
    elements = elements_repo.find_all_by_norad_id(
        args.norad_id, engine_version=args.engine_version
    )
    if len(elements) < 2:
        raise ValueError(
            f"NORAD {args.norad_id} requiere ≥ 2 OrbitalElements en el "
            f"catálogo para detección de maniobras; encontrados {len(elements)}."
        )
    series = OrbitalElementSeries.from_elements(elements)
    result = detect_maneuvers(
        series,
        baseline_window_days=args.baseline_window_days,
        detection_threshold_sigma=args.detection_threshold_sigma,
        min_baseline_samples=args.min_baseline_samples,
    )
    json.dump(result.model_dump(mode="json"), sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


def _cmd_anomalies(args: argparse.Namespace) -> int:
    from orbital_sentinel.analytics.anomalies import detect_anomalies
    from orbital_sentinel.analytics.maneuvers import OrbitalElementSeries

    elements_repo = OrbitalElementsRepository(args.normalized_root)
    elements = elements_repo.find_all_by_norad_id(
        args.norad_id, engine_version=args.engine_version
    )
    if len(elements) < 2:
        raise ValueError(
            f"NORAD {args.norad_id} requiere ≥ 2 OrbitalElements en el "
            f"catálogo para detección de anomalías; encontrados {len(elements)}."
        )
    series = OrbitalElementSeries.from_elements(elements)
    result = detect_anomalies(
        series,
        baseline_window_days=args.baseline_window_days,
        threshold_sigma=args.threshold_sigma,
        min_baseline_samples=args.min_baseline_samples,
    )
    json.dump(result.model_dump(mode="json"), sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


_DETECTOR_FILTER_MAP = {
    "maneuver": "maneuver_detection_v01",
    "anomaly": "anomaly_detection_v01",
    "conjunction": "conjunction_detection_v01",
}


def _cmd_evidence(args: argparse.Namespace) -> int:
    from orbital_sentinel.analytics.anomalies import detect_anomalies
    from orbital_sentinel.analytics.conjunctions import (
        ConjunctionDetectionsRepository,
    )
    from orbital_sentinel.analytics.evidence import (
        EvidenceCatalog,
        build_anomaly_evidence,
        build_conjunction_evidence,
        build_maneuver_evidence,
    )
    from orbital_sentinel.analytics.maneuvers import (
        OrbitalElementSeries,
        detect_maneuvers,
    )

    elements_repo = OrbitalElementsRepository(args.normalized_root)
    elements = elements_repo.find_all_by_norad_id(
        args.norad_id, engine_version=args.engine_version,
    )

    all_evidence: list[Any] = []

    if len(elements) >= 2:
        series = OrbitalElementSeries.from_elements(elements)
        man_result = detect_maneuvers(
            series,
            baseline_window_days=args.baseline_window_days,
            detection_threshold_sigma=args.threshold_sigma,
            min_baseline_samples=args.min_baseline_samples,
        )
        all_evidence.extend(build_maneuver_evidence(man_result))
        anom_result = detect_anomalies(
            series,
            baseline_window_days=args.baseline_window_days,
            threshold_sigma=args.threshold_sigma,
            min_baseline_samples=args.min_baseline_samples,
        )
        all_evidence.extend(build_anomaly_evidence(anom_result))

    if args.detections_root.exists():
        conj_repo = ConjunctionDetectionsRepository(args.detections_root)
        conj_dets = conj_repo.find_by_norad(args.norad_id)
        all_evidence.extend(
            build_conjunction_evidence(conj_dets, only_for_norad=args.norad_id)
        )

    catalog = EvidenceCatalog.from_evidence(
        all_evidence, derived_at=datetime.now(timezone.utc),
    )

    items = catalog.list_by_norad(args.norad_id)
    if args.detector_filter is not None:
        target = _DETECTOR_FILTER_MAP[args.detector_filter]
        items = [e for e in items if e.source_detector == target]
    if args.from_time is not None:
        items = [e for e in items if e.event_epoch >= args.from_time]
    if args.to_time is not None:
        items = [e for e in items if e.event_epoch <= args.to_time]

    output = {
        "norad_cat_id": args.norad_id,
        "n_evidence_total": catalog.n_evidence,
        "n_evidence_returned": len(items),
        "schema_version": catalog.schema_version,
        "catalog_engine_version": catalog.catalog_engine_version,
        "evidence": [e.model_dump(mode="json") for e in items],
    }
    json.dump(output, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


def _cmd_context(args: argparse.Namespace) -> int:
    from orbital_sentinel.analytics.anomalies import detect_anomalies
    from orbital_sentinel.analytics.conjunctions import (
        ConjunctionDetectionsRepository,
    )
    from orbital_sentinel.analytics.evidence import (
        EvidenceCatalog,
        build_anomaly_evidence,
        build_conjunction_evidence,
        build_maneuver_evidence,
    )
    from orbital_sentinel.analytics.explanation import build_explanation_context
    from orbital_sentinel.analytics.maneuvers import (
        OrbitalElementSeries,
        detect_maneuvers,
    )

    elements_repo = OrbitalElementsRepository(args.normalized_root)
    elements = elements_repo.find_all_by_norad_id(
        args.norad_id, engine_version=args.engine_version,
    )

    all_evidence: list[Any] = []

    if len(elements) >= 2:
        series = OrbitalElementSeries.from_elements(elements)
        man_result = detect_maneuvers(
            series,
            baseline_window_days=args.baseline_window_days,
            detection_threshold_sigma=args.threshold_sigma,
            min_baseline_samples=args.min_baseline_samples,
        )
        all_evidence.extend(build_maneuver_evidence(man_result))
        anom_result = detect_anomalies(
            series,
            baseline_window_days=args.baseline_window_days,
            threshold_sigma=args.threshold_sigma,
            min_baseline_samples=args.min_baseline_samples,
        )
        all_evidence.extend(build_anomaly_evidence(anom_result))

    if args.detections_root.exists():
        conj_repo = ConjunctionDetectionsRepository(args.detections_root)
        conj_dets = conj_repo.find_by_norad(args.norad_id)
        all_evidence.extend(
            build_conjunction_evidence(conj_dets, only_for_norad=args.norad_id)
        )

    # Aplicar filtros opcionales SOBRE LA EVIDENCIA antes de consolidar en
    # catálogo (mantiene determinismo y honora el contrato del subcomando).
    if args.detector_filter is not None:
        target = _DETECTOR_FILTER_MAP[args.detector_filter]
        all_evidence = [e for e in all_evidence if e.source_detector == target]
    if args.from_time is not None:
        all_evidence = [e for e in all_evidence if e.event_epoch >= args.from_time]
    if args.to_time is not None:
        all_evidence = [e for e in all_evidence if e.event_epoch <= args.to_time]

    catalog = EvidenceCatalog.from_evidence(
        all_evidence, derived_at=datetime.now(timezone.utc),
    )
    context = build_explanation_context(catalog, object_id=args.norad_id)
    json.dump(context.model_dump(mode="json"), sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


def _cmd_bundle(args: argparse.Namespace) -> int:
    from orbital_sentinel.analytics.anomalies import detect_anomalies
    from orbital_sentinel.analytics.bundles import build_evidence_bundle
    from orbital_sentinel.analytics.conjunctions import (
        ConjunctionDetectionsRepository,
    )
    from orbital_sentinel.analytics.evidence import (
        EvidenceCatalog,
        build_anomaly_evidence,
        build_conjunction_evidence,
        build_maneuver_evidence,
    )
    from orbital_sentinel.analytics.explanation import build_explanation_context
    from orbital_sentinel.analytics.maneuvers import (
        OrbitalElementSeries,
        detect_maneuvers,
    )

    elements_repo = OrbitalElementsRepository(args.normalized_root)
    elements = elements_repo.find_all_by_norad_id(
        args.norad_id, engine_version=args.engine_version,
    )

    all_evidence: list[Any] = []
    if len(elements) >= 2:
        series = OrbitalElementSeries.from_elements(elements)
        man_result = detect_maneuvers(
            series,
            baseline_window_days=args.baseline_window_days,
            detection_threshold_sigma=args.threshold_sigma,
            min_baseline_samples=args.min_baseline_samples,
        )
        all_evidence.extend(build_maneuver_evidence(man_result))
        anom_result = detect_anomalies(
            series,
            baseline_window_days=args.baseline_window_days,
            threshold_sigma=args.threshold_sigma,
            min_baseline_samples=args.min_baseline_samples,
        )
        all_evidence.extend(build_anomaly_evidence(anom_result))

    if args.detections_root.exists():
        conj_repo = ConjunctionDetectionsRepository(args.detections_root)
        conj_dets = conj_repo.find_by_norad(args.norad_id)
        all_evidence.extend(
            build_conjunction_evidence(conj_dets, only_for_norad=args.norad_id)
        )

    if args.detector_filter is not None:
        target = _DETECTOR_FILTER_MAP[args.detector_filter]
        all_evidence = [e for e in all_evidence if e.source_detector == target]
    if args.from_time is not None:
        all_evidence = [e for e in all_evidence if e.event_epoch >= args.from_time]
    if args.to_time is not None:
        all_evidence = [e for e in all_evidence if e.event_epoch <= args.to_time]

    catalog = EvidenceCatalog.from_evidence(
        all_evidence, derived_at=datetime.now(timezone.utc),
    )
    context = build_explanation_context(catalog, object_id=args.norad_id)
    bundle = build_evidence_bundle(context, catalog)
    json.dump(bundle.model_dump(mode="json"), sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


def _cmd_verify_bundle(args: argparse.Namespace) -> int:
    from orbital_sentinel.analytics.bundles import EvidenceBundle, verify_bundle

    if args.bundle_file == "-":
        raw = sys.stdin.read()
    else:
        raw = Path(args.bundle_file).read_text(encoding="utf-8")
    data = json.loads(raw)
    bundle = EvidenceBundle.model_validate(data)
    report = verify_bundle(bundle)
    json.dump(report.model_dump(mode="json"), sys.stdout, indent=2)
    sys.stdout.write("\n")
    if args.strict and not report.is_valid:
        return 1
    return 0


def _cmd_agent_input(args: argparse.Namespace) -> int:
    from orbital_sentinel.analytics.agent_contract import build_agent_input
    from orbital_sentinel.analytics.bundles import EvidenceBundle
    from orbital_sentinel.core.errors import AgentInputRejectedError

    if args.bundle_file == "-":
        raw = sys.stdin.read()
    else:
        raw = Path(args.bundle_file).read_text(encoding="utf-8")
    data = json.loads(raw)
    bundle = EvidenceBundle.model_validate(data)
    try:
        agent_input = build_agent_input(
            bundle, declared_consumer_class=args.consumer_class,
        )
    except AgentInputRejectedError as exc:
        from orbital_sentinel.analytics.bundles import BundleVerificationReport
        report = exc.verification_report
        assert isinstance(report, BundleVerificationReport)
        sys.stderr.write(json.dumps(report.model_dump(mode="json"), indent=2))
        sys.stderr.write("\n")
        return 1
    json.dump(agent_input.model_dump(mode="json"), sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


def _cmd_explain(args: argparse.Namespace) -> int:
    from orbital_sentinel.analytics.agent_contract import AgentInput
    from orbital_sentinel.analytics.explanation_agent import generate_explanation

    if args.agent_input_file == "-":
        raw = sys.stdin.read()
    else:
        raw = Path(args.agent_input_file).read_text(encoding="utf-8")
    data = json.loads(raw)
    agent_input = AgentInput.model_validate(data)
    artifact = generate_explanation(agent_input)
    json.dump(artifact.model_dump(mode="json"), sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


def _cmd_verify_explanation(args: argparse.Namespace) -> int:
    from orbital_sentinel.analytics.agent_contract import AgentInput
    from orbital_sentinel.analytics.explanation_agent import ExplanationArtifact
    from orbital_sentinel.analytics.explanation_verifier import verify_explanation

    if args.artifact_file == "-":
        artifact_raw = sys.stdin.read()
    else:
        artifact_raw = Path(args.artifact_file).read_text(encoding="utf-8")
    artifact = ExplanationArtifact.model_validate(json.loads(artifact_raw))
    ai_raw = Path(args.agent_input_file).read_text(encoding="utf-8")
    agent_input = AgentInput.model_validate(json.loads(ai_raw))
    report = verify_explanation(artifact, agent_input)
    json.dump(report.model_dump(mode="json"), sys.stdout, indent=2)
    sys.stdout.write("\n")
    if args.strict and not report.is_valid:
        return 1
    return 0


def _cmd_claim_registry(args: argparse.Namespace) -> int:
    from orbital_sentinel.analytics.agent_contract import AgentInput
    from orbital_sentinel.analytics.claims import build_claim_registry
    from orbital_sentinel.analytics.explanation_agent import ExplanationArtifact

    if args.artifact_file == "-":
        artifact_raw = sys.stdin.read()
    else:
        artifact_raw = Path(args.artifact_file).read_text(encoding="utf-8")
    artifact = ExplanationArtifact.model_validate(json.loads(artifact_raw))
    ai_raw = Path(args.agent_input_file).read_text(encoding="utf-8")
    agent_input = AgentInput.model_validate(json.loads(ai_raw))
    registry = build_claim_registry(artifact, agent_input)
    json.dump(registry.model_dump(mode="json"), sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


def _cmd_verify_claim_registry(args: argparse.Namespace) -> int:
    from orbital_sentinel.analytics.agent_contract import AgentInput
    from orbital_sentinel.analytics.claims import (
        ClaimRegistry,
        verify_claim_registry,
    )
    from orbital_sentinel.analytics.explanation_agent import ExplanationArtifact

    if args.registry_file == "-":
        reg_raw = sys.stdin.read()
    else:
        reg_raw = Path(args.registry_file).read_text(encoding="utf-8")
    registry = ClaimRegistry.model_validate(json.loads(reg_raw))
    ai_raw = Path(args.agent_input_file).read_text(encoding="utf-8")
    agent_input = AgentInput.model_validate(json.loads(ai_raw))
    art_raw = Path(args.artifact_file).read_text(encoding="utf-8")
    artifact = ExplanationArtifact.model_validate(json.loads(art_raw))
    report = verify_claim_registry(registry, agent_input, artifact)
    json.dump(report.model_dump(mode="json"), sys.stdout, indent=2)
    sys.stdout.write("\n")
    if args.strict and not report.is_valid:
        return 1
    return 0


def _cmd_hypothesis_registry(args: argparse.Namespace) -> int:
    from orbital_sentinel.analytics.agent_contract import AgentInput
    from orbital_sentinel.analytics.claims import ClaimRegistry
    from orbital_sentinel.analytics.hypotheses import build_hypothesis_registry

    if args.claim_registry_file == "-":
        raw = sys.stdin.read()
    else:
        raw = Path(args.claim_registry_file).read_text(encoding="utf-8")
    claim_registry = ClaimRegistry.model_validate(json.loads(raw))
    ai_raw = Path(args.agent_input_file).read_text(encoding="utf-8")
    agent_input = AgentInput.model_validate(json.loads(ai_raw))
    registry = build_hypothesis_registry(claim_registry, agent_input)
    json.dump(registry.model_dump(mode="json"), sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


def _cmd_verify_hypothesis_registry(args: argparse.Namespace) -> int:
    from orbital_sentinel.analytics.agent_contract import AgentInput
    from orbital_sentinel.analytics.claims import ClaimRegistry
    from orbital_sentinel.analytics.hypotheses import (
        HypothesisRegistry,
        verify_hypothesis_registry,
    )

    if args.hypothesis_registry_file == "-":
        raw = sys.stdin.read()
    else:
        raw = Path(args.hypothesis_registry_file).read_text(encoding="utf-8")
    registry = HypothesisRegistry.model_validate(json.loads(raw))
    cr_raw = Path(args.claim_registry_file).read_text(encoding="utf-8")
    claim_registry = ClaimRegistry.model_validate(json.loads(cr_raw))
    ai_raw = Path(args.agent_input_file).read_text(encoding="utf-8")
    agent_input = AgentInput.model_validate(json.loads(ai_raw))
    report = verify_hypothesis_registry(registry, claim_registry, agent_input)
    json.dump(report.model_dump(mode="json"), sys.stdout, indent=2)
    sys.stdout.write("\n")
    if args.strict and not report.is_valid:
        return 1
    return 0


def _cmd_evidence_chain(args: argparse.Namespace) -> int:
    from orbital_sentinel.analytics.agent_contract import AgentInput
    from orbital_sentinel.analytics.claims import ClaimRegistry
    from orbital_sentinel.analytics.evidence_chains import build_evidence_chain
    from orbital_sentinel.analytics.explanation_agent import ExplanationArtifact
    from orbital_sentinel.analytics.hypotheses import HypothesisRegistry

    if args.hypothesis_registry_file == "-":
        raw = sys.stdin.read()
    else:
        raw = Path(args.hypothesis_registry_file).read_text(encoding="utf-8")
    hyp_registry = HypothesisRegistry.model_validate(json.loads(raw))
    cr_raw = Path(args.claim_registry_file).read_text(encoding="utf-8")
    claim_registry = ClaimRegistry.model_validate(json.loads(cr_raw))
    art_raw = Path(args.artifact_file).read_text(encoding="utf-8")
    artifact = ExplanationArtifact.model_validate(json.loads(art_raw))
    ai_raw = Path(args.agent_input_file).read_text(encoding="utf-8")
    agent_input = AgentInput.model_validate(json.loads(ai_raw))
    chain = build_evidence_chain(hyp_registry, claim_registry, artifact, agent_input)
    json.dump(chain.model_dump(mode="json"), sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


def _cmd_verify_evidence_chain(args: argparse.Namespace) -> int:
    from orbital_sentinel.analytics.agent_contract import AgentInput
    from orbital_sentinel.analytics.claims import ClaimRegistry
    from orbital_sentinel.analytics.evidence_chains import (
        EvidenceChain,
        verify_evidence_chain,
    )
    from orbital_sentinel.analytics.explanation_agent import ExplanationArtifact
    from orbital_sentinel.analytics.hypotheses import HypothesisRegistry

    if args.chain_file == "-":
        raw = sys.stdin.read()
    else:
        raw = Path(args.chain_file).read_text(encoding="utf-8")
    chain = EvidenceChain.model_validate(json.loads(raw))
    hyp_raw = Path(args.hypothesis_registry_file).read_text(encoding="utf-8")
    hyp_registry = HypothesisRegistry.model_validate(json.loads(hyp_raw))
    cr_raw = Path(args.claim_registry_file).read_text(encoding="utf-8")
    claim_registry = ClaimRegistry.model_validate(json.loads(cr_raw))
    art_raw = Path(args.artifact_file).read_text(encoding="utf-8")
    artifact = ExplanationArtifact.model_validate(json.loads(art_raw))
    ai_raw = Path(args.agent_input_file).read_text(encoding="utf-8")
    agent_input = AgentInput.model_validate(json.loads(ai_raw))
    report = verify_evidence_chain(
        chain, hyp_registry, claim_registry, artifact, agent_input,
    )
    json.dump(report.model_dump(mode="json"), sys.stdout, indent=2)
    sys.stdout.write("\n")
    if args.strict and not report.is_valid:
        return 1
    return 0


def _cmd_investigation_case(args: argparse.Namespace) -> int:
    from orbital_sentinel.analytics.agent_contract import AgentInput
    from orbital_sentinel.analytics.bundles import EvidenceBundle
    from orbital_sentinel.analytics.claims import ClaimRegistry
    from orbital_sentinel.analytics.evidence_chains import EvidenceChain
    from orbital_sentinel.analytics.explanation_agent import ExplanationArtifact
    from orbital_sentinel.analytics.hypotheses import HypothesisRegistry
    from orbital_sentinel.analytics.investigations import build_investigation_case

    if args.chain_file == "-":
        raw = sys.stdin.read()
    else:
        raw = Path(args.chain_file).read_text(encoding="utf-8")
    chain = EvidenceChain.model_validate(json.loads(raw))
    hyp_raw = Path(args.hypothesis_registry_file).read_text(encoding="utf-8")
    hyp_registry = HypothesisRegistry.model_validate(json.loads(hyp_raw))
    cr_raw = Path(args.claim_registry_file).read_text(encoding="utf-8")
    claim_registry = ClaimRegistry.model_validate(json.loads(cr_raw))
    art_raw = Path(args.artifact_file).read_text(encoding="utf-8")
    artifact = ExplanationArtifact.model_validate(json.loads(art_raw))
    ai_raw = Path(args.agent_input_file).read_text(encoding="utf-8")
    agent_input = AgentInput.model_validate(json.loads(ai_raw))
    b_raw = Path(args.bundle_file).read_text(encoding="utf-8")
    bundle = EvidenceBundle.model_validate(json.loads(b_raw))
    case = build_investigation_case(
        chain,
        hypothesis_registry=hyp_registry,
        claim_registry=claim_registry,
        artifact=artifact,
        agent_input=agent_input,
        bundle=bundle,
    )
    json.dump(case.model_dump(mode="json"), sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


def _cmd_verify_investigation_case(args: argparse.Namespace) -> int:
    from orbital_sentinel.analytics.investigations import (
        InvestigationCase,
        verify_investigation_case,
    )

    if args.case_file == "-":
        raw = sys.stdin.read()
    else:
        raw = Path(args.case_file).read_text(encoding="utf-8")
    case = InvestigationCase.model_validate(json.loads(raw))
    report = verify_investigation_case(case)
    json.dump(report.model_dump(mode="json"), sys.stdout, indent=2)
    sys.stdout.write("\n")
    if args.strict and not report.is_valid:
        return 1
    return 0


def _cmd_revoke_artifact(args: argparse.Namespace) -> int:
    from orbital_sentinel.analytics.revocations import (
        build_revocation_ledger,
        build_revocation_record,
    )

    record = build_revocation_record(
        target_artifact_type=args.target_artifact_type,
        target_artifact_id=args.target_artifact_id,
        target_artifact_signature=args.target_artifact_signature,
        revocation_reason=args.revocation_reason,
        superseding_artifact_id=args.superseding_artifact_id,
        supporting_evidence_ids=args.supporting_evidence_ids,
    )
    ledger = build_revocation_ledger([record])
    json.dump(ledger.model_dump(mode="json"), sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


def _cmd_verify_revocation_ledger(args: argparse.Namespace) -> int:
    from orbital_sentinel.analytics.revocations import (
        RevocationLedger,
        verify_revocation_ledger,
    )

    if args.ledger_file == "-":
        raw = sys.stdin.read()
    else:
        raw = Path(args.ledger_file).read_text(encoding="utf-8")
    ledger = RevocationLedger.model_validate(json.loads(raw))
    report = verify_revocation_ledger(ledger)
    json.dump(report.model_dump(mode="json"), sys.stdout, indent=2)
    sys.stdout.write("\n")
    if args.strict and not report.is_valid:
        return 1
    return 0


def _cmd_external_source_registry(args: argparse.Namespace) -> int:
    from orbital_sentinel.analytics.bundles import EvidenceBundle
    from orbital_sentinel.analytics.external_sources import (
        ExternalSourceRecord,
        build_external_source_registry,
    )

    if args.bundle_file == "-":
        raw = sys.stdin.read()
    else:
        raw = Path(args.bundle_file).read_text(encoding="utf-8")
    bundle = EvidenceBundle.model_validate(json.loads(raw))
    records_raw = Path(args.records_file).read_text(encoding="utf-8")
    records_doc = json.loads(records_raw)
    records = [
        ExternalSourceRecord.model_validate(d) for d in records_doc["records"]
    ]
    mapping = records_doc["evidence_to_source_record_mapping"]
    registry = build_external_source_registry(bundle, records, mapping)
    json.dump(registry.model_dump(mode="json"), sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


def _cmd_external_source_registry_from_repos(args: argparse.Namespace) -> int:
    from orbital_sentinel.analytics.bundles import EvidenceBundle
    from orbital_sentinel.analytics.external_sources import (
        derive_external_source_registry_for_bundle,
    )
    from orbital_sentinel.catalog.orbital_elements import OrbitalElementsRepository
    from orbital_sentinel.catalog.tle_snapshots import TLESnapshotsRepository

    if args.bundle_file == "-":
        raw = sys.stdin.read()
    else:
        raw = Path(args.bundle_file).read_text(encoding="utf-8")
    bundle = EvidenceBundle.model_validate(json.loads(raw))
    tle_repo = TLESnapshotsRepository(args.raw_root)
    elem_repo = OrbitalElementsRepository(args.normalized_root)
    registry = derive_external_source_registry_for_bundle(
        bundle,
        tle_snapshots_repo=tle_repo,
        orbital_elements_repo=elem_repo,
    )
    json.dump(registry.model_dump(mode="json"), sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


def _cmd_verify_external_source_registry(args: argparse.Namespace) -> int:
    from orbital_sentinel.analytics.bundles import EvidenceBundle
    from orbital_sentinel.analytics.external_sources import (
        ExternalSourceRegistry,
        verify_external_source_registry,
    )

    if args.registry_file == "-":
        raw = sys.stdin.read()
    else:
        raw = Path(args.registry_file).read_text(encoding="utf-8")
    registry = ExternalSourceRegistry.model_validate(json.loads(raw))
    b_raw = Path(args.bundle_file).read_text(encoding="utf-8")
    bundle = EvidenceBundle.model_validate(json.loads(b_raw))
    report = verify_external_source_registry(registry, bundle)
    json.dump(report.model_dump(mode="json"), sys.stdout, indent=2)
    sys.stdout.write("\n")
    if args.strict and not report.is_valid:
        return 1
    return 0


def _cmd_dissent_record(args: argparse.Namespace) -> int:
    from orbital_sentinel.analytics.dissent import build_dissent_record

    record = build_dissent_record(
        target_case_id=args.target_case_id,
        target_case_signature=args.target_case_signature,
        dissent_index=args.dissent_index,
        dissent_type=args.dissent_type,
        dissent_basis_evidence_ids=args.dissent_basis_evidence_ids,
        referenced_alternative_case_id=args.referenced_alternative_case_id,
    )
    json.dump(record.model_dump(mode="json"), sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


def _cmd_dissent_ledger(args: argparse.Namespace) -> int:
    from orbital_sentinel.analytics.dissent import (
        DissentRecord,
        build_dissent_ledger,
    )

    records = []
    for p in args.record_files:
        raw = Path(p).read_text(encoding="utf-8")
        records.append(DissentRecord.model_validate(json.loads(raw)))
    ledger = build_dissent_ledger(
        target_case_id=args.target_case_id,
        target_case_signature=args.target_case_signature,
        records=records,
    )
    json.dump(ledger.model_dump(mode="json"), sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


def _cmd_verify_dissent_ledger(args: argparse.Namespace) -> int:
    from orbital_sentinel.analytics.dissent import (
        DissentLedger,
        verify_dissent_ledger,
    )

    if args.ledger_file == "-":
        raw = sys.stdin.read()
    else:
        raw = Path(args.ledger_file).read_text(encoding="utf-8")
    ledger = DissentLedger.model_validate(json.loads(raw))
    report = verify_dissent_ledger(ledger)
    json.dump(report.model_dump(mode="json"), sys.stdout, indent=2)
    sys.stdout.write("\n")
    if args.strict and not report.is_valid:
        return 1
    return 0


def _cmd_self_verify(args: argparse.Namespace) -> int:
    from orbital_sentinel.reproducibility import verify_installation

    report = verify_installation()
    json.dump(report.model_dump(mode="json"), sys.stdout, indent=2)
    sys.stdout.write("\n")
    if args.strict and not report.is_valid:
        return 1
    return 0


def _cmd_detections(args: argparse.Namespace) -> int:
    output = run_detections(
        detections_root=args.detections_root,
        norad=args.norad,
        limit=args.limit,
    )
    json.dump(output, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


def run_detections(
    *,
    detections_root: Path,
    norad: int | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    """Lista detecciones persistidas, opcionalmente filtradas por NORAD."""
    from orbital_sentinel.analytics.conjunctions import (
        ConjunctionDetectionsRepository,
    )

    repo = ConjunctionDetectionsRepository(detections_root)
    if norad is not None:
        rows = repo.find_by_norad(norad, limit=limit)
    else:
        rows = list(repo.iter_all())
        rows.sort(key=lambda d: d.miss_distance_km)
        rows = rows[:limit]

    return {
        "n_total": repo.count(),
        "n_returned": len(rows),
        "filter_norad": norad,
        "detections": [d.model_dump(mode="json") for d in rows],
    }


def _build_time_list(
    from_time: datetime, to_time: datetime, step_minutes: float
) -> list[datetime]:
    times: list[datetime] = []
    step = timedelta(minutes=step_minutes)
    t = from_time
    while t <= to_time:
        times.append(t)
        t += step
    return times


def _serialize_ephemeris(e: Ephemeris) -> dict[str, Any]:
    return {
        "evaluation_time": e.evaluation_time.isoformat(),
        "minutes_from_epoch": e.minutes_from_epoch,
        "position_teme_km": list(e.position_teme_km),
        "velocity_teme_km_s": list(e.velocity_teme_km_s),
        "sgp4_error_code": e.sgp4_error_code,
    }


# --- error reporting ------------------------------------------------------


def _emit_error(message: str, kind: str) -> None:
    sys.stderr.write(
        json.dumps({"error": kind, "message": message}, indent=2) + "\n"
    )


if __name__ == "__main__":
    sys.exit(main())
