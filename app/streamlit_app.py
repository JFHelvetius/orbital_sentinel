"""Orbital Sentinel — interfaz web profesional.

Build: v0.1.2 · dashboard layout · realistic globe · Inter typography.

Cuatro pestañas:
  🌍 Mapa orbital     — globo interactivo con trazas de órbita en tiempo de época.
  📋 Casos            — evidencias, scatter de conjunciones, descarga del caso.
  🔍 Verificar        — sube cualquier case.json y audita la cadena hash.
  ℹ️  Sobre            — cómo funciona, filosofía, enlaces.

Streamlit Cloud: importa orbital_sentinel desde src/ del repo clonado.
"""

from __future__ import annotations

import math
import ssl
import sys
import urllib.request
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
# TLE de referencia embebidos (CelesTrak stations, época 2026-06-07/08)
# Usados cuando el cache/blobs no está en el repo (Streamlit Cloud).
# ─────────────────────────────────────────────────────────────────────────────

_TLE_STATIONS = """\
ISS (ZARYA)
1 25544U 98067A   26158.90128688  .00007994  00000+0  14961-3 0  9996
2 25544  51.6338 346.0598 0006926 145.2709 214.8733 15.49660544570312
POISK
1 36086U 09060A   26158.90128688  .00007994  00000+0  14961-3 0  9994
2 36086  51.6338 346.0598 0006926 145.2709 214.8733 15.49660544570359
CSS (TIANHE)
1 48274U 21035A   26159.08188283  .00025465  00000+0  30374-3 0  9998
2 48274  41.4696  17.3987 0008702   5.5904 354.5031 15.60427341291749
ISS (NAUKA)
1 49044U 21066A   26158.90128688  .00007994  00000+0  14961-3 0  9992
2 49044  51.6338 346.0598 0006926 145.2709 214.8733 15.49660544570357
FREGAT DEB
1 49271U 11037PF  26151.14915702  .00018955  00000+0  30994-1 0  9992
2 49271  51.6227  53.0895 0914379 245.3590 104.9405 12.41880577222933
CSS (WENTIAN)
1 53239U 22085A   26159.08188283  .00025465  00000+0  30374-3 0  9991
2 53239  41.4696  17.3987 0008702   5.5904 354.5031 15.60427341288236
CSS (MENGTIAN)
1 54216U 22143A   26159.08188283  .00025465  00000+0  30374-3 0  9992
2 54216  41.4696  17.3987 0008702   5.5904 354.5031 15.60427341292158
HRC MONOBLOCK CAMERA
1 66052U 98067XR  26158.73746098  .00076529  00000+0  55774-3 0  9994
2 66052  51.6266 327.6637 0001454 182.7303 177.3688 15.72605662 36514
SZ-21 MODULE
1 66515U 25246C   26157.31606433  .00056445  00000+0  36002-3 0  9996
2 66515  41.4728  14.9847 0007184 283.9983  76.0062 15.75457395 32025
SOYUZ-MS 28
1 66664U 25275A   26158.90128688  .00007994  00000+0  14961-3 0  9995
2 66664  51.6338 346.0598 0006926 145.2709 214.8733 15.49660544570354
DUPLEX
1 66906U 98067XS  26158.77704526  .00040528  00000+0  46053-3 0  9996
2 66906  51.6281 336.9694 0004226 163.6622 196.4509 15.61898303 29180
ISS OBJECT XY
1 66912U 98067XY  26158.70071378  .00325324  50593-4  10139-2 0  9990
2 66912  51.6203 324.3260 0007317 272.0274  87.9894 15.91000080 29331
KNACKSAT-2
1 67683U 98067XZ  26158.80293921  .00048726  00000+0  61258-3 0  9997
2 67683  51.6303 341.6515 0010362 174.2130 185.8984 15.59121118 18810
CORAL
1 67684U 98067YA  26159.18707238  .00155474  00000+0  10798-2 0  9992
2 67684  51.6253 334.4321 0009761 198.6171 161.4472 15.73360701 18941
GXIBA-1
1 67685U 98067YB  26158.75031954  .00052644  00000+0  62566-3 0  9996
2 67685  51.6294 341.2956 0011540 172.2654 187.8520 15.60548421 18814
UITMSAT-2
1 67686U 98067YC  26158.78069590  .00076518  00000+0  80948-3 0  9997
2 67686  51.6286 339.9975 0007475 162.8307 197.2942 15.63441273 18838
LEOPARD
1 67687U 98067YD  26159.22115794  .00045479  00000+0  55311-3 0  9994
2 67687  51.6314 339.2020 0007757 156.5041 203.6308 15.60052341 18809
HMU-SAT2
1 67688U 98067YE  26159.20931596  .00057867  00000+0  64721-3 0  9998
2 67688  51.6310 338.3693 0007486 158.9337 201.1967 15.62130581 18815
CREW DRAGON 12
1 67796U 26031A   26158.90128673  .00006825  00000+0  12894-3 0  9992
2 67796  51.6338 346.0598 0006929 145.2520 214.8923 15.49658997570355
PROGRESS-MS 33
1 68319U 26058A   26158.90128688  .00007994  00000+0  14961-3 0  9994
2 68319  51.6338 346.0598 0006926 145.2709 214.8733 15.49660544570353
CYGNUS NG-24
1 68689U 26079A   26158.90128673  .00006825  00000+0  12894-3 0  9996
2 68689  51.6338 346.0598 0006929 145.2520 214.8923 15.49658997570357
PROGRESS-MS 34
1 68837U 26093A   26158.90128673  .00006825  00000+0  12894-3 0  9997
2 68837  51.6338 346.0598 0006929 145.2520 214.8923 15.49658997570352
TIANZHOU-10
1 69049U 26102A   26159.08188283  .00025465  00000+0  30374-3 0  9991
2 69049  41.4696  17.3987 0008702   5.5904 354.5031 15.60427341  4531
DRAGON CRS-34
1 69103U 26107A   26158.90128688  .00007994  00000+0  14961-3 0  9991
2 69103  51.6338 346.0598 0006926 145.2709 214.8733 15.49660544570355
SHENZHOU-23 (SZ-23)
1 69180U 26113A   26159.08188283  .00025465  00000+0  30374-3 0  9999
2 69180  41.4696  17.3987 0008702   5.5904 354.5031 15.60427341291883
"""

# ─────────────────────────────────────────────────────────────────────────────
# CSS global
# ─────────────────────────────────────────────────────────────────────────────

_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');

/* ── Design tokens (sophisticated dark navy, no pitch black) ───────────── */
:root {
  --bg-app:        #0d1220;
  --bg-panel:      #151b2c;
  --bg-card:       #1a2236;
  --bg-elevated:   #212a40;
  --bg-input:      #11172a;
  --border-soft:   rgba(160,180,220,.08);
  --border:        rgba(160,180,220,.14);
  --border-strong: rgba(160,180,220,.22);
  --text-pri:      #e8eef7;
  --text-sec:      #94a3b8;
  --text-ter:      #64748b;
  --accent:        #4a90e2;
  --accent-bri:    #5fa8f5;
  --success:       #10b981;
  --warning:       #f59e0b;
  --danger:        #ef4444;
  --info:          #06b6d4;
}

