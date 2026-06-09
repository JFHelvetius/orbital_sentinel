"""Orbital Sentinel — interfaz web.

Cuatro secciones:
  1. Mapa orbital       — globo interactivo con trazas de órbita (Plotly).
  2. Casos de referencia — explora los InvestigationCase incluidos en el repo.
  3. Verificar           — sube cualquier case.json y comprueba la cadena.
  4. Sobre el proyecto   — descripción, filosofía, enlaces.

Streamlit Cloud: el paquete se importa desde src/ del repo clonado.
Las deps (pydantic, duckdb, pyarrow, sgp4, streamlit, pandas, plotly)
se instalan vía requirements.txt sin compilar el paquete.
"""

from __future__ import annotations

import math
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, NamedTuple

_SRC = Path(__file__).parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from sgp4.api import Satrec
from sgp4.api import jday as _sgp4_jday

from orbital_sentinel.analytics.investigations.models import InvestigationCase
from orbital_sentinel.analytics.investigations.verifier import verify_investigation_case

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

_ROOT = Path(__file__).parent.parent
_CASES_DIR = _ROOT / "reference_cases"
EARTH_R_KM = 6371.0

_NORAD_NAMES: dict[int, str] = {
    25544: "ISS",
    36086: "Poisk",
    48274: "CSS Tianhe",
    49044: "Nauka",
    49271: "Fregat Deb",
    53239: "Wentian",
    54216: "Mengtian",
    66052: "HRC Camera",
    66515: "SZ-21 Module",
    66664: "Soyuz-MS 28",
    66906: "Duplex",
    66912: "ISS Object XY",
    67683: "KNACKSAT-2",
    67684: "CORAL",
    67685: "GXIBA-1",
    67686: "UITMSAT-2",
    67687: "LEOPARD",
    67688: "HMU-SAT2",
    67796: "Crew Dragon 12",
    68319: "Progress-MS 33",
    68689: "Cygnus NG-24",
    68837: "Progress-MS 34",
    69049: "Tianzhou-10",
    69103: "Dragon CRS-34",
    69180: "Shenzhou-23",
}

_CASE_LABELS: dict[str, str] = {
    "iss_conjunction_001": "ISS (25544) — Conjunciones Jun 2026",
    "tiangong_conjunction_002": "CSS Tianhe (48274) — Conjunciones Jun 2026",
}

# Objetos no cooperativos con miss > 10 km en los casos de referencia
_CONJUNCTION_PARTNERS: set[int] = {67688}  # HMU-SAT2

# Clusters de la ISS (docked)
_ISS_CLUSTER: set[int] = {
    25544, 36086, 49044, 66052, 66515, 66664, 66906, 66912,
    67796, 68319, 68689,
}
# Clusters del CSS (docked)
_CSS_CLUSTER: set[int] = {48274, 53239, 54216, 49271, 69049, 69180}


# ---------------------------------------------------------------------------
# Orbital map helpers
# ---------------------------------------------------------------------------

class SatTrack(NamedTuple):
    norad: int
    name: str
    lats: list[float | None]
    lons: list[float | None]
    epoch_lat: float
    epoch_lon: float
    epoch_alt: float


def _jday_dt(dt: datetime) -> tuple[float, float]:
    return _sgp4_jday(
        dt.year, dt.month, dt.day,
        dt.hour, dt.minute,
        dt.second + dt.microsecond * 1e-6,
    )


def _teme_to_latlon(x: float, y: float, z: float, dt: datetime) -> tuple[float, float, float]:
    """TEME → (lat_deg, lon_deg, alt_km) via rotación GMST simplificada."""
    jd1, jd2 = _jday_dt(dt)
    jd = jd1 + jd2
    t = (jd - 2451545.0) / 36525.0
    gmst_deg = (
        280.46061837
        + 360.98564736629 * (jd - 2451545.0)
        + 0.000387933 * t * t
        - t * t * t / 38710000.0
    ) % 360.0
    theta = math.radians(gmst_deg)
    cx, sx = math.cos(theta), math.sin(theta)
    ex = x * cx + y * sx
    ey = -x * sx + y * cx
    ez = z
    r = math.sqrt(ex * ex + ey * ey + ez * ez)
    lat = math.degrees(math.asin(ez / r))
    lon = math.degrees(math.atan2(ey, ex))
    if lon > 180.0:
        lon -= 360.0
    elif lon < -180.0:
        lon += 360.0
    return lat, lon, r - EARTH_R_KM


