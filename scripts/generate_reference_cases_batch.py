"""Genera múltiples InvestigationCases válidos en batch.

Cada caso ejecuta el pipeline completo:

    TLEs (raw)
      → TLESnapshot
      → normalize_snapshot → OrbitalElement[]
      → analyze_pairwise_conjunction (primary vs cada target)
      → ConjunctionDetection.from_analysis
      → _conjunction_to_evidence → DerivedEvidence
      → EvidenceCatalog.from_evidence
      → build_explanation_context
      → build_evidence_bundle
      → build_agent_input
      → generate_explanation
      → build_claim_registry
      → build_hypothesis_registry
      → build_evidence_chain
      → build_investigation_case
      → escribir reference_cases/<case_dir>/case.json

Los hashes cross-layer son coherentes por construcción: la cadena se
verifica con `verify_investigation_case(case)` antes de escribir.

Uso:
    python scripts/generate_reference_cases_batch.py

Para añadir casos nuevos: editar SPECS (al final del módulo) con tuplas
(case_dir, primary_norad, target_norads, window_minutes).
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
APP = ROOT / "app"
REF_CASES = ROOT / "reference_cases"
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(APP))

from orbital_sentinel.analytics.agent_contract import build_agent_input
from orbital_sentinel.analytics.bundles import build_evidence_bundle
from orbital_sentinel.analytics.claims import build_claim_registry
from orbital_sentinel.analytics.conjunctions import (
    analyze_pairwise_conjunction,
)
from orbital_sentinel.analytics.conjunctions.storage import ConjunctionDetection
from orbital_sentinel.analytics.evidence import (
    EvidenceCatalog,
)
from orbital_sentinel.analytics.evidence.builders import (
    build_conjunction_evidence,
)
from orbital_sentinel.analytics.evidence_chains import build_evidence_chain
from orbital_sentinel.analytics.explanation import build_explanation_context
from orbital_sentinel.analytics.explanation_agent import generate_explanation
from orbital_sentinel.analytics.hypotheses import build_hypothesis_registry
from orbital_sentinel.analytics.investigations import (
    build_investigation_case,
    verify_investigation_case,
)
from orbital_sentinel.catalog import TLESnapshot, normalize_snapshot

# Carga el catálogo de TLEs embebidos (ya descargados de CelesTrak)
import tle_embedded as TE  # noqa: E402


# ─────────────────────────────────────────────────────────────────────
# Helpers de pipeline
# ─────────────────────────────────────────────────────────────────────

def _make_snapshot(name: str, raw_text: str, fetched_at: datetime) -> TLESnapshot:
    encoded = raw_text.encode("utf-8")
    return TLESnapshot(
        content_hash=hashlib.sha256(encoded).hexdigest(),
        source="celestrak",
        dataset=name,
        url=f"https://celestrak.org/NORAD/elements/{name}.txt",
        fetched_at=fetched_at,
        raw_text=raw_text,
        n_bytes=len(encoded),
    )


def _norad_to_index(elements: list, norad: int) -> int:
    for i, el in enumerate(elements):
        if int(el.norad_cat_id) == int(norad):
            return i
    raise ValueError(f"NORAD {norad} no encontrado en el dataset")


def _build_case(
    *,
    case_dir: str,
    primary_norad: int,
    target_norads: list[int],
    dataset_var: str,
    window_minutes: int = 1440,   # 24 h
    step_minutes: float = 5.0,
    combined_radius_km: float = 0.020,  # 20 m default
    derived_at: datetime,
) -> tuple[str, int]:
    """Construye un caso y lo guarda en reference_cases/<case_dir>/.

    Returns: (case_id, n_detections).
    """
    raw_text = getattr(TE, dataset_var, "")
    if not raw_text:
        raise ValueError(f"Dataset {dataset_var} vacío en tle_embedded.py")
    snap = _make_snapshot(dataset_var.lower().replace("tle_", ""), raw_text, derived_at)
    elements = list(normalize_snapshot(snap, derived_at=derived_at))
    idx_primary = _norad_to_index(elements, primary_norad)
    primary_el = elements[idx_primary]

    # Ventana temporal centrada en la época del primary
    window_start = primary_el.epoch_datetime + timedelta(minutes=30)
    window_end = window_start + timedelta(minutes=window_minutes)

    # Detectar conjunciones contra cada target
    detections: list[ConjunctionDetection] = []
    persist_at = derived_at
    for tnorad in target_norads:
        try:
            tidx = _norad_to_index(elements, tnorad)
        except ValueError:
            print(f"   WARN target NORAD {tnorad} no en dataset, skip")
            continue
        target_el = elements[tidx]
        try:
            analysis = analyze_pairwise_conjunction(
                primary_el, snap, target_el, snap,
                window_start=window_start,
                window_end=window_end,
                step_minutes=step_minutes,
                combined_hard_body_radius_km=combined_radius_km,
            )
        except Exception as exc:
            print(f"   WARN analyze fallo contra NORAD {tnorad}: {exc}")
            continue
        det = ConjunctionDetection.from_analysis(analysis, persisted_at=persist_at)
        detections.append(det)

    if not detections:
        print(f"   WARN {case_dir}: 0 detections validas, omitido")
        return "", 0

    # Convertir detecciones a evidences (lado primary)
    evidences = build_conjunction_evidence(
        detections, only_for_norad=primary_norad,
    )

    # Pipeline completo
    def _clock() -> datetime:
        return derived_at

    catalog = EvidenceCatalog.from_evidence(evidences, derived_at=derived_at)
    ctx = build_explanation_context(catalog, object_id=primary_norad, clock=_clock)
    bundle = build_evidence_bundle(ctx, catalog, clock=_clock)
    ai = build_agent_input(
        bundle, declared_consumer_class="explanation_agent_v01", clock=_clock,
    )
    art = generate_explanation(ai, clock=_clock)
    cr = build_claim_registry(art, ai, clock=_clock)
    hr = build_hypothesis_registry(cr, ai, clock=_clock)
    chain = build_evidence_chain(hr, cr, art, ai, clock=_clock)
    case = build_investigation_case(
        chain, hypothesis_registry=hr, claim_registry=cr,
        artifact=art, agent_input=ai, bundle=bundle, clock=_clock,
    )

    # Verificar la cadena antes de escribir (sanity check)
    report = verify_investigation_case(case)
    if not report.is_valid:
        raise RuntimeError(
            f"Case {case_dir} no valida tras construcción: "
            f"{report.n_findings} findings"
        )

    # Escribir
    out_dir = REF_CASES / case_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "case.json").write_text(
        json.dumps(case.model_dump(mode="json"), indent=2),
        encoding="utf-8",
    )
    return case.case_id, len(detections)


# ─────────────────────────────────────────────────────────────────────
# Specs de casos a generar
# ─────────────────────────────────────────────────────────────────────
#
# Formato: (case_dir, primary_norad, target_norads, dataset_var, comment)
# `dataset_var` apunta a una variable TLE_* en tle_embedded.py
#
# Para targets de constelaciones grandes, pasamos lista vacía y el script
# escogerá los N más cercanos en altitud automáticamente — pero para
# determinismo de hashes, las listas fijas son mejores.

SPECS: list[dict] = [
    # ── Sistemas de navegación global ────────────────────────────────
    {
        "case_dir": "gps_iiia_conjunction_001",
        "primary_norad": 40730,    # GPS BIIF-9 (USA 260)
        "targets": [40294, 40534, 41019, 43873, 45854, 46826, 48859, 55268],
        "dataset_var": "TLE_GPS_OPS",
        "comment": "GPS IIIA en MEO ~20200 km, conjunciones con otros GPS",
    },
    {
        "case_dir": "galileo_conjunction_001",
        "primary_norad": 41859,    # Galileo 13 (FOC FM10)
        "targets": [41174, 41175, 41549, 41550, 41859, 42671, 49809],
        "dataset_var": "TLE_GALILEO",
        "comment": "Galileo FOC en MEO ~23222 km",
    },
    {
        "case_dir": "glonass_conjunction_001",
        "primary_norad": 32276,    # COSMOS 2434 (GLONASS)
        "targets": [32275, 32393, 36400, 37938, 39155, 39620, 40001],
        "dataset_var": "TLE_GLONASS",
        "comment": "GLONASS en MEO ~19100 km",
    },
    {
        "case_dir": "beidou_conjunction_001",
        "primary_norad": 38953,    # BEIDOU IGSO-3
        "targets": [37809, 38091, 38250, 38775, 38953, 41315, 41434],
        "dataset_var": "TLE_BEIDOU",
        "comment": "BeiDou MEO/IGSO",
    },
    # ── Comunicaciones ───────────────────────────────────────────────
    {
        "case_dir": "iridium_conjunction_001",
        "primary_norad": 41917,    # Iridium NEXT 102
        "targets": [41918, 41919, 41920, 41921, 41922, 41923, 41924],
        "dataset_var": "TLE_IRIDIUM_NEXT",
        "comment": "Iridium NEXT en LEO ~780 km, fly-by entre adyacentes",
    },
    {
        "case_dir": "intelsat_geo_conjunction_001",
        "primary_norad": 26900,    # INTELSAT (primer object en el grupo)
        "targets": [27380, 27426, 27438, 27445, 27513, 27954, 28358, 28659],
        "dataset_var": "TLE_INTELSAT",
        "comment": "INTELSAT GEO ~35786 km",
    },
    # ── Observación Tierra y meteorología ────────────────────────────
    {
        "case_dir": "earth_obs_conjunction_001",
        "primary_norad": 39634,    # SENTINEL-1A
        "targets": [40697, 43689, 43781, 51850, 56759],
        "dataset_var": "TLE_EO_RESOURCE",
        "comment": "Earth observation en SSO ~700 km",
    },
    {
        "case_dir": "weather_conjunction_001",
        "primary_norad": 28054,    # DMSP 5D-3 F16
        "targets": [28912, 29522, 32958, 35491, 35951, 36411, 36744, 37214],
        "dataset_var": "TLE_WEATHER",
        "comment": "Satelites meteorologicos en LEO SSO",
    },
    # ── CubeSats y ciencia ────────────────────────────────────────────
    {
        "case_dir": "cubesat_conjunction_001",
        "primary_norad": 27844,    # CubeSat (primer object en el grupo)
        "targets": [27848, 28895, 32785, 32790, 32791, 35932, 35933, 35935],
        "dataset_var": "TLE_CUBESAT",
        "comment": "CubeSats co-orbitales en LEO",
    },
]


def main() -> int:
    derived_at = datetime(2026, 6, 10, 12, 0, tzinfo=timezone.utc)
    print(f"Generando {len(SPECS)} casos de referencia…")
    print(f"derived_at: {derived_at.isoformat()}")
    print()
    successes = 0
    for spec in SPECS:
        print(f"[{spec['case_dir']}] {spec['comment']}")
        try:
            case_id, n_det = _build_case(
                case_dir=spec["case_dir"],
                primary_norad=spec["primary_norad"],
                target_norads=spec["targets"],
                dataset_var=spec["dataset_var"],
                derived_at=derived_at,
            )
            if case_id:
                print(f"   OK case_id={case_id[:16]}... {n_det} detections")
                successes += 1
        except Exception as exc:
            print(f"   FAIL: {type(exc).__name__}: {exc}")
        print()
    print(f"\n{successes}/{len(SPECS)} casos generados con éxito.")
    return 0 if successes else 1


if __name__ == "__main__":
    raise SystemExit(main())