/* ── Base ──────────────────────────────────────────────────────────────── */
html, body, [class*="st-"], [class*="css-"] {
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif !important;
}
.stApp {
  background: var(--bg-app) !important;
  color: var(--text-pri);
}
.stApp, .main, .block-container,
[data-testid="stMain"],
[data-testid="stMainBlockContainer"],
[data-testid="stAppViewContainer"] {
  background: var(--bg-app) !important;
}
h1,h2,h3,h4,h5,h6 { color: var(--text-pri); letter-spacing:-.01em; font-weight:600; }
p, span, div, label { color: var(--text-pri); }
hr, [data-testid="stMarkdownContainer"] hr { border-color: var(--border) !important; opacity:.6; }
code, pre { font-family: 'JetBrains Mono', 'SF Mono', Consolas, monospace !important; }

/* ── Hero refinado ─────────────────────────────────────────────────────── */
.hero {
  padding: 1.4rem 0 1.2rem;
  border-bottom: 1px solid var(--border-soft);
  margin-bottom: 1.3rem;
  display: flex; align-items: baseline; gap: 1.2rem;
}
.hero h1 {
  font-size: 1.65rem; font-weight: 700; letter-spacing:-.02em; margin: 0;
  color: var(--text-pri);
}
.hero h1 .pill {
  display:inline-block; font-size:.65rem; font-weight:600;
  background:rgba(74,144,226,.12); color:var(--accent-bri);
  border:1px solid rgba(74,144,226,.25); border-radius:4px;
  padding:.15rem .5rem; margin-left:.6rem; letter-spacing:.05em;
  text-transform:uppercase; vertical-align:middle;
}
.hero p {
  color: var(--text-sec); font-size: .82rem; margin: 0;
  letter-spacing: .005em;
}

/* ── Tabs ──────────────────────────────────────────────────────────────── */
.stTabs [data-baseweb="tab-list"] {
  background: transparent !important;
  border-bottom: 1px solid var(--border) !important;
  gap: .25rem;
}
.stTabs [data-baseweb="tab"] {
  background: transparent !important;
  color: var(--text-sec) !important;
  font-size: .82rem !important;
  font-weight: 500 !important;
  padding: .55rem 1rem !important;
  border-radius: 6px 6px 0 0 !important;
  border-bottom: 2px solid transparent !important;
  transition: all .15s !important;
}
.stTabs [data-baseweb="tab"]:hover {
  color: var(--text-pri) !important;
  background: rgba(255,255,255,.025) !important;
}
.stTabs [data-baseweb="tab"][aria-selected="true"] {
  color: var(--accent-bri) !important;
  border-bottom-color: var(--accent-bri) !important;
  background: rgba(74,144,226,.06) !important;
}

/* ── Cards de caso (estilo Linear/Vercel) ──────────────────────────────── */
.case-card {
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--bg-card);
  padding: 1rem 1.1rem .9rem;
  transition: all .15s;
}
.case-card:hover { border-color: var(--border-strong); background: var(--bg-elevated); }
.case-card .cc-icon { font-size:1.4rem; margin-bottom:.4rem; opacity:.85; }
.case-card .cc-title { font-size:.92rem; font-weight:600; color: var(--text-pri); }
.case-card .cc-summary { color: var(--text-ter); font-size:.78rem; margin:.25rem 0 .2rem; }
.case-card .cc-highlight { color: var(--warning); font-size:.76rem; font-weight:500; }

/* ── Stat chips (numéricos compactos) ──────────────────────────────────── */
.stat-row { display:flex; gap:.6rem; margin:.9rem 0 .6rem; flex-wrap:wrap; }
.stat-chip {
  display:flex; align-items:center; justify-content:space-between;
  background: var(--bg-card); border: 1px solid var(--border);
  border-radius: 6px; padding: .5rem .75rem; min-width: 0;
  transition: border-color .15s; gap: .5rem;
}
.stat-chip:hover { border-color: var(--border-strong); }
.stat-chip .sv {
  font-size: 1.05rem; font-weight: 600; color: var(--text-pri);
  font-family: 'JetBrains Mono', monospace; letter-spacing:-.02em;
}
.stat-chip .sl {
  font-size:.66rem; color: var(--text-ter);
  text-transform: uppercase; letter-spacing:.07em; font-weight:500;
}

/* ── Cadena hash ───────────────────────────────────────────────────────── */
.chain-wrap {
  display:flex; align-items:center; flex-wrap:wrap; gap:.4rem;
  padding: 1rem; background: var(--bg-card); border-radius: 8px;
  border: 1px solid var(--border);
}
.chain-node {
  display:flex; flex-direction:column; align-items:center;
  background: var(--bg-elevated); border: 1px solid var(--border);
  border-radius: 6px; padding: .45rem .65rem; min-width: 95px;
}
.chain-node.ok  { border-color: rgba(16,185,129,.35); background: rgba(16,185,129,.05); }
.chain-node.err { border-color: rgba(239,68,68,.35);  background: rgba(239,68,68,.05);  }
.cn-label { font-size:.65rem; color: var(--text-ter); text-transform:uppercase; letter-spacing:.05em; }
.cn-hash  { font-size:.62rem; color: var(--accent-bri); font-family:'JetBrains Mono',monospace; }
.cn-badge { font-size:.78rem; margin-top:.15rem; }
.chain-arrow { color: var(--text-ter); font-size:1rem; opacity:.5; }

/* ── Alertas (conjunción y proximidad) ────────────────────────────────── */
.conj-alert {
  display:flex; align-items:center; gap:1rem;
  border: 1px solid rgba(239,68,68,.3); border-radius: 8px;
  background: rgba(239,68,68,.05); padding: .85rem 1.1rem; margin: .4rem 0;
}
.conj-alert .ca-val { font-size: 1.4rem; font-weight: 700; color: var(--danger); font-family: 'JetBrains Mono', monospace; }
.conj-alert .ca-label { font-size:.72rem; color: var(--text-ter); text-transform:uppercase; letter-spacing:.05em; }
.conj-alert .ca-name { font-size:.9rem; font-weight:600; color: var(--text-pri); }

.prox-badge {
  display: flex; align-items: center; gap: .5rem;
  background: rgba(6,182,212,.05);
  border: 1px solid rgba(6,182,212,.25);
  border-radius: 6px; padding: .5rem .85rem; margin: .25rem 0;
}
.prox-badge .pb-name { color: var(--info); font-weight: 600; font-size: .85rem; }
.prox-badge .pb-detail { color: var(--text-ter); font-size:.75rem; }

/* ── How-it-works grid ─────────────────────────────────────────────────── */
.how-grid { display:grid; grid-template-columns:repeat(3,1fr); gap:1rem; margin:1rem 0; }
.how-card {
  border: 1px solid var(--border); border-radius: 8px;
  background: var(--bg-card); padding: 1.2rem 1.3rem;
}
.how-num  { font-size:1.6rem; font-weight:700; color: var(--accent); margin-bottom:.4rem; font-family:'JetBrains Mono',monospace; }
.how-title{ font-size:.95rem; font-weight:600; color: var(--text-pri); margin-bottom:.35rem; }
.how-body { font-size:.82rem; color: var(--text-sec); line-height:1.55; }

/* ── Inputs (compactos y elegantes) ───────────────────────────────────── */
[data-testid="stTextInput"] input,
[data-testid="stTextArea"] textarea {
  background: var(--bg-input) !important;
  color: var(--text-pri) !important;
  border: 1px solid var(--border) !important;
  border-radius: 6px !important;
  font-size: .85rem !important;
  font-family: 'Inter', sans-serif !important;
}
[data-testid="stTextInput"] input:focus,
[data-testid="stTextArea"] textarea:focus {
  border-color: var(--accent) !important;
  box-shadow: 0 0 0 3px rgba(74,144,226,.12) !important;
  outline: none !important;
}
[data-testid="stTextInput"] input::placeholder { color: var(--text-ter) !important; }