def _tle_epoch(sat: Satrec) -> datetime:
    """Extrae el epoch del TLE como datetime UTC."""
    jd = sat.jdsatepoch + sat.jdsatepochF
    delta = timedelta(days=jd - 2451545.0)
    return datetime(2000, 1, 1, 12, 0, 0, tzinfo=timezone.utc) + delta


def _find_blob(case_name: str) -> Path | None:
    blobs_dir = _CASES_DIR / case_name / "cache" / "blobs"
    for f in blobs_dir.rglob("*.bin"):
        return f
    return None


def _parse_tle_blocks(text: str) -> list[tuple[str, str, str]]:
    lines = [l.rstrip() for l in text.splitlines() if l.strip()]
    blocks = []
    for i in range(0, len(lines) - 2, 3):
        name, l1, l2 = lines[i], lines[i + 1], lines[i + 2]
        if l1.startswith("1 ") and l2.startswith("2 "):
            blocks.append((name.strip(), l1, l2))
    return blocks


@st.cache_data(show_spinner=False)
def _compute_tracks(case_name: str) -> list[SatTrack]:
    blob_path = _find_blob(case_name)
    if blob_path is None:
        return []
    blocks = _parse_tle_blocks(blob_path.read_text(encoding="utf-8"))

    # Usar epoch del primer TLE como tiempo de referencia
    ref_sat = Satrec.twoline2rv(blocks[0][1], blocks[0][2])
    epoch = _tle_epoch(ref_sat)

    tracks: list[SatTrack] = []
    for name, l1, l2 in blocks:
        sat = Satrec.twoline2rv(l1, l2)
        norad = int(l2.split()[1])
        lats: list[float | None] = []
        lons: list[float | None] = []
        prev_lon: float | None = None

        for minute in range(92):  # ~1.5 órbitas LEO
            t = epoch + timedelta(minutes=minute)
            jd1, jd2 = _jday_dt(t)
            e, r, _ = sat.sgp4(jd1, jd2)
            if e != 0 or r[0] == 0.0:
                lats.append(None)
                lons.append(None)
                prev_lon = None
                continue
            lat, lon, alt = _teme_to_latlon(r[0], r[1], r[2], t)
            if prev_lon is not None and abs(lon - prev_lon) > 180:
                lats.append(None)
                lons.append(None)
            lats.append(lat)
            lons.append(lon)
            prev_lon = lon

        # Posición en época
        jd1, jd2 = _jday_dt(epoch)
        e0, r0, _ = sat.sgp4(jd1, jd2)
        if e0 == 0 and r0[0] != 0.0:
            elat, elon, ealt = _teme_to_latlon(r0[0], r0[1], r0[2], epoch)
        else:
            elat, elon, ealt = 0.0, 0.0, 400.0

        tracks.append(SatTrack(
            norad=norad,
            name=_NORAD_NAMES.get(norad, name),
            lats=lats,
            lons=lons,
            epoch_lat=elat,
            epoch_lon=elon,
            epoch_alt=ealt,
        ))

    return tracks


