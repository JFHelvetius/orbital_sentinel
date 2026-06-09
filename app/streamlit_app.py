"""Orbital Sentinel — interfaz web profesional.

Cuatro pestañas:
  🌍 Mapa orbital     — globo interactivo con trazas de órbita en tiempo de época.
  📋 Casos            — evidencias, scatter de conjunciones, descarga del caso.
  🔍 Verificar        — sube cualquier case.json y audita la cadena hash.
  ℹ️  Sobre            — cómo funciona, filosofía, enlaces.

Streamlit Cloud: importa orbital_sentinel desde src/ del repo clonado.
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
from sgp4.api import jday as _jday

from orbital_sentinel.analytics.investigations.models import InvestigationCase
from orbital_sentinel.analytics.investigations.verifier import verify_investigation_case

# ─────────────────────────────────────────────────────────────────────────────
# Constantes de dominio
# ─────────────────────────────────────────────────────────────────────────────

_ROOT   = Path(__file__).parent.parent
_CASES  = _ROOT / "reference_cases"
EARTH_R = 6371.0

_NAMES: dict[int, str] = {
    25544: "ISS",            36086: "Poisk",
    48274: "CSS Tianhe",     49044: "Nauka",
    49271: "Fregat Deb",     53239: "Wentian",
    54216: "Mengtian",       66052: "HRC Camera",
    66515: "SZ-21 Module",   66664: "Soyuz-MS 28",
    66906: "Duplex",         66912: "ISS Object XY",
    67683: "KNACKSAT-2",     67684: "CORAL",
    67685: "GXIBA-1",        67686: "UITMSAT-2",
    67687: "LEOPARD",        67688: "HMU-SAT2",
    67796: "Crew Dragon 12", 68319: "Progress-MS 33",
    68689: "Cygnus NG-24",   68837: "Progress-MS 34",
    69049: "Tianzhou-10",    69103: "Dragon CRS-34",
    69180: "Shenzhou-23",
}
_ISS_DOCK: set[int] = {
    25544, 36086, 49044, 66052, 66515, 66664,
    66906, 66912, 67796, 68319, 68689,
}
_CSS_DOCK: set[int] = {48274, 53239, 54216, 49271, 69049, 69180}

_CASE_META = {
    "iss_conjunction_001": {
        "title": "ISS  ·  NORAD 25544",
        "icon": "🛰️",
        "summary": "9 evidencias · 1 acercamiento real",
        "highlight": "HMU-SAT2 a 46.91 km · TCA 14 Jun 2026",
        "color": "#ffd700",
    },
    "tiangong_conjunction_002": {
        "title": "CSS Tianhe  ·  NORAD 48274",
        "icon": "🚀",
        "summary": "6 evidencias · 2 acercamientos reales",
        "highlight": "HMU-SAT2 aparece en ambos casos",
        "color": "#ff6b6b",
    },
}

# ─────────────────────────────────────────────────────────────────────────────
# CSS global
# ─────────────────────────────────────────────────────────────────────────────

_CSS = """
<style>
/* Fondo degradado espacial */
.stApp { background: linear-gradient(160deg,#050810 0%,#07091a 55%,#0a0e20 100%) !important; }

/* Hero */
.hero { padding:2rem 0 1.5rem; }
.hero h1 { font-size:2.6rem; font-weight:800; letter-spacing:-1px;
           background:linear-gradient(90deg,#e8edf5 0%,#4f9eff 100%);
           -webkit-background-clip:text; -webkit-text-fill-color:transparent; margin:0; }
.hero p  { color:#8892a4; font-size:1.05rem; margin:.4rem 0 0; }

/* Cards de caso */
.case-card { border:1px solid rgba(100,140,255,.18); border-radius:14px;
             background:rgba(255,255,255,.04); padding:1.4rem 1.4rem 1rem;
             transition:border .2s; cursor:default; }
.case-card:hover { border-color:rgba(100,140,255,.4); }
.case-card .cc-icon { font-size:2rem; margin-bottom:.5rem; }
.case-card .cc-title { font-size:1.1rem; font-weight:700; color:#e8edf5; }
.case-card .cc-summary { color:#8892a4; font-size:.88rem; margin:.3rem 0 .25rem; }
.case-card .cc-highlight { color:#ffd700; font-size:.85rem; font-weight:600; }

/* Stat chips */
.stat-row { display:flex; gap:1rem; margin:1.2rem 0 .8rem; flex-wrap:wrap; }
.stat-chip { display:flex; flex-direction:column; align-items:center;
             background:rgba(79,158,255,.08); border:1px solid rgba(79,158,255,.2);
             border-radius:10px; padding:.6rem 1.2rem; min-width:120px; }
.stat-chip .sv { font-size:1.5rem; font-weight:700; color:#4f9eff; }
.stat-chip .sl { font-size:.75rem; color:#8892a4; margin-top:.15rem; text-align:center; }

/* Cadena hash */
.chain-wrap { display:flex; align-items:center; flex-wrap:wrap; gap:.4rem;
              padding:1rem; background:rgba(0,0,0,.25); border-radius:10px;
              border:1px solid rgba(79,158,255,.12); }
.chain-node { display:flex; flex-direction:column; align-items:center;
              background:rgba(79,158,255,.1); border:1px solid rgba(79,158,255,.25);
              border-radius:8px; padding:.45rem .7rem; min-width:100px; }
.chain-node.ok  { border-color:rgba(46,213,115,.4);  background:rgba(46,213,115,.07); }
.chain-node.err { border-color:rgba(255,71,87,.4);   background:rgba(255,71,87,.07);  }
.cn-label { font-size:.7rem; color:#8892a4; text-align:center; }
.cn-hash  { font-size:.65rem; color:#4f9eff; font-family:monospace; }
.cn-badge { font-size:.8rem; margin-top:.2rem; }
.chain-arrow { color:#4a5568; font-size:1.2rem; }

/* Alerta de conjunción */
.conj-alert { display:flex; align-items:center; gap:1rem;
              border:1px solid rgba(255,71,87,.35); border-radius:12px;
              background:rgba(255,71,87,.08); padding:.9rem 1.2rem;
              margin:.5rem 0; }
.conj-alert .ca-val { font-size:1.6rem; font-weight:800; color:#ff4757; }
.conj-alert .ca-label { font-size:.8rem; color:#8892a4; }
.conj-alert .ca-name  { font-size:1rem; font-weight:600; color:#e8edf5; }

/* Sección "Cómo funciona" */
.how-grid { display:grid; grid-template-columns:repeat(3,1fr); gap:1rem; margin:1rem 0; }
.how-card { border:1px solid rgba(100,140,255,.18); border-radius:12px;
            background:rgba(255,255,255,.03); padding:1.2rem; }
.how-num  { font-size:2rem; font-weight:800; color:#4f9eff; margin-bottom:.5rem; }
.how-title{ font-size:1rem; font-weight:700; color:#e8edf5; margin-bottom:.4rem; }
.how-body { font-size:.85rem; color:#8892a4; line-height:1.5; }

/* Ocultar header por defecto de Streamlit */
#MainMenu, footer, header { visibility:hidden; }
</style>
"""

# ─────────────────────────────────────────────────────────────────────────────
# Helpers de dominio
# ─────────────────────────────────────────────────────────────────────────────

def _name(norad: int) -> str:
    return _NAMES.get(norad, f"NORAD {norad}")

def _label(norad: int) -> str:
    n = _NAMES.get(norad)
    return f"{n} ({norad})" if n else str(norad)

def _short(h: str, n: int = 10) -> str:
    return h[:n] + "…"

def _list_cases() -> list[str]:
    if not _CASES.exists():
        return []
    return sorted(
        d.name for d in _CASES.iterdir()
        if d.is_dir() and (d / "case.json").exists()
        and d.name != "external_audit_demo"
    )

@st.cache_data(show_spinner=False)
def _load(name: str) -> InvestigationCase:
    return InvestigationCase.model_validate_json(
        (_CASES / name / "case.json").read_text(encoding="utf-8")
    )

def _ev_rows(case: InvestigationCase) -> list[dict[str, Any]]:
    rows = []
    for be in case.evidence_bundle.evidence_payloads:
        ev = be.derived_evidence
        hp = ev.honesty_payload
        if ev.source_detector == "conjunction_detection_v01":
            rows.append({
                "Objeto": _label(int(hp.get("other_norad_cat_id", 0))),
                "TCA (UTC)": ev.event_epoch.strftime("%Y-%m-%d  %H:%M"),
                "Miss (km)": round(float(hp.get("miss_distance_km", 0)), 4),
                "σ (km)": round(float(hp.get("combined_sigma_at_tca_km", 0)), 2),
                "Refinado": "✓" if hp.get("tca_was_refined") else "—",
                "evidence_id": _short(ev.evidence_id, 10),
            })
    return sorted(rows, key=lambda r: r["Miss (km)"])

# ─────────────────────────────────────────────────────────────────────────────
# Orbital map helpers
# ─────────────────────────────────────────────────────────────────────────────

class SatTrack(NamedTuple):
    norad: int
    name: str
    lats: list[float | None]
    lons: list[float | None]
    lat0: float
    lon0: float
    alt0: float

def _gmst_rad(jd: float) -> float:
    t = (jd - 2451545.0) / 36525.0
    d = (280.46061837 + 360.98564736629*(jd-2451545.0)
         + 0.000387933*t*t - t*t*t/38710000.0) % 360.0
    return math.radians(d)

def _teme_latlon(x: float, y: float, z: float, jd: float) -> tuple[float, float, float]:
    th = _gmst_rad(jd)
    ex = x*math.cos(th) + y*math.sin(th)
    ey = -x*math.sin(th) + y*math.cos(th)
    r  = math.sqrt(ex*ex + ey*ey + z*z)
    lat = math.degrees(math.asin(z / r))
    lon = math.degrees(math.atan2(ey, ex))
    if lon > 180:  lon -= 360
    if lon < -180: lon += 360
    return lat, lon, r - EARTH_R

def _epoch_dt(sat: Satrec) -> datetime:
    jd = sat.jdsatepoch + sat.jdsatepochF
    return datetime(2000,1,1,12,tzinfo=timezone.utc) + timedelta(days=jd-2451545.0)

def _parse_blocks(text: str) -> list[tuple[str,str,str]]:
    lines = [l.rstrip() for l in text.splitlines() if l.strip()]
    out = []
    for i in range(0, len(lines)-2, 3):
        n, l1, l2 = lines[i], lines[i+1], lines[i+2]
        if l1.startswith("1 ") and l2.startswith("2 "):
            out.append((n.strip(), l1, l2))
    return out

@st.cache_data(show_spinner=False)
def _tracks(case_name: str) -> list[SatTrack]:
    blob = next((_CASES / case_name / "cache" / "blobs").rglob("*.bin"), None)
    if blob is None:
        return []
    blocks = _parse_blocks(blob.read_text(encoding="utf-8"))
    ref = Satrec.twoline2rv(blocks[0][1], blocks[0][2])
    epoch = _epoch_dt(ref)

    result: list[SatTrack] = []
    for name, l1, l2 in blocks:
        sat = Satrec.twoline2rv(l1, l2)
        norad = int(l2.split()[1])
        lats: list[float | None] = []
        lons: list[float | None] = []
        prev_lon: float | None = None

        for m in range(93):
            t  = epoch + timedelta(minutes=m)
            j1, j2 = _jday(t.year,t.month,t.day,t.hour,t.minute,t.second+t.microsecond/1e6)
            e, r, _ = sat.sgp4(j1, j2)
            if e != 0 or r[0] == 0:
                lats.append(None); lons.append(None); prev_lon = None
                continue
            lat, lon, _ = _teme_latlon(r[0],r[1],r[2], j1+j2)
            if prev_lon is not None and abs(lon-prev_lon) > 180:
                lats.append(None); lons.append(None)
            lats.append(lat); lons.append(lon); prev_lon = lon

        j1, j2 = _jday(epoch.year,epoch.month,epoch.day,epoch.hour,epoch.minute,epoch.second)
        _, r0, _ = sat.sgp4(j1, j2)
        if r0[0] != 0:
            lat0, lon0, alt0 = _teme_latlon(r0[0],r0[1],r0[2],j1+j2)
        else:
            lat0, lon0, alt0 = 0.0, 0.0, 400.0

        result.append(SatTrack(norad, _NAMES.get(norad, name), lats, lons, lat0, lon0, alt0))
    return result


def _globe_figure(tracks: list[SatTrack], case: InvestigationCase) -> go.Figure:
    real_norads: set[int] = set()
    for be in case.evidence_bundle.evidence_payloads:
        hp = be.derived_evidence.honesty_payload
        if float(hp.get("miss_distance_km", 0)) > 10:
            real_norads.add(int(hp.get("other_norad_cat_id", 0)))

    primary = case.evidence_bundle.object_id
    fig = go.Figure()

    for t in tracks:
        is_primary  = (t.norad == primary)
        is_real     = (t.norad in real_norads)
        is_iss_dock = (t.norad in _ISS_DOCK and not is_primary)
        is_css_dock = (t.norad in _CSS_DOCK and not is_primary)

        if is_primary:
            lc, mc, lw, ms, sym = "#ffd700","#ffd700", 2.5, 16, "star"
        elif is_real:
            lc, mc, lw, ms, sym = "#ff4757","#ff4757", 2.0, 13, "x"
        elif is_iss_dock:
            lc, mc, lw, ms, sym = "rgba(79,158,255,.35)","rgba(79,158,255,.7)", 1.0, 7, "circle"
        elif is_css_dock:
            lc, mc, lw, ms, sym = "rgba(255,107,107,.35)","rgba(255,107,107,.7)", 1.0, 7, "circle"
        else:
            lc, mc, lw, ms, sym = "rgba(100,200,120,.3)","rgba(130,220,140,.65)", 1.0, 7, "circle"

        # Traza de órbita
        fig.add_trace(go.Scattergeo(
            lat=t.lats, lon=t.lons, mode="lines",
            line=dict(width=lw, color=lc),
            name=t.name, showlegend=True, hoverinfo="skip",
        ))
        # Posición actual
        show_txt = is_primary or is_real
        fig.add_trace(go.Scattergeo(
            lat=[t.lat0], lon=[t.lon0],
            mode="markers+text" if show_txt else "markers",
            marker=dict(size=ms, color=mc, symbol=sym,
                        line=dict(width=1.5 if show_txt else 0, color="white")),
            text=[t.name] if show_txt else [],
            textposition="top right",
            textfont=dict(color="white", size=11, family="sans-serif"),
            name=t.name, showlegend=False,
            hovertemplate=(
                f"<b>{t.name}</b><br>NORAD {t.norad}<br>"
                f"Alt: {t.alt0:.0f} km"
                + ("<br><b>⚠ Acercamiento no cooperativo</b>" if is_real else "")
                + "<extra></extra>"
            ),
        ))

    fig.update_geos(
        projection_type="orthographic",
        showland=True,    landcolor="rgb(38,46,62)",
        showocean=True,   oceancolor="rgb(10,18,42)",
        showlakes=False,  showrivers=False,
        showcoastlines=True, coastlinecolor="rgba(110,130,170,.6)",
        showcountries=True,  countrycolor="rgba(70,85,115,.4)",
        showgraticules=True, graticulecolor="rgba(60,80,130,.2)",
        bgcolor="rgb(7,11,24)",
        framecolor="rgba(79,158,255,.2)",
    )
    fig.update_layout(
        paper_bgcolor="rgb(7,11,24)",
        height=580,
        margin=dict(l=0, r=0, t=36, b=0),
        legend=dict(
            bgcolor="rgba(10,15,35,.9)", bordercolor="rgba(79,158,255,.2)",
            borderwidth=1, font=dict(color="#8892a4", size=10),
            x=1.01, y=1, xanchor="left",
        ),
        title=dict(
            text="Posiciones en época TLE  ·  trazas 90 min  ·  arrastra para rotar",
            font=dict(color="#8892a4", size=12), x=0.01,
        ),
    )
    return fig


def _scatter_figure(rows: list[dict[str, Any]]) -> go.Figure:
    co   = [r for r in rows if r["Miss (km)"] < 5]
    real = [r for r in rows if r["Miss (km)"] >= 5]

    fig = go.Figure()
    if co:
        fig.add_trace(go.Scatter(
            x=[r["Miss (km)"] for r in co],
            y=[r["σ (km)"]    for r in co],
            mode="markers",
            name="Co-orbital",
            marker=dict(size=12, color="rgba(79,158,255,.7)",
                        line=dict(width=1, color="rgba(79,158,255,.3)")),
            text=[r["Objeto"] for r in co],
            hovertemplate="<b>%{text}</b><br>Miss: %{x:.4f} km<br>σ: %{y:.2f} km<extra></extra>",
        ))
    if real:
        fig.add_trace(go.Scatter(
            x=[r["Miss (km)"] for r in real],
            y=[r["σ (km)"]    for r in real],
            mode="markers+text",
            name="Acercamiento real",
            marker=dict(size=18, color="#ff4757", symbol="x",
                        line=dict(width=2.5, color="white")),
            text=[r["Objeto"] for r in real],
            textposition="top right",
            textfont=dict(color="#ff4757", size=11),
            hovertemplate="<b>%{text}</b><br>Miss: %{x:.4f} km<br>σ: %{y:.2f} km<extra></extra>",
        ))

    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        height=320,
        margin=dict(l=50, r=20, t=40, b=50),
        title=dict(text="Distancia mínima vs. incertidumbre σ",
                   font=dict(color="#8892a4", size=13)),
        xaxis=dict(title="Miss distance (km)", color="#8892a4",
                   gridcolor="rgba(79,158,255,.1)", zerolinecolor="rgba(79,158,255,.2)"),
        yaxis=dict(title="σ combinado (km)", color="#8892a4",
                   gridcolor="rgba(79,158,255,.1)"),
        legend=dict(bgcolor="rgba(0,0,0,0)", font=dict(color="#8892a4", size=11)),
        annotations=[dict(
            x=0.5, y=-0.18, xref="paper", yref="paper", showarrow=False,
            text="El clúster co-orbital (izq) son módulos acoplados. "
                 "El punto aislado (der) es el acercamiento real a verificar.",
            font=dict(color="#4a5568", size=10), align="center",
        )],
    )
    return fig


def _chain_html(case: InvestigationCase, report: Any) -> str:
    nodes = [
        ("Bundle",      case.referenced_bundle_id),
        ("Agent Input", case.referenced_agent_input_id),
        ("Explanation", case.referenced_explanation_id),
        ("Claims",      case.referenced_claim_registry_id),
        ("Hypothesis",  case.referenced_hypothesis_registry_id),
        ("Chain",       case.referenced_chain_id),
        ("Case",        case.case_signature),
    ]
    ok = report.is_valid
    parts = []
    for i, (label, h) in enumerate(nodes):
        cls = "ok" if ok else "err"
        badge = "✓" if ok else "✗"
        parts.append(
            f'<div class="chain-node {cls}">'
            f'<span class="cn-label">{label}</span>'
            f'<span class="cn-hash">{h[:8]}…</span>'
            f'<span class="cn-badge">{badge}</span>'
            f'</div>'
        )
        if i < len(nodes) - 1:
            parts.append('<span class="chain-arrow">→</span>')
    return f'<div class="chain-wrap">{"".join(parts)}</div>'


# ─────────────────────────────────────────────────────────────────────────────
# Páginas
# ─────────────────────────────────────────────────────────────────────────────

def _page_map() -> None:
    cases = _list_cases()
    if not cases:
        st.error("No se encontraron casos de referencia."); return

    # ── Selector de caso como cartas ─────────────────────────────────────────
    st.markdown("#### Selecciona el objeto principal")
    cols = st.columns(len(cases))
    if "map_case" not in st.session_state:
        st.session_state["map_case"] = cases[0]

    for col, name in zip(cols, cases):
        meta = _CASE_META.get(name, {})
        with col:
            st.markdown(f"""
<div class="case-card">
  <div class="cc-icon">{meta.get('icon','🛰️')}</div>
  <div class="cc-title">{meta.get('title', name)}</div>
  <div class="cc-summary">{meta.get('summary','')}</div>
  <div class="cc-highlight">{meta.get('highlight','')}</div>
</div>""", unsafe_allow_html=True)
            st.markdown("&nbsp;", unsafe_allow_html=True)
            if st.button(f"Ver este caso", key=f"map_btn_{name}", use_container_width=True):
                st.session_state["map_case"] = name

    selected = st.session_state["map_case"]
    meta = _CASE_META.get(selected, {})

    # ── Glob ─────────────────────────────────────────────────────────────────
    with st.spinner("Propagando órbitas…"):
        try:
            track_list = _tracks(selected)
            case       = _load(selected)
        except Exception as exc:
            st.error(f"Error: {exc}"); return

    # ── Globe ─────────────────────────────────────────────────────────────────
    st.plotly_chart(
        _globe_figure(track_list, case),
        use_container_width=True,
        config={"displayModeBar": True, "scrollZoom": False},
    )

    # ── Métricas de conjunciones ──────────────────────────────────────────────
    real_evs = [
        be for be in case.evidence_bundle.evidence_payloads
        if float(be.derived_evidence.honesty_payload.get("miss_distance_km", 0)) > 10
    ]
    if real_evs:
        st.markdown("**Acercamientos no cooperativos en este caso:**")
        ev_cols = st.columns(max(len(real_evs), 1))
        for col, be in zip(ev_cols, real_evs):
            hp    = be.derived_evidence.honesty_payload
            norad = int(hp.get("other_norad_cat_id", 0))
            miss  = float(hp.get("miss_distance_km", 0))
            tca   = be.derived_evidence.event_epoch.strftime("%Y-%m-%d  %H:%M UTC")
            with col:
                st.markdown(f"""
<div class="conj-alert">
  <div>
    <div class="ca-name">⚠ {_label(norad)}</div>
    <div class="ca-val">{miss:.2f} km</div>
    <div class="ca-label">TCA · {tca}</div>
  </div>
</div>""", unsafe_allow_html=True)

    # ── Stats chips ───────────────────────────────────────────────────────────
    n_obj  = len(track_list)
    n_real = len(real_evs)
    n_ev   = case.evidence_bundle.n_evidence_payloads
    st.markdown(f"""
<div class="stat-row">
  <div class="stat-chip"><span class="sv">{n_obj}</span><span class="sl">Objetos rastreados</span></div>
  <div class="stat-chip"><span class="sv">{n_ev}</span><span class="sl">Evidencias totales</span></div>
  <div class="stat-chip"><span class="sv" style="color:#ff4757">{n_real}</span><span class="sl">Acercamientos reales</span></div>
  <div class="stat-chip"><span class="sv" style="color:#2ed573">✓</span><span class="sl">Cadena verificada</span></div>
</div>""", unsafe_allow_html=True)


def _page_cases() -> None:
    cases = _list_cases()
    if not cases:
        st.error("No se encontraron casos."); return

    options = {_CASE_META.get(c, {}).get("title", c): c for c in cases}
    label   = st.selectbox("Caso:", list(options.keys()), key="cases_sel")
    selected = options[label]

    with st.spinner("Cargando…"):
        try:
            case = _load(selected)
        except Exception as exc:
            st.error(f"Error: {exc}"); return

    # ── Header del caso ───────────────────────────────────────────────────────
    report = verify_investigation_case(case)
    c_info, c_dl = st.columns([4, 1])
    with c_info:
        st.markdown(f"#### {_label(case.evidence_bundle.object_id)}")
        st.caption(
            f"case\\_id: `{_short(case.case_id, 16)}`  ·  "
            f"{case.derived_at.strftime('%Y-%m-%d %H:%M UTC')}  ·  "
            f"{case.evidence_bundle.n_evidence_payloads} evidencias"
        )
    with c_dl:
        st.download_button(
            "⬇ case.json",
            data=(_CASES / selected / "case.json").read_bytes(),
            file_name=f"{selected}_case.json",
            mime="application/json",
            use_container_width=True,
            help="Descarga y sube en 'Verificar' para auditar la cadena.",
        )

    if report.is_valid:
        st.success(f"✓ Cadena íntegra · {report.n_artifacts_verified} artefactos verificados", icon="🔒")
    else:
        st.error(f"✗ {report.n_findings} fallo(s) en la cadena", icon="⚠️")

    for hyp in case.hypothesis_registry.hypotheses:
        st.info(f"**Hipótesis:** {hyp.hypothesis_label}", icon="📋")

    # ── Scatter + Tabla ───────────────────────────────────────────────────────
    rows = _ev_rows(case)
    st.plotly_chart(_scatter_figure(rows), use_container_width=True, config={"displayModeBar": False})

    df = pd.DataFrame(rows)
    def _color(row: pd.Series) -> list[str]:
        m = row["Miss (km)"]
        if m > 10:  return ["background-color:rgba(255,71,87,.12);color:#ff4757;font-weight:bold"]*len(row)
        if m > 1:   return ["background-color:rgba(79,158,255,.06)"]*len(row)
        return ["color:#4a5568"]*len(row)
    st.dataframe(df.style.apply(_color, axis=1), use_container_width=True, hide_index=True)

    # ── Cadena de custodia ────────────────────────────────────────────────────
    with st.expander("🔗 Cadena de custodia criptográfica", expanded=False):
        st.markdown(_chain_html(case, report), unsafe_allow_html=True)
        st.caption(
            "Cada hash se computa sobre el contenido del artefacto anterior. "
            "Si cualquier byte fue modificado, el hash siguiente no coincide."
        )

    with st.expander("📄 Texto de explicación (verbatim, determinístico)", expanded=False):
        st.code(case.explanation_artifact.explanation_text, language=None)


def _page_verify() -> None:
    st.markdown("""
**Sube cualquier `case.json`** producido por Orbital Sentinel.
La verificación ejecuta los mismos verifiers que CI y **no envía ningún dato fuera de tu máquina**.
""")

    uploaded = st.file_uploader(
        "Arrastra aquí tu case.json",
        type=["json"], key="verify_upload",
        help="Descárgalo desde la pestaña 'Casos de referencia'.",
    )

    if not uploaded:
        st.info(
            "👆 Descarga un caso desde la pestaña **Casos de referencia** "
            "usando el botón ⬇ case.json y súbelo aquí.",
            icon="ℹ️",
        )
        return

    with st.spinner("Verificando…"):
        raw = uploaded.read().decode("utf-8")
        try:
            case = InvestigationCase.model_validate_json(raw)
        except Exception as exc:
            st.error(f"Archivo inválido: `{exc}`"); return
        report = verify_investigation_case(case)

    # ── Resultado prominente ──────────────────────────────────────────────────
    if report.is_valid:
        st.markdown("""
<div style="border:1px solid rgba(46,213,115,.4); border-radius:14px;
            background:rgba(46,213,115,.08); padding:1.4rem 1.8rem; margin:.5rem 0;">
  <div style="font-size:2.2rem;font-weight:800;color:#2ed573;">✓ Cadena íntegra</div>
  <div style="color:#8892a4;font-size:.95rem;margin-top:.3rem;">
    Todos los artefactos verificados · La cadena SHA-256 no ha sido alterada.
  </div>
</div>""", unsafe_allow_html=True)
    else:
        st.markdown(f"""
<div style="border:1px solid rgba(255,71,87,.4); border-radius:14px;
            background:rgba(255,71,87,.08); padding:1.4rem 1.8rem; margin:.5rem 0;">
  <div style="font-size:2.2rem;font-weight:800;color:#ff4757;">✗ Cadena rota</div>
  <div style="color:#8892a4;font-size:.95rem;margin-top:.3rem;">
    {report.n_findings} fallo(s) encontrado(s) — los datos pueden haber sido modificados.
  </div>
</div>""", unsafe_allow_html=True)
        for f in report.findings:
            st.warning(
                f"`{f.finding_type}`  \n"
                f"Esperado `{f.expected[:28]}…`  →  Obtenido `{f.actual[:28]}…`"
            )

    st.divider()
    st.markdown("**Diagrama de cadena de custodia:**")
    st.markdown(_chain_html(case, report), unsafe_allow_html=True)
    st.divider()

    # ── Contenido del caso ────────────────────────────────────────────────────
    st.markdown(f"#### {_label(case.evidence_bundle.object_id)}")
    st.caption(
        f"case\\_id: `{_short(case.case_id, 16)}`  ·  "
        f"{case.derived_at.strftime('%Y-%m-%d %H:%M UTC')}"
    )
    for hyp in case.hypothesis_registry.hypotheses:
        st.info(f"**Hipótesis:** {hyp.hypothesis_label}", icon="📋")

    rows = _ev_rows(case)
    if rows:
        st.plotly_chart(_scatter_figure(rows), use_container_width=True,
                        config={"displayModeBar": False})

    with st.expander("Reporte completo (JSON)", expanded=False):
        st.json(report.model_dump(mode="json"))


def _page_about() -> None:
    st.markdown("""
**Orbital Sentinel** es infraestructura pública para afirmaciones verificables
sobre el entorno orbital cercano a la Tierra. Cualquier persona —
sin acceso privilegiado, sin autoridad, sin necesidad de confiar en nadie —
puede producir, verificar y disputar lo que ocurre en órbita.
""")

    st.markdown("""
<div class="how-grid">
  <div class="how-card">
    <div class="how-num">①</div>
    <div class="how-title">Ingesta de fuentes públicas</div>
    <div class="how-body">
      Descarga TLEs de CelesTrak y registra el SHA-256 de los bytes recibidos.
      Cualquier cambio posterior es detectable — los datos originales quedan anclados.
    </div>
  </div>
  <div class="how-card">
    <div class="how-num">②</div>
    <div class="how-title">Análisis con incertidumbre declarada</div>
    <div class="how-body">
      Propagación SGP4, detección de conjunciones, maniobras y anomalías.
      Cada resultado incluye los campos de honestidad del detector.
      Sin IA. Sin puntuaciones de riesgo. Solo geometría.
    </div>
  </div>
  <div class="how-card">
    <div class="how-num">③</div>
    <div class="how-title">Cadena hash end-to-end</div>
    <div class="how-body">
      Cada artefacto lleva el hash del anterior: Bundle → Agent Input → Explanation →
      Claims → Hypothesis → Chain → Case. Rompe un eslabón y la cadena falla.
      Verificable offline por cualquiera.
    </div>
  </div>
</div>
""", unsafe_allow_html=True)

    st.markdown("---")
    c1, c2, c3 = st.columns(3)
    with c1: st.link_button("⭐ Código en GitHub",
                             "https://github.com/JFHelvetius/orbital_sentinel",
                             use_container_width=True)
    with c2: st.link_button("📦 Instalar desde PyPI",
                             "https://pypi.org/project/orbital-sentinel/",
                             use_container_width=True)
    with c3: st.link_button("📖 Por qué existe este proyecto",
                             "https://github.com/JFHelvetius/orbital_sentinel/blob/main/docs/why-this-exists.md",
                             use_container_width=True)
    st.caption("Apache 2.0 · Sin IA · Datos: CelesTrak (fuente pública)")


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    st.set_page_config(
        page_title="Orbital Sentinel",
        page_icon="🛰️",
        layout="wide",
        initial_sidebar_state="collapsed",
        menu_items={
            "Get Help":   "https://github.com/JFHelvetius/orbital_sentinel/discussions",
            "Report a bug": "https://github.com/JFHelvetius/orbital_sentinel/issues",
            "About": "Orbital Sentinel — infraestructura verificable para afirmaciones orbitales · Apache 2.0",
        },
    )
    st.markdown(_CSS, unsafe_allow_html=True)

    # ── Hero ──────────────────────────────────────────────────────────────────
    st.markdown("""
<div class="hero">
  <h1>Orbital Sentinel</h1>
  <p>Infraestructura verificable para afirmaciones sobre el entorno orbital · Sin IA · Sin autoridad central</p>
</div>""", unsafe_allow_html=True)

    tab_map, tab_cases, tab_verify, tab_about = st.tabs([
        "🌍  Mapa orbital",
        "📋  Casos de referencia",
        "🔍  Verificar un caso",
        "ℹ️  Sobre el proyecto",
    ])
    with tab_map:    _page_map()
    with tab_cases:  _page_cases()
    with tab_verify: _page_verify()
    with tab_about:  _page_about()


if __name__ == "__main__":
    main()