/* Radio buttons */
[data-testid="stRadio"] label, [data-testid="stRadio"] > div { color: var(--text-pri) !important; }
[data-testid="stRadio"] > div[role="radiogroup"] { gap: .35rem !important; }

/* Sliders */
.stSlider [data-baseweb="slider"] [role="slider"] {
  background: var(--accent) !important;
  border: 2px solid var(--bg-app) !important;
}

/* Toggles */
[data-testid="stToggle"] label { color: var(--text-pri) !important; font-size:.83rem !important; }

/* Captions */
[data-testid="stCaptionContainer"], .stCaption {
  color: var(--text-ter) !important; font-size:.75rem !important;
}

/* ── Botones ───────────────────────────────────────────────────────────── */
button[kind="secondary"], button[data-testid*="baseButton-secondary"] {
  background: var(--bg-card) !important;
  color: var(--text-pri) !important;
  border: 1px solid var(--border) !important;
  border-radius: 6px !important;
  font-size: .83rem !important;
  font-weight: 500 !important;
  padding: .4rem .85rem !important;
  transition: all .15s !important;
}
button[kind="secondary"]:hover {
  background: var(--bg-elevated) !important;
  border-color: var(--accent) !important;
  color: var(--accent-bri) !important;
}

/* ── Expanders (mínimo, sin tocar el chevron) ──────────────────────────── */
.stExpander {
  border: 1px solid var(--border);
  border-radius: 8px;
  margin: .8rem 0;
}

/* ── DataFrame ─────────────────────────────────────────────────────────── */
[data-testid="stDataFrame"] {
  background: var(--bg-card) !important;
  border: 1px solid var(--border) !important;
  border-radius: 8px !important;
  overflow: hidden;
}
[data-testid="stDataFrame"] table { background: var(--bg-card) !important; }
[data-testid="stDataFrame"] thead th {
  background: var(--bg-panel) !important;
  color: var(--text-sec) !important;
  text-transform: uppercase !important;
  font-size: .7rem !important;
  letter-spacing: .05em !important;
  font-weight: 600 !important;
}

/* ── Globo: marco mínimo (sin tocar el SVG interno) ────────────────────── */
[data-testid="stPlotlyChart"] {
  border: 1px solid var(--border);
  border-radius: 10px;
}

/* ── Panel lateral de control ──────────────────────────────────────────── */
.ctrl-section { margin-bottom: .9rem; }
.ctrl-title {
  font-size: .65rem;
  text-transform: uppercase;
  letter-spacing: .09em;
  color: var(--text-ter);
  margin: 1rem 0 .4rem;
  font-weight: 600;
}
.live-clock {
  font-family: 'JetBrains Mono', monospace;
  font-size: .82rem; color: var(--accent-bri);
  padding: .55rem .8rem;
  background: var(--bg-card); border: 1px solid var(--border);
  border-radius: 6px; margin-bottom: .8rem;
  display: flex; align-items: center; gap: .5rem;
}
.live-clock::before {
  content:''; width:.45rem; height:.45rem; border-radius:50%;
  background: var(--success); box-shadow: 0 0 6px var(--success);
  animation: pulse 2s ease-in-out infinite;
}
@keyframes pulse { 0%,100% { opacity:1 } 50% { opacity:.3 } }

/* ── Búsqueda: tags de resultado ───────────────────────────────────────── */
.search-result-tag {
  display: inline-block;
  background: rgba(74,144,226,.1);
  border: 1px solid rgba(74,144,226,.3);
  border-radius: 5px;
  padding: .22rem .55rem;
  font-size: .76rem;
  color: var(--accent-bri);
  margin: .2rem .2rem 0 0;
  font-family: 'JetBrains Mono', monospace;
}
.search-result-tag.danger { background:rgba(239,68,68,.1); border-color:rgba(239,68,68,.3); color: var(--danger); }
.search-result-tag.unknown { background:rgba(6,182,212,.1); border-color:rgba(6,182,212,.3); color: var(--info); }

/* ── Sin starfield (queda más serio sin animaciones decorativas) ──────── */
#orbital-stars { display: none !important; }

/* ── Ocultar chrome de Streamlit ───────────────────────────────────────── */
#MainMenu, footer, header { visibility: hidden; }
[data-testid="stSidebarNav"] { display: none; }
[data-testid="stHeader"] { background: transparent !important; height: 0 !important; }

/* ── Inline link styling ───────────────────────────────────────────────── */
a { color: var(--accent-bri) !important; text-decoration: none !important; }
a:hover { color: var(--accent) !important; text-decoration: underline !important; }
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
    incl: float        # inclination (deg)
    period_min: float  # orbital period (min)
    alt_mean: float    # mean altitude (km)
    known: bool        # in _NAMES catalog

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

_CELESTRAK_URLS = [
    "https://celestrak.org/NORAD/elements/gp.php?GROUP=stations&FORMAT=tle",
    "https://celestrak.com/NORAD/elements/stations.txt",
]
_HEADERS = {"User-Agent": "orbital-sentinel/0.1 (github.com/JFHelvetius/orbital_sentinel)"}


@st.cache_data(ttl=3600, show_spinner=False)
def _fetch_live_tles() -> tuple[str, str]:
    """Descarga TLEs de CelesTrak (caché 1 h). Prueba múltiples URLs y SSL."""
    for url in _CELESTRAK_URLS:
        for verify_ssl in (True, False):
            try:
                ctx = ssl.create_default_context()
                if not verify_ssl:
                    ctx.check_hostname = False
                    ctx.verify_mode = ssl.CERT_NONE
                req = urllib.request.Request(url, headers=_HEADERS)
                with urllib.request.urlopen(req, timeout=12, context=ctx) as r:
                    text = r.read().decode("utf-8")
                if text.strip() and text.count("1 ") >= 5:
                    ts = datetime.now(timezone.utc).strftime("%d %b %Y %H:%M UTC")
                    return text, f"🟢 CelesTrak live · {ts}"
            except Exception:
                continue
    return _TLE_STATIONS, "🟡 TLEs embebidos 2026-06-08 · CelesTrak no alcanzable"


_DATASETS = {
    "🏠 Estaciones (~25)":              ("stations",       "full"),
    "👁 Visibles a simple vista (~150)": ("visual",         "full"),
    "🚀 Lanzamientos 30 días (~300)":   ("last-30-days",   "lite"),
    "📡 Starlink (~6000)":              ("starlink",       "lite"),
    "🌍 Activos LEO (~3000)":           ("active",         "lite"),
}