def _orbital_figure(tracks: list[SatTrack], case: InvestigationCase) -> go.Figure:
    # Extraer NORADs de conjunciones con miss > 10 km
    real_partners: set[int] = set()
    for be in case.evidence_bundle.evidence_payloads:
        hp = be.derived_evidence.honesty_payload
        if hp.get("miss_distance_km", 0) > 10:
            real_partners.add(int(hp.get("other_norad_cat_id", 0)))

    fig = go.Figure()

    for t in tracks:
        if t.norad == 25544:  # ISS
            line_color, marker_color = "#FFD700", "#FFD700"
            line_width, marker_size = 2.5, 14
            symbol = "star"
        elif t.norad == 48274:  # CSS Tianhe
            line_color, marker_color = "#FF6B6B", "#FF6B6B"
            line_width, marker_size = 2.5, 14
            symbol = "diamond"
        elif t.norad in real_partners:
            line_color, marker_color = "#FF4444", "#FF4444"
            line_width, marker_size = 2, 10
            symbol = "x"
        elif t.norad in _ISS_CLUSTER or t.norad in _CSS_CLUSTER:
            line_color, marker_color = "rgba(100,160,255,0.45)", "rgba(100,160,255,0.8)"
            line_width, marker_size = 1, 6
            symbol = "circle"
        else:
            line_color, marker_color = "rgba(160,220,160,0.45)", "rgba(160,220,160,0.8)"
            line_width, marker_size = 1, 6
            symbol = "circle"

        hover = (
            f"<b>{t.name}</b><br>"
            f"NORAD {t.norad}<br>"
            f"Alt: {t.epoch_alt:.0f} km"
            + ("<br><b>⚠ Acercamiento no cooperativo</b>" if t.norad in real_partners else "")
        )

        # Traza de órbita
        fig.add_trace(go.Scattergeo(
            lat=t.lats,
            lon=t.lons,
            mode="lines",
            line=dict(width=line_width, color=line_color),
            name=t.name,
            showlegend=True,
            hoverinfo="skip",
        ))

        # Posición en época
        fig.add_trace(go.Scattergeo(
            lat=[t.epoch_lat],
            lon=[t.epoch_lon],
            mode="markers+text" if t.norad in {25544, 48274} | real_partners else "markers",
            marker=dict(size=marker_size, color=marker_color, symbol=symbol),
            text=[t.name] if t.norad in {25544, 48274} | real_partners else [],
            textposition="top right",
            textfont=dict(color="white", size=11),
            name=t.name,
            showlegend=False,
            hovertemplate=hover + "<extra></extra>",
        ))

    fig.update_geos(
        projection_type="natural earth",
        showland=True,
        landcolor="rgb(35,40,50)",
        showocean=True,
        oceancolor="rgb(15,20,40)",
        showlakes=False,
        showrivers=False,
        showcoastlines=True,
        coastlinecolor="rgba(120,130,150,0.7)",
        showcountries=True,
        countrycolor="rgba(80,90,110,0.4)",
        bgcolor="rgb(10,14,28)",
        framecolor="rgba(100,120,150,0.3)",
    )
    fig.update_layout(
        paper_bgcolor="rgb(10,14,28)",
        plot_bgcolor="rgb(10,14,28)",
        height=560,
        margin=dict(l=0, r=0, t=40, b=0),
        legend=dict(
            bgcolor="rgba(15,20,40,0.85)",
            bordercolor="rgba(100,120,150,0.4)",
            borderwidth=1,
            font=dict(color="rgba(200,210,230,0.9)", size=11),
            orientation="v",
            x=1.01, y=1,
        ),
        title=dict(
            text="Posiciones en época TLE · trazas 90 min",
            font=dict(color="rgba(180,190,220,0.9)", size=13),
            x=0.01,
        ),
    )
    return fig


# ---------------------------------------------------------------------------
# Case helpers (reutilizados en varias pestañas)
# ---------------------------------------------------------------------------

def _norad_label(norad: int) -> str:
    name = _NORAD_NAMES.get(norad)
    return f"{name} ({norad})" if name else str(norad)


def _short(h: str, n: int = 14) -> str:
    return h[:n] + "…"


def _list_cases() -> list[str]:
    if not _CASES_DIR.exists():
        return []
    return sorted(
        d.name
        for d in _CASES_DIR.iterdir()
        if d.is_dir()
        and (d / "case.json").exists()
        and d.name != "external_audit_demo"
    )


@st.cache_data(show_spinner=False)
def _load_case(name: str) -> InvestigationCase:
    return InvestigationCase.model_validate_json(
        (_CASES_DIR / name / "case.json").read_text(encoding="utf-8")
    )


def _evidence_rows(case: InvestigationCase) -> list[dict[str, Any]]:
    rows = []
    for be in case.evidence_bundle.evidence_payloads:
        ev = be.derived_evidence
        hp = ev.honesty_payload
        if ev.source_detector == "conjunction_detection_v01":
            rows.append({
                "Objeto secundario": _norad_label(int(hp.get("other_norad_cat_id", 0))),
                "TCA (UTC)": ev.event_epoch.strftime("%Y-%m-%d  %H:%M:%S"),
                "Distancia mín (km)": round(float(hp.get("miss_distance_km", 0.0)), 4),
                "σ combinado (km)": round(float(hp.get("combined_sigma_at_tca_km", 0.0)), 3),
                "TCA refinado": "✓" if hp.get("tca_was_refined") else "—",
                "Solo aparente": "sí" if ev.is_apparent_not_confirmed else "no",
                "evidence_id": _short(ev.evidence_id),
            })
    return sorted(rows, key=lambda r: r["Distancia mín (km)"])


def _highlight(row: pd.Series) -> list[str]:
    miss = row["Distancia mín (km)"]
    if miss > 10.0:
        return ["background-color:#2a1f00;color:#FFD700;font-weight:bold"] * len(row)
    if miss > 1.0:
        return ["background-color:#0f1a2e"] * len(row)
    return ["color:#555"] * len(row)


def _render_case(case: InvestigationCase, *, run_verify: bool = True) -> None:
    primary = case.evidence_bundle.object_id
    st.markdown(f"#### {_norad_label(primary)}")
    st.caption(
        f"case\\_id: `{_short(case.case_id, 20)}`  ·  "
        f"producido: {case.derived_at.strftime('%Y-%m-%d %H:%M UTC')}  ·  "
        f"{case.evidence_bundle.n_evidence_payloads} evidencias"
    )

    if run_verify:
        report = verify_investigation_case(case)
        if report.is_valid:
            st.success(f"✓ Cadena íntegra — {report.n_artifacts_verified} artefactos verificados", icon="🔒")
        else:
            st.error(f"✗ {report.n_findings} fallo(s) en la cadena", icon="⚠️")
            for f in report.findings:
                st.warning(f"`{f.finding_type}`")

    for hyp in case.hypothesis_registry.hypotheses:
        st.info(f"**Hipótesis:** {hyp.hypothesis_label}", icon="📋")

    st.divider()
    rows = _evidence_rows(case)
    if rows:
        df = pd.DataFrame(rows)
        st.markdown("**Evidencias** (ordenadas por distancia mínima)")
        st.caption("Dorado = acercamiento no co-orbital. Gris = objeto co-orbital.")
        st.dataframe(df.style.apply(_highlight, axis=1), use_container_width=True, hide_index=True)

    with st.expander("Explicación verbatim del agente", expanded=False):
        st.code(case.explanation_artifact.explanation_text, language=None)

    with st.expander("Cadena de custodia (hashes SHA-256)", expanded=False):
        for label, h in [
            ("bundle_id", case.referenced_bundle_id),
            ("agent_input_id", case.referenced_agent_input_id),
            ("explanation_id", case.referenced_explanation_id),
            ("claim_registry_id", case.referenced_claim_registry_id),
            ("hypothesis_registry_id", case.referenced_hypothesis_registry_id),
            ("chain_id", case.referenced_chain_id),
            ("case_signature", case.case_signature),
        ]:
            st.text(f"  {label}:\n  {h}")


# ---------------------------------------------------------------------------
# Páginas
# ---------------------------------------------------------------------------

def _page_map() -> None:
    st.header("Mapa orbital", divider="gray")

    cases = _list_cases()
    if not cases:
        st.error("No se encontraron casos.")
        return

    options = {_CASE_LABELS.get(c, c): c for c in cases}
    label = st.selectbox("Dataset:", list(options.keys()), key="map_case")
    selected = options[label]

    col_info, col_legend = st.columns([3, 1])
    with col_info:
        st.caption(
            "Posiciones calculadas en la época del TLE (2026-06-08). "
            "Trazas = 90 minutos de órbita hacia adelante. "
            "⭐ ISS · ♦ CSS Tianhe · ✕ acercamiento no cooperativo."
        )

    with st.spinner("Propagando órbitas…"):
        try:
            tracks = _compute_tracks(selected)
            case = _load_case(selected)
        except Exception as exc:
            st.error(f"Error: {exc}")
            return

    fig = _orbital_figure(tracks, case)
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": True})

    # Métrica rápida de la conjunción principal
    real_events = [
        be for be in case.evidence_bundle.evidence_payloads
        if be.derived_evidence.honesty_payload.get("miss_distance_km", 0) > 10
    ]
    if real_events:
        st.divider()
        st.markdown("**Acercamientos no cooperativos detectados en este caso:**")
        cols = st.columns(len(real_events))
        for col, be in zip(cols, real_events):
            hp = be.derived_evidence.honesty_payload
            norad = int(hp.get("other_norad_cat_id", 0))
            miss = float(hp.get("miss_distance_km", 0))
            tca = be.derived_evidence.event_epoch.strftime("%Y-%m-%d %H:%M UTC")
            with col:
                st.metric(
                    label=_norad_label(norad),
                    value=f"{miss:.2f} km",
                    delta=f"TCA {tca}",
                    delta_color="off",
                )


def _page_cases() -> None:
    st.header("Casos de referencia", divider="gray")
    st.write(
        "Casos producidos desde una ingesta real de CelesTrak el 2026-06-08. "
        "La cadena criptográfica es verificable offline con "
        "`orbital-sentinel verify-investigation-case`."
    )

    cases = _list_cases()
    if not cases:
        st.error("No se encontraron casos.")
        return

    options = {_CASE_LABELS.get(c, c): c for c in cases}
    label = st.selectbox("Caso:", list(options.keys()), key="cases_sel")
    selected = options[label]

    with st.spinner("Cargando…"):
        try:
            case = _load_case(selected)
        except Exception as exc:
            st.error(f"Error: {exc}")
            return

    # Botón de descarga
    case_bytes = (_CASES_DIR / selected / "case.json").read_bytes()
    st.download_button(
        label="⬇ Descargar case.json",
        data=case_bytes,
        file_name=f"{selected}_case.json",
        mime="application/json",
        help="Descarga el archivo y súbelo en la pestaña 'Verificar' para comprobar la cadena.",
    )

    _render_case(case)

    if len(cases) > 1:
        st.divider()
        st.caption(
            "💡 HMU-SAT2 (67688) aparece como acercamiento real en **ambos** casos "
            "(ISS y CSS Tianhe) en la misma ventana de 7 días."
        )