@st.cache_data(show_spinner=False)
def _positions_only(tle_text: str, t0_offset_min: int = 0) -> list[SatTrack]:
    """Modo LITE: solo posición actual, sin propagar la órbita completa.
    Para datasets >100 objetos — evita timeouts y figuras gigantes."""
    blocks = _parse_blocks(tle_text)
    if not blocks:
        return []
    ref = Satrec.twoline2rv(blocks[0][1], blocks[0][2])
    epoch = _epoch_dt(ref) + timedelta(minutes=t0_offset_min)

    out: list[SatTrack] = []
    for name, l1, l2 in blocks:
        try:
            sat = Satrec.twoline2rv(l1, l2)
            norad = int(l2.split()[1])
            incl = math.degrees(sat.inclo)
            pm = (2 * math.pi / sat.no_kozai) if sat.no_kozai > 0 else 0.0
            a = (398600.4418 * (pm * 60 / (2 * math.pi)) ** 2) ** (1/3) if pm > 0 else 6771.0
            alt_mean = a - EARTH_R

            j1, j2 = _jday(epoch.year, epoch.month, epoch.day,
                            epoch.hour, epoch.minute, epoch.second + epoch.microsecond/1e6)
            e, r0, _ = sat.sgp4(j1, j2)
            if e != 0 or r0[0] == 0:
                continue
            lat0, lon0, alt0 = _teme_latlon(r0[0], r0[1], r0[2], j1 + j2)
            out.append(SatTrack(
                norad, _NAMES.get(norad, name.strip()),
                [], [],  # sin traza orbital
                lat0, lon0, alt0,
                incl, pm, alt_mean,
                norad in _NAMES,
            ))
        except Exception:
            continue
    return out


@st.cache_data(ttl=1800, show_spinner=False)
def _fetch_group_tles(group: str) -> str | None:
    """Descarga un grupo CelesTrak. Devuelve el texto TLE o None si falla."""
    for url in (
        f"https://celestrak.org/NORAD/elements/gp.php?GROUP={group}&FORMAT=tle",
        f"https://celestrak.com/NORAD/elements/{group}.txt",
    ):
        for verify in (True, False):
            try:
                ctx = ssl.create_default_context()
                if not verify:
                    ctx.check_hostname = False
                    ctx.verify_mode = ssl.CERT_NONE
                req = urllib.request.Request(url, headers=_HEADERS)
                with urllib.request.urlopen(req, timeout=15, context=ctx) as r:
                    text = r.read().decode("utf-8")
                if text.strip() and text.count("1 ") >= 3:
                    return text
            except Exception:
                continue
    return None


def _find_proximity_objects(
    station_tracks: list[SatTrack],
    extra_tle_text: str,
    delta_incl: float = 8.0,
    delta_alt: float = 300.0,
) -> list[SatTrack]:
    """
    Screening rápido (sin propagación completa) de objetos en extra_tle_text
    con parámetros orbitales similares a alguna estación rastreada.
    Solo propaga los candidatos que pasan el filtro.
    """
    known_norads = {t.norad for t in station_tracks}
    station_params = [(t.incl, t.alt_mean) for t in station_tracks if t.known]
    if not station_params:
        return []

    candidate_blocks: list[tuple[str, str, str]] = []
    for name, l1, l2 in _parse_blocks(extra_tle_text):
        try:
            norad = int(l2.split()[1])
            if norad in known_norads:
                continue
            sat = Satrec.twoline2rv(l1, l2)
            incl = math.degrees(sat.inclo)
            pm = (2 * math.pi / sat.no_kozai) if sat.no_kozai > 0 else 0
            a = (398600.4418 * (pm * 60 / (2 * math.pi)) ** 2) ** (1 / 3) if pm > 0 else 0
            alt = a - EARTH_R
            if any(abs(incl - si) <= delta_incl and abs(alt - sa) <= delta_alt
                   for si, sa in station_params):
                candidate_blocks.append((name, l1, l2))
        except Exception:
            continue

    if not candidate_blocks:
        return []
    cand_text = "\n".join(f"{n}\n{l1}\n{l2}" for n, l1, l2 in candidate_blocks)
    try:
        return _tracks(cand_text, 0)
    except Exception:
        return []


def _subsolar_point(when: datetime) -> tuple[float, float]:
    """Punto subsolar aproximado (lat°, lon°) para un datetime UTC."""
    doy = when.timetuple().tm_yday
    g   = math.radians(357.529 + 0.98560028 * doy)
    lam = math.radians(280.459 + 0.98564736 * doy + 1.915 * math.sin(g) + 0.020 * math.sin(2*g))
    e   = math.radians(23.439 - 0.0000004 * doy)
    dec = math.degrees(math.asin(math.sin(e) * math.sin(lam)))
    b   = math.radians(360 * (doy - 81) / 364)
    eot = 9.87 * math.sin(2*b) - 7.53 * math.cos(b) - 1.5 * math.sin(b)  # minutos
    t   = when.hour + when.minute / 60 + when.second / 3600
    lon = -(t - 12) * 15 - eot / 4
    lon = ((lon + 180) % 360) - 180
    return dec, lon


def _terminator(lat_s: float, lon_s: float, n: int = 120) -> tuple[list[float | None], list[float | None]]:
    """Gran círculo a 90° del punto subsolar (frontera día/noche)."""
    ls = math.radians(lat_s); lo = math.radians(lon_s)
    sx = math.cos(ls) * math.cos(lo)
    sy = math.cos(ls) * math.sin(lo)
    sz = math.sin(ls)
    ref = (0.0, 0.0, 1.0) if abs(sz) < 0.9 else (1.0, 0.0, 0.0)
    ux = sy*ref[2] - sz*ref[1]; uy = sz*ref[0] - sx*ref[2]; uz = sx*ref[1] - sy*ref[0]
    un = math.sqrt(ux*ux + uy*uy + uz*uz); ux /= un; uy /= un; uz /= un
    vx = sy*uz - sz*uy; vy = sz*ux - sx*uz; vz = sx*uy - sy*ux
    lats: list[float | None] = []; lons: list[float | None] = []; prev = None
    for i in range(n + 1):
        a  = 2 * math.pi * i / n
        px = ux*math.cos(a) + vx*math.sin(a)
        py = uy*math.cos(a) + vy*math.sin(a)
        pz = uz*math.cos(a) + vz*math.sin(a)
        lat = math.degrees(math.asin(max(-1.0, min(1.0, pz))))
        lon = math.degrees(math.atan2(py, px))
        if prev is not None and abs(lon - prev) > 180:
            lats.append(None); lons.append(None)
        lats.append(lat); lons.append(lon); prev = lon
    return lats, lons


def _parse_blocks(text: str) -> list[tuple[str,str,str]]:
    lines = [l.rstrip() for l in text.splitlines() if l.strip()]
    out = []
    for i in range(0, len(lines)-2, 3):
        n, l1, l2 = lines[i], lines[i+1], lines[i+2]
        if l1.startswith("1 ") and l2.startswith("2 "):
            out.append((n.strip(), l1, l2))
    return out

@st.cache_data(show_spinner=False)
def _tracks(tle_text: str, t0_offset_min: int = 0, n_min: int = 185) -> list[SatTrack]:
    """Propaga todas las trazas n_min minutos (≈2 órbitas por defecto)."""
    blocks = _parse_blocks(tle_text)
    if not blocks:
        return []
    ref = Satrec.twoline2rv(blocks[0][1], blocks[0][2])
    base_epoch = _epoch_dt(ref)
    epoch = base_epoch + timedelta(minutes=t0_offset_min)

    result: list[SatTrack] = []
    for name, l1, l2 in blocks:
        sat  = Satrec.twoline2rv(l1, l2)
        norad = int(l2.split()[1])

        # Parámetros orbitales desde el modelo SGP4
        incl       = math.degrees(sat.inclo)
        period_min = (2 * math.pi / sat.no_kozai) if sat.no_kozai > 0 else 0.0
        a          = (398600.4418 * (period_min * 60 / (2 * math.pi)) ** 2) ** (1/3) if period_min > 0 else 6771.0
        alt_mean   = a - EARTH_R
        known      = norad in _NAMES

        lats: list[float | None] = []
        lons: list[float | None] = []
        prev_lon: float | None = None

        for m in range(n_min):
            t  = epoch + timedelta(minutes=m)
            j1, j2 = _jday(t.year, t.month, t.day, t.hour, t.minute, t.second + t.microsecond / 1e6)
            e, r, _ = sat.sgp4(j1, j2)
            if e != 0 or r[0] == 0:
                lats.append(None); lons.append(None); prev_lon = None
                continue
            lat, lon, _ = _teme_latlon(r[0], r[1], r[2], j1 + j2)
            if prev_lon is not None and abs(lon - prev_lon) > 180:
                lats.append(None); lons.append(None)
            lats.append(lat); lons.append(lon); prev_lon = lon

        # Posición en el instante t0 (primer punto de la traza)
        t0 = epoch
        j1, j2 = _jday(t0.year, t0.month, t0.day, t0.hour, t0.minute, t0.second + t0.microsecond / 1e6)
        _, r0, _ = sat.sgp4(j1, j2)
        if r0[0] != 0:
            lat0, lon0, alt0 = _teme_latlon(r0[0], r0[1], r0[2], j1 + j2)
        else:
            lat0, lon0, alt0 = 0.0, 0.0, alt_mean

        result.append(SatTrack(norad, _NAMES.get(norad, name), lats, lons,
                               lat0, lon0, alt0, incl, period_min, alt_mean, known))
    return result


def _globe_figure(
    tracks: list[SatTrack],
    case: InvestigationCase,
    t0_offset: int = 0,
    highlight: frozenset[int] | None = None,
    extra_tracks: list[SatTrack] | None = None,
) -> go.Figure:
    real_norads: set[int] = set()
    for be in case.evidence_bundle.evidence_payloads:
        hp = be.derived_evidence.honesty_payload
        if float(hp.get("miss_distance_km", 0)) > 10:
            real_norads.add(int(hp.get("other_norad_cat_id", 0)))

    primary = case.evidence_bundle.object_id
    fig = go.Figure()

    # Modo lite: muchos objetos → solo dots, sin trazas ni labels
    lite_mode = len(tracks) > 100 or any(not t.lats for t in tracks)
    if lite_mode:
        # Render por batches de marcadores agrupados (mucho más rápido)
        d_lat = [t.lat0 for t in tracks if t.known and t.norad != primary]
        d_lon = [t.lon0 for t in tracks if t.known and t.norad != primary]
        d_cd  = [[t.norad, t.name, t.alt0, t.incl, t.period_min]
                 for t in tracks if t.known and t.norad != primary]
        u_lat = [t.lat0 for t in tracks if not t.known]
        u_lon = [t.lon0 for t in tracks if not t.known]
        u_cd  = [[t.norad, t.name, t.alt0, t.incl, t.period_min]
                 for t in tracks if not t.known]
        prim = [t for t in tracks if t.norad == primary]

        # Hover template reutilizado
        hov = ("<b>%{customdata[1]}</b><br>NORAD %{customdata[0]}"
               "<br>Alt: %{customdata[2]:.0f} km · Incl: %{customdata[3]:.2f}°"
               "<br>Período: %{customdata[4]:.1f} min<extra></extra>")

        if d_lat:
            fig.add_trace(go.Scattergeo(
                lat=d_lat, lon=d_lon, mode="markers",
                marker=dict(size=8, color="rgba(110,255,180,0.95)",
                            line=dict(width=1, color="rgba(255,255,255,0.4)")),
                customdata=d_cd, hovertemplate=hov,
                name="Catalogados", showlegend=False,
            ))
        if u_lat:
            fig.add_trace(go.Scattergeo(
                lat=u_lat, lon=u_lon, mode="markers",
                marker=dict(size=9, color="rgba(255,200,40,1)",
                            symbol="diamond", line=dict(width=1, color="rgba(255,255,255,0.5)")),
                customdata=u_cd, hovertemplate=hov,
                name="Sin catalogar", showlegend=False,
            ))
        if prim:
            t = prim[0]
            for gs, ga in ((32, 0.04), (24, 0.09), (18, 0.14)):
                fig.add_trace(go.Scattergeo(
                    lat=[t.lat0], lon=[t.lon0], mode="markers",
                    marker=dict(size=gs, color=f"rgba(255,215,0,{ga})", symbol="circle"),
                    showlegend=False, hoverinfo="skip",
                ))
            fig.add_trace(go.Scattergeo(
                lat=[t.lat0], lon=[t.lon0], mode="markers+text",
                marker=dict(size=18, color="#ffd700", symbol="star",
                            line=dict(width=1.5, color="white")),
                text=[t.name], textposition="top right",
                textfont=dict(color="#ffd700", size=12),
                customdata=[[t.norad, t.name, t.alt0, t.incl, t.period_min]],
                hovertemplate=hov, name="Primary", showlegend=False,
            ))
        tracks_to_draw = []
    else:
        tracks_to_draw = tracks

    for t in tracks_to_draw:
        is_primary  = (t.norad == primary)
        is_real     = (t.norad in real_norads)
        is_unknown  = not t.known and not is_primary and not is_real
        is_iss_dock = (t.norad in _ISS_DOCK and not is_primary and not is_unknown)
        is_css_dock = (t.norad in _CSS_DOCK and not is_primary and not is_unknown)

        if is_primary:
            lc, mc, lw, ms, sym = "#ffd700", "#ffd700", 2.5, 16, "star"
        elif is_real:
            lc, mc, lw, ms, sym = "#ff3547", "#ff3547", 2.0, 14, "x"
        elif is_unknown:
            lc, mc, lw, ms, sym = "rgba(255,180,0,0.5)", "rgba(255,200,0,0.9)", 1.3, 10, "diamond"
        elif is_iss_dock:
            lc, mc, lw, ms, sym = "rgba(79,158,255,0.3)", "rgba(79,158,255,0.65)", 1.0, 6, "circle"
        elif is_css_dock:
            lc, mc, lw, ms, sym = "rgba(255,100,100,0.3)", "rgba(255,120,100,0.65)", 1.0, 6, "circle"
        else:
            lc, mc, lw, ms, sym = "rgba(100,200,160,0.3)", "rgba(130,220,170,0.6)", 0.9, 6, "circle"

        # Atenuación si hay búsqueda
        dim = highlight is not None and t.norad not in highlight
        if dim:
            ms = max(ms - 3, 3); lw = max(lw * 0.4, 0.3)

        # Glow para primary/real
        if is_primary and not dim:
            for gs, ga in ((32, 0.04), (24, 0.09), (18, 0.14)):
                fig.add_trace(go.Scattergeo(
                    lat=[t.lat0], lon=[t.lon0], mode="markers",
                    marker=dict(size=gs, color=f"rgba(255,215,0,{ga})", symbol="circle"),
                    showlegend=False, hoverinfo="skip",
                ))
        elif is_real and not dim:
            for gs, ga in ((26, 0.05), (18, 0.1)):
                fig.add_trace(go.Scattergeo(
                    lat=[t.lat0], lon=[t.lon0], mode="markers",
                    marker=dict(size=gs, color=f"rgba(255,53,71,{ga})", symbol="circle"),
                    showlegend=False, hoverinfo="skip",
                ))

        hover = (
            f"<b>{'❓ ' if is_unknown else ''}{t.name}</b>"
            f"<br>NORAD {t.norad}"
            f"<br>Alt actual: <b>{t.alt0:.0f} km</b>"
            f"<br>Alt media: {t.alt_mean:.0f} km"
            f"<br>Inclinación: {t.incl:.2f}°"
            f"<br>Período: {t.period_min:.1f} min"
            + ("<br><b>⚠ NO CATALOGADO</b>" if is_unknown else "")
            + ("<br><b>⚠ Acercamiento no cooperativo</b>" if is_real else "")
            + "<extra></extra>"
        )
        show_txt = (is_primary or is_real or is_unknown) and not dim

        fig.add_trace(go.Scattergeo(
            lat=t.lats, lon=t.lons, mode="lines",
            line=dict(width=lw, color=lc),
            name=t.name, showlegend=False, hoverinfo="skip",
        ))
        fig.add_trace(go.Scattergeo(
            lat=[t.lat0], lon=[t.lon0],
            mode="markers+text" if show_txt else "markers",
            marker=dict(size=ms, color=mc, symbol=sym,
                        line=dict(width=1 if show_txt else 0, color="rgba(255,255,255,0.4)")),
            text=[t.name] if show_txt else [],
            textposition="top right",
            textfont=dict(color="#ffd700" if is_primary else
                          ("#ffb300" if is_unknown else "rgba(255,255,255,0.85)"), size=10),
            customdata=[[t.norad, t.name, t.alt0, t.incl, t.period_min]],
            name=t.name, showlegend=False, hovertemplate=hover,
        ))

    # Objetos de proximidad
    for t in (extra_tracks or []):
        for gs, ga in ((22, 0.06), (16, 0.12)):
            fig.add_trace(go.Scattergeo(
                lat=[t.lat0], lon=[t.lon0], mode="markers",
                marker=dict(size=gs, color=f"rgba(0,210,200,{ga})", symbol="circle"),
                showlegend=False, hoverinfo="skip",
            ))
        fig.add_trace(go.Scattergeo(
            lat=t.lats, lon=t.lons, mode="lines",
            line=dict(width=1.2, color="rgba(0,210,200,0.5)"),
            name=t.name, showlegend=False, hoverinfo="skip",
        ))
        fig.add_trace(go.Scattergeo(
            lat=[t.lat0], lon=[t.lon0], mode="markers+text",
            marker=dict(size=10, color="rgba(0,210,200,0.9)", symbol="triangle-up"),
            text=[t.name], textposition="top right",
            textfont=dict(color="#00d2c8", size=10),
            name=t.name, showlegend=False,
            hovertemplate=f"<b>🔴 {t.name}</b><br>NORAD {t.norad}<br>⚠ Proximidad detectada<extra></extra>",
        ))

    # Terminador día/noche + subsolar (try/except por si los helpers fallan)
    now_utc = datetime.now(timezone.utc)
    try:
        lat_sun, lon_sun = _subsolar_point(now_utc)
        t_lats, t_lons = _terminator(lat_sun, lon_sun)
        fig.add_trace(go.Scattergeo(
            lat=t_lats, lon=t_lons, mode="lines",
            line=dict(width=1.2, color="rgba(255,220,80,0.45)", dash="dot"),
            name="Terminador", showlegend=False, hoverinfo="skip",
        ))
        fig.add_trace(go.Scattergeo(
            lat=[lat_sun], lon=[lon_sun], mode="markers+text",
            marker=dict(size=12, color="rgba(255,220,60,0.9)", symbol="circle"),
            text=["☀"], textposition="top center",
            textfont=dict(size=14, color="rgba(255,220,60,0.95)"),
            name="Subsolar", showlegend=False,
            hovertemplate=f"<b>☀ Subsolar</b><br>{now_utc.strftime('%H:%M UTC')}<extra></extra>",
        ))
    except Exception:
        pass

    # Frames de rotación
    fig.frames = [
        go.Frame(layout=dict(geo=dict(projection=dict(rotation=dict(lon=lon)))), name=str(lon))
        for lon in range(0, 360, 3)
    ]

    # Geo realista — paleta Earth-from-space estilo Google Earth en vectorial
    t_label = f"T+{t0_offset//60}h {t0_offset%60:02d}m" if t0_offset else now_utc.strftime("%H:%M UTC")

    fig.update_layout(
        geo=dict(
            projection=dict(type="orthographic"),
            resolution=50,                                       # alta definición costas
            showland=True,    landcolor="rgb(85,110,68)",        # verde tierra vivo
            showocean=True,   oceancolor="rgb(6,28,76)",         # océano profundo realista
            showlakes=True,   lakecolor="rgb(16,52,112)",
            showrivers=True,  rivercolor="rgba(50,90,160,0.55)", riverwidth=0.6,
            showcoastlines=True, coastlinecolor="rgba(230,240,210,0.75)", coastlinewidth=0.9,
            showcountries=True,  countrycolor="rgba(200,215,170,0.45)", countrywidth=0.6,
            showsubunits=True,   subunitcolor="rgba(170,190,150,0.22)", subunitwidth=0.4,
            bgcolor="rgb(6,10,24)",
        ),
        paper_bgcolor="rgb(10,15,30)",
        height=760,
        margin=dict(l=0, r=0, t=40, b=0),
        showlegend=False,
        title=dict(
            text=f"<b style='color:#e8eef7'>Vista orbital</b>  "
                 f"<span style='font-size:11px;color:#5a6a84'>· {t_label}</span>",
            font=dict(color="#e8eef7", size=14), x=0.02, y=0.97,
        ),
        font=dict(color="#94a3b8", size=11),
        updatemenus=[dict(
            type="buttons", showactive=True,
            y=1.0, x=1.0, xanchor="right", yanchor="top", direction="left",
            buttons=[
                dict(label="▶ Rotar", method="animate",
                     args=[None, {"frame": {"duration": 40, "redraw": True},
                                  "fromcurrent": True, "transition": {"duration": 0},
                                  "mode": "immediate"}]),
                dict(label="⏸", method="animate",
                     args=[[None], {"frame": {"duration": 0}, "mode": "immediate",
                                    "transition": {"duration": 0}}]),
            ],
            bgcolor="rgba(21,27,44,0.92)",
            bordercolor="rgba(160,180,220,0.2)",
            font=dict(color="#e8eef7", size=11),
            pad=dict(r=8, t=4, b=4),
        )],
    )
    return fig