def _page_verify() -> None:
    st.header("Verificar un InvestigationCase", divider="gray")
    st.write(
        "Sube cualquier `case.json`. "
        "La verificación corre localmente — ningún dato sale de tu máquina."
    )

    uploaded = st.file_uploader(
        "Arrastra aquí tu case.json",
        type=["json"],
        key="verify_upload",
        help="Descárgalo desde la pestaña 'Casos de referencia' o desde GitHub.",
    )

    if not uploaded:
        st.info("Descarga un caso desde la pestaña anterior para probar.", icon="ℹ️")
        return

    with st.spinner("Verificando…"):
        raw = uploaded.read().decode("utf-8")
        try:
            case = InvestigationCase.model_validate_json(raw)
        except Exception as exc:
            st.error(f"El archivo no es un `InvestigationCase` válido: `{exc}`")
            return
        report = verify_investigation_case(case)

    if report.is_valid:
        st.success(
            f"**Cadena íntegra.** {report.n_artifacts_verified} artefactos, 0 fallos.",
            icon="🔒",
        )
    else:
        st.error(f"**Cadena rota.** {report.n_findings} fallo(s).", icon="⚠️")
        for f in report.findings:
            st.warning(
                f"`{f.finding_type}`  \n"
                f"Esperado: `{f.expected[:32]}…`  \nObtenido: `{f.actual[:32]}…`"
            )

    st.divider()
    _render_case(case, run_verify=False)

    with st.expander("Reporte completo (JSON)", expanded=False):
        st.json(report.model_dump(mode="json"))


def _page_about() -> None:
    st.header("Sobre el proyecto", divider="gray")
    st.markdown(
        """
**Orbital Sentinel** es software de código abierto que permite a cualquier persona —
sin acceso privilegiado, sin autoridad, sin confianza en nadie —
*demostrar* qué ocurre en órbita y *auditar* la afirmación de cualquier otro.

La unidad de trabajo es un `InvestigationCase`: un único JSON con la cadena completa
desde los bytes originales de CelesTrak hasta las conclusiones. Rompible en cualquier
eslabón si alguien manipuló los datos en el camino.

---
**Sin IA · Sin LLM · Sin puntuaciones de riesgo · Sin autoridad central.**

Cada explicación es texto generado por plantillas determinísticas.
El sistema no *interpreta*; *cita*.

---
"""
    )
    c1, c2, c3 = st.columns(3)
    with c1:
        st.link_button("Código en GitHub", "https://github.com/JFHelvetius/orbital_sentinel")
    with c2:
        st.link_button("Instalar desde PyPI", "https://pypi.org/project/orbital-sentinel/")
    with c3:
        st.link_button(
            "Por qué existe",
            "https://github.com/JFHelvetius/orbital_sentinel/blob/main/docs/why-this-exists.md",
        )
    st.caption("Apache 2.0 · Datos: CelesTrak (fuente pública).")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    st.set_page_config(
        page_title="Orbital Sentinel",
        page_icon="🛰️",
        layout="wide",
        initial_sidebar_state="collapsed",
        menu_items={
            "Get Help": "https://github.com/JFHelvetius/orbital_sentinel/discussions",
            "Report a bug": "https://github.com/JFHelvetius/orbital_sentinel/issues",
            "About": "Orbital Sentinel — infraestructura verificable para afirmaciones orbitales. Apache 2.0.",
        },
    )

    st.title("🛰️  Orbital Sentinel")
    st.caption(
        "Infraestructura verificable para afirmaciones sobre el entorno orbital cerca de la Tierra. "
        "Sin IA · Sin puntuaciones de riesgo · Sin autoridad central."
    )

    tab_map, tab_cases, tab_verify, tab_about = st.tabs([
        "🌍  Mapa orbital",
        "📋  Casos de referencia",
        "🔍  Verificar un caso",
        "ℹ️  Sobre el proyecto",
    ])

    with tab_map:
        _page_map()
    with tab_cases:
        _page_cases()
    with tab_verify:
        _page_verify()
    with tab_about:
        _page_about()


if __name__ == "__main__":
    main()