def _satellite_figure(
    tracks: list[SatTrack],
    case: InvestigationCase,
    highlight: frozenset[int] | None = None,
    extra_tracks: list[SatTrack] | None = None,
) -> go.Figure:
    """Vista plana con teselas satelitales reales de Esri World Imagery (estilo Google Earth)."""
    real_norads: set[int] = set()
    for be in case.evidence_bundle.evidence_payloads:
        hp = be.derived_evidence.honesty_payload
        if float(hp.get("miss_distance_km", 0)) > 10:
            real_norads.add(int(hp.get("other_norad_cat_id", 0)))

    primary = case.evidence_bundle.object_id
    fig = go.Figure()

    # Modo lite: muchos objetos → render por batches sin trazas
    lite_mode = len(tracks) > 100 or any(not t.lats for t in tracks)
    if lite_mode:
        d_lat = [t.lat0 for t in tracks if t.known and t.norad != primary]
        d_lon = [t.lon0 for t in tracks if t.known and t.norad != primary]
        d_txt = [f"<b>{t.name}</b><br>NORAD {t.norad}<br>Alt: {t.alt0:.0f} km"
                 for t in tracks if t.known and t.norad != primary]
        u_lat = [t.lat0 for t in tracks if not t.known]
        u_lon = [t.lon0 for t in tracks if not t.known]
        u_txt = [f"<b>❓ {t.name}</b><br>NORAD {t.norad}"
                 for t in tracks if not t.known]
        prim = [t for t in tracks if t.norad == primary]
        if d_lat:
            fig.add_trace(go.Scattermapbox(
                lat=d_lat, lon=d_lon, mode="markers",
                marker=dict(size=5, color="#7eff9e"),
                hovertext=d_txt, hovertemplate="%{hovertext}<extra></extra>",
                name="", showlegend=False,
            ))
        if u_lat:
            fig.add_trace(go.Scattermapbox(
                lat=u_lat, lon=u_lon, mode="markers",
                marker=dict(size=6, color="#ffb300"),
                hovertext=u_txt, hovertemplate="%{hovertext}<extra></extra>",
                name="", showlegend=False,
            ))
        if prim:
            t = prim[0]
            fig.add_trace(go.Scattermapbox(
                lat=[t.lat0], lon=[t.lon0], mode="markers",
                marker=dict(size=15, color="#ffd700"),
                hovertext=f"<b>{t.name}</b>",
                hovertemplate="%{hovertext}<extra></extra>",
                name="", showlegend=False,
            ))
        tracks_to_draw = []
    else:
        tracks_to_draw = tracks

    for t in tracks_to_draw:
        is_primary = (t.norad == primary)
        is_real    = (t.norad in real_norads)
        is_unknown = not t.known and not is_primary and not is_real

        if is_primary:
            color = "#ffd700"; size = 14; sym = "star"
        elif is_real:
            color = "#ff3547"; size = 12; sym = "x"
        elif is_unknown:
            color = "#ffb300"; size = 9; sym = "diamond"
        else:
            color = "rgba(120,220,180,0.85)"; size = 6; sym = "circle"

        dim = highlight is not None and t.norad not in highlight
        if dim:
            size = max(size - 2, 3)

        # Quitar None y cortes de longitud para mapbox
        lats = [l for l in t.lats if l is not None]
        lons = [l for l in t.lons if l is not None]

        fig.add_trace(go.Scattermapbox(
            lat=lats, lon=lons, mode="lines",
            line=dict(width=2 if (is_primary or is_real) else 1, color=color),
            name=t.name, showlegend=False, hoverinfo="skip",
            opacity=0.3 if dim else (0.9 if (is_primary or is_real or is_unknown) else 0.6),
        ))
        fig.add_trace(go.Scattermapbox(
            lat=[t.lat0], lon=[t.lon0], mode="markers",
            marker=dict(size=size, color=color),
            name=t.name, showlegend=False,
            text=[t.name], hovertemplate=(
                f"<b>{t.name}</b><br>NORAD {t.norad}"
                f"<br>Alt: {t.alt0:.0f} km · Incl: {t.incl:.1f}°"
                "<extra></extra>"
            ),
            opacity=0.3 if dim else 1.0,
        ))

    for t in (extra_tracks or []):
        lats = [l for l in t.lats if l is not None]
        lons = [l for l in t.lons if l is not None]
        fig.add_trace(go.Scattermapbox(
            lat=lats, lon=lons, mode="lines",
            line=dict(width=1.5, color="#00d2c8"),
            name=t.name, showlegend=False, hoverinfo="skip", opacity=0.7,
        ))
        fig.add_trace(go.Scattermapbox(
            lat=[t.lat0], lon=[t.lon0], mode="markers",
            marker=dict(size=10, color="#00d2c8"),
            name=t.name, showlegend=False,
            hovertemplate=f"<b>🔴 {t.name}</b><br>⚠ Proximidad detectada<extra></extra>",
        ))

    fig.update_layout(
        mapbox=dict(
            style="white-bg",
            layers=[
                dict(  # base: imágenes satelitales Esri
                    below="traces",
                    sourcetype="raster",
                    sourceattribution="Esri · Maxar · Earthstar Geographics · USGS",
                    source=[
                        "https://server.arcgisonline.com/ArcGIS/rest/services/"
                        "World_Imagery/MapServer/tile/{z}/{y}/{x}"
                    ],
                ),
                dict(  # capa híbrida: bordes y etiquetas de países/ciudades
                    below="traces",
                    sourcetype="raster",
                    source=[
                        "https://server.arcgisonline.com/ArcGIS/rest/services/"
                        "Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}"
                    ],
                ),
            ],
            center=dict(lat=20, lon=0),
            zoom=1.2,
        ),
        paper_bgcolor="rgb(10,15,30)",
        height=760,
        margin=dict(l=0, r=0, t=0, b=0),
        showlegend=False,
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

    if "map_case" not in st.session_state:
        st.session_state["map_case"] = cases[0]

    # ── Carga TLEs anticipada (no bloquea el layout) ──────────────────────────
    tle_text, tle_source = _fetch_live_tles()

    # ── Layout: globo izquierda · panel control derecha ───────────────────────
    col_globe, col_ctrl = st.columns([4, 1], gap="small")

    with col_ctrl:
        now_utc = datetime.now(timezone.utc)
        st.markdown(f'<div class="live-clock">🕐 {now_utc.strftime("%H:%M:%S UTC")}</div>', unsafe_allow_html=True)

        case_labels = {_CASE_META.get(c, {}).get("title", c): c for c in cases}
        sel_label = st.radio(
            "Objeto principal", list(case_labels.keys()),
            key="map_case_radio", label_visibility="visible",
        )
        selected = case_labels[sel_label]
        st.session_state["map_case"] = selected

        search_q = st.text_input(
            "Buscar", placeholder="Nombre o NORAD…",
            key="map_search", label_visibility="visible",
        )

        t0_offset = st.slider(
            "Proyección temporal", 0, 1440, 0, 15,
            key="map_t0", format="%d min", help="Máx 24 h desde época TLE",
        )
        if t0_offset:
            h, m = divmod(t0_offset, 60)
            st.caption(f"T+{h}h {m:02d}m")

        n_orbits = st.select_slider(
            "Trazas orbitales", [1, 2, 3], value=2, key="map_orbits",
        )
        st.caption(f"{n_orbits} órbita{'s' if n_orbits > 1 else ''} ≈ {n_orbits*92} min")

        scan_prox = st.toggle(
            "🛰 Detección proximidad", key="map_scan_prox",
            help="Escanea last-30-days de CelesTrak buscando objetos en órbita similar a las estaciones.",
        )

        dataset_label = st.selectbox(
            "Dataset a rastrear",
            list(_DATASETS.keys()),
            index=0,
            key="map_dataset",
            help=("Estaciones: ISS, CSS y módulos acoplados (con trazas).  "
                  "Visibles: brillantes a simple vista.  "
                  "Lanzamientos: últimos 30 días.  "
                  "Starlink/Activos: miles de objetos en modo lite (solo posiciones)."),
        )
        view_mode = st.radio(
            "Modo de vista",
            ["🌍 Globo 3D", "🛰 Satélite (Esri)"],
            key="map_view_mode",
            help="Globo 3D: orthographic vectorial realista. Satélite: tiles Esri World Imagery.",
        )

    # ── Selección de dataset: fetch live de CelesTrak según selección ────────
    ds_group, ds_mode = _DATASETS[dataset_label]
    if ds_group != "stations":
        # Para datasets distintos a stations, usamos el group fetcher
        with st.spinner(f"Descargando {dataset_label} desde CelesTrak…"):
            ds_tle = _fetch_group_tles(ds_group)
        if ds_tle:
            active_tle = ds_tle
            active_source = f"🟢 CelesTrak live · {ds_group} · {datetime.now(timezone.utc).strftime('%H:%M UTC')}"
        else:
            active_tle = tle_text
            active_source = tle_source + f" (fallback de {ds_group})"
    else:
        active_tle = tle_text
        active_source = tle_source

    # ── Propagación ───────────────────────────────────────────────────────────
    blocks_ref = _parse_blocks(active_tle)
    n_min_steps = 185
    if blocks_ref:
        sat0 = Satrec.twoline2rv(blocks_ref[0][1], blocks_ref[0][2])
        p0 = (2 * math.pi / sat0.no_kozai) if sat0.no_kozai > 0 else 92
        n_min_steps = int(p0 * n_orbits) + 5

    with st.spinner(f"Calculando posiciones ({ds_mode} mode)…"):
        try:
            if ds_mode == "lite":
                track_list = _positions_only(active_tle, t0_offset)
            else:
                track_list = _tracks(active_tle, t0_offset, n_min_steps)
            case = _load(selected)
        except Exception as exc:
            st.error(f"Error: {exc}"); return

    # Diagnóstico visible
    with col_globe:
        n_blocks = active_tle.count("\n1 ")  # cuenta líneas que empiezan con "1 "
        if ds_group != "stations":
            if ds_tle is None:
                st.error(f"❌ CelesTrak no respondió para grupo **{ds_group}**. Mostrando fallback de estaciones.")
            elif len(track_list) == 0:
                st.warning(f"⚠ Se descargaron {n_blocks} TLEs de **{ds_group}** pero ninguno propagó. Revisa el log.")
            else:
                st.success(f"✅ **{len(track_list)} objetos** activos de **{ds_group}** ({active_source})")

    # Proximity scan
    extra_tracks: list[SatTrack] = []
    if scan_prox:
        with st.spinner("Escaneando proximidades…"):
            extra_tle = _fetch_group_tles("last-30-days")
            if extra_tle:
                extra_tracks = _find_proximity_objects(track_list, extra_tle)

    # Search highlight
    highlight: frozenset[int] | None = None
    search_matches: list[SatTrack] = []
    if search_q.strip():
        q = search_q.strip().lower()
        search_matches = [t for t in track_list + extra_tracks
                          if q in t.name.lower() or q in str(t.norad)]
        highlight = frozenset(t.norad for t in search_matches)

    # ── Globe + resultados (columna izquierda) ────────────────────────────────
    with col_globe:
        try:
            if view_mode and "Satélite" in view_mode:
                fig = _satellite_figure(track_list, case,
                                         highlight=highlight, extra_tracks=extra_tracks)
            else:
                fig = _globe_figure(track_list, case, t0_offset,
                                    highlight=highlight, extra_tracks=extra_tracks)
            event = st.plotly_chart(
                fig, use_container_width=True,
                config={"displayModeBar": True, "scrollZoom": True, "displaylogo": False},
                on_select="rerun",
                selection_mode=["points"],
                key="globe_chart",
            )
        except Exception as exc:
            st.error(f"❌ {type(exc).__name__}: {exc}")
            import traceback
            st.code(traceback.format_exc(), language="python")
            return
        st.caption(f"{active_source}  ·  {len(track_list)} objetos  ·  modo {ds_mode}")

        # ── Info del objeto clicado ──────────────────────────────────────────
        sel_points = (event.selection or {}).get("points", []) if event else []
        if sel_points:
            p = sel_points[0]
            cd = p.get("customdata", None)
            if cd and len(cd) >= 5:
                norad, name, alt, incl, per = cd[:5]
                st.markdown(f"""
**🎯 Objeto seleccionado:** `{name}`
- **NORAD ID:** `{norad}`
- **Altitud actual:** `{alt:.0f} km`
- **Inclinación:** `{incl:.2f}°`
- **Período orbital:** `{per:.1f} min` ({per/60:.2f} h)
- **Velocidad orbital:** `{(2*math.pi*(EARTH_R+alt)/per/60):.2f} km/s`
""")

        if search_q.strip():
            if search_matches:
                prox_norads = {tt.norad for tt in extra_tracks}
                tags = "".join(
                    f'<span class="search-result-tag {"unknown" if t.norad in prox_norads else ""}">'
                    f'{t.name} · {t.norad} · {t.alt_mean:.0f} km · {t.incl:.1f}°</span>'
                    for t in search_matches
                )
                st.markdown(tags, unsafe_allow_html=True)
            else:
                st.info(f"Sin resultados para «{search_q}»")

    # ── Panel control: stats + alertas ───────────────────────────────────────
    real_evs = [
        be for be in case.evidence_bundle.evidence_payloads
        if float(be.derived_evidence.honesty_payload.get("miss_distance_km", 0)) > 10
    ]
    unknown_tracks = [t for t in track_list if not t.known]
    n_unknown = len(unknown_tracks)
    n_real    = len(real_evs)
    n_ev      = case.evidence_bundle.n_evidence_payloads

    with col_ctrl:
        st.divider()
        st.metric("Objetos rastreados", len(track_list))
        if n_unknown:
            st.metric("Sin catalogar", n_unknown)
        st.metric("Evidencias", n_ev)
        if n_real:
            st.metric("Acercamientos", n_real)
        if extra_tracks:
            st.metric("Proximidad detectada", len(extra_tracks))

        if real_evs:
            st.divider()
            st.markdown("**⚠ Conjunciones**")
            for be in real_evs:
                hp    = be.derived_evidence.honesty_payload
                norad = int(hp.get("other_norad_cat_id", 0))
                miss  = float(hp.get("miss_distance_km", 0))
                tca   = be.derived_evidence.event_epoch.strftime("%d %b %H:%M")
                st.error(f"**{_label(norad)}**  \n{miss:.2f} km · {tca} UTC", icon="⚠")

        if extra_tracks:
            st.divider()
            st.markdown(f"**🛰 Proximidad ({len(extra_tracks)})**")
            for t in extra_tracks[:6]:
                st.info(
                    f"**{t.name}**  \nNORAD {t.norad} · {t.alt_mean:.0f} km · {t.incl:.1f}°",
                    icon="🔴",
                )

        if unknown_tracks:
            st.divider()
            st.markdown(f"**❓ Sin catalogar ({n_unknown})**")
            for t in unknown_tracks[:5]:
                st.warning(
                    f"**{t.name}**  \nNORAD {t.norad} · {t.alt_mean:.0f} km · {t.incl:.1f}°",
                    icon="❓",
                )

    # ── Tabla completa (toggle limpio sin expander) ──────────────────────────
    st.divider()
    all_objs = track_list + extra_tracks
    show_table = st.toggle(
        f"📋 Ver tabla completa — {len(all_objs)} objetos detectados",
        key="map_show_table",
    )
    if show_table:
        prox_set = {t.norad for t in extra_tracks}
        rows = []
        for t in sorted(all_objs, key=lambda x: (x.known, x.norad)):
            estado = "🔴 Proximidad" if t.norad in prox_set else ("✓" if t.known else "❓ Desconocido")
            rows.append({
                "Estado": estado,
                "Nombre": t.name,
                "NORAD": t.norad,
                "Alt media (km)": round(t.alt_mean, 0),
                "Inclinación (°)": round(t.incl, 2),
                "Período (min)": round(t.period_min, 1),
            })
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True, height=400)


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
  <div>
    <h1>Orbital Sentinel <span class="pill">v0.1 · Apache 2.0</span></h1>
    <p>Infraestructura verificable para afirmaciones sobre el entorno orbital · Datos públicos · Sin IA · Sin autoridad central</p>
  </div>
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
