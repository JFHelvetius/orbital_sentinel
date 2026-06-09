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

/* Atmósfera alrededor del globo */
[data-testid="stPlotlyChart"] {
    box-shadow:
        0 0 0 1px rgba(20,80,220,.1),
        0 0 35px rgba(20,80,220,.2),
        0 0 80px rgba(10,50,180,.12),
        0 0 150px rgba(5,30,130,.07);
    border-radius: 8px;
}

/* Panel lateral de control */
.ctrl-section { margin-bottom:.8rem; }
.ctrl-title { font-size:.78rem; text-transform:uppercase; letter-spacing:.08em;
              color:#4a5568; margin-bottom:.35rem; }
.live-clock { font-family:monospace; font-size:.85rem; color:#4f9eff; }

/* Búsqueda de satélites */
.sat-search-wrap { position:relative; }
.search-result-tag { display:inline-block; background:rgba(79,158,255,.12);
  border:1px solid rgba(79,158,255,.3); border-radius:6px;
  padding:.2rem .6rem; font-size:.8rem; color:#4f9eff; margin:.2rem .2rem 0 0; }
.search-result-tag.danger { background:rgba(255,53,71,.12); border-color:rgba(255,53,71,.3); color:#ff3547; }
.search-result-tag.unknown { background:rgba(255,165,0,.12); border-color:rgba(255,165,0,.3); color:#ffb300; }

/* Badge de proximidad */
.prox-badge { display:inline-flex; align-items:center; gap:.5rem;
  background:rgba(0,210,200,.07); border:1px solid rgba(0,210,200,.25);
  border-radius:8px; padding:.5rem 1rem; margin:.3rem 0; }
.prox-badge .pb-name { color:#00d2c8; font-weight:600; font-size:.9rem; }
.prox-badge .pb-detail { color:#8892a4; font-size:.78rem; }
</style>
<script>
(function(){
  if(document.getElementById('orbital-stars')) return;
  var sf=document.createElement('div');
  sf.id='orbital-stars';
  sf.style.cssText='position:fixed;top:0;left:0;width:100%;height:100%;pointer-events:none;z-index:0;overflow:hidden;';
  var s='<style>@keyframes tw{0%{opacity:.08}50%{opacity:.7}100%{opacity:.08}}</style>';
  for(var i=0;i<180;i++){
    var x=(Math.random()*100).toFixed(2),y=(Math.random()*100).toFixed(2);
    var sz=(Math.random()*1.4+0.3).toFixed(1),dur=(Math.random()*4+2).toFixed(1);
    var del=(Math.random()*5).toFixed(1);
    s+='<div style="position:absolute;left:'+x+'%;top:'+y+'%;width:'+sz+'px;height:'+sz+'px;background:#fff;border-radius:50%;animation:tw '+dur+'s '+del+'s ease-in-out infinite;"></div>';
  }
  sf.innerHTML=s; document.body.appendChild(sf);
})();
</script>
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

    for t in tracks:
        is_primary  = (t.norad == primary)
        is_real     = (t.norad in real_norads)
        is_unknown  = not t.known and not is_primary and not is_real
        is_iss_dock = (t.norad in _ISS_DOCK and not is_primary and not is_unknown)
        is_css_dock = (t.norad in _CSS_DOCK and not is_primary and not is_unknown)

        if is_primary:
            lc, mc, lw, ms, sym = "#ffd700", "#ffd700", 2.5, 18, "star"
        elif is_real:
            lc, mc, lw, ms, sym = "#ff3547", "#ff3547", 2.2, 15, "x"
        elif is_unknown:
            lc, mc, lw, ms, sym = "rgba(255,165,0,0.5)", "rgba(255,185,0,0.95)", 1.4, 11, "diamond"
        elif is_iss_dock:
            lc, mc, lw, ms, sym = "rgba(79,158,255,0.3)", "rgba(79,158,255,0.65)", 1.0, 7, "circle"
        elif is_css_dock:
            lc, mc, lw, ms, sym = "rgba(255,100,100,0.3)", "rgba(255,120,100,0.65)", 1.0, 7, "circle"
        else:
            lc, mc, lw, ms, sym = "rgba(80,180,120,0.25)", "rgba(110,210,140,0.6)", 0.8, 6, "circle"

        # Glow rings para objetos importantes
        if is_primary:
            for gs, ga in ((36, 0.03), (28, 0.07), (22, 0.12)):
                fig.add_trace(go.Scattergeo(
                    lat=[t.lat0], lon=[t.lon0], mode="markers",
                    marker=dict(size=gs, color=f"rgba(255,215,0,{ga})", symbol="circle"),
                    showlegend=False, hoverinfo="skip",
                ))
        elif is_real:
            for gs, ga in ((30, 0.04), (22, 0.09)):
                fig.add_trace(go.Scattergeo(
                    lat=[t.lat0], lon=[t.lon0], mode="markers",
                    marker=dict(size=gs, color=f"rgba(255,53,71,{ga})", symbol="circle"),
                    showlegend=False, hoverinfo="skip",
                ))

        # Hover enriquecido
        badges = []
        if is_unknown: badges.append("⚠ NO CATALOGADO localmente")
        if is_real:    badges.append("⚠ Acercamiento no cooperativo")
        badge_html = "".join(f"<br><b>{b}</b>" for b in badges)
        hover = (
            f"<b>{'❓ ' if is_unknown else ''}{t.name}</b>"
            f"<br>NORAD {t.norad}"
            f"<br>─────────────────"
            f"<br>Alt actual: <b>{t.alt0:.0f} km</b>"
            f"<br>Alt media: {t.alt_mean:.0f} km"
            f"<br>Inclinación: {t.incl:.2f}°"
            f"<br>Período: {t.period_min:.1f} min  ({t.period_min/60:.2f} h)"
            + badge_html
            + "<extra></extra>"
        )

        # Si hay búsqueda activa, atenuar objetos que no coinciden
        dim = highlight is not None and t.norad not in highlight
        if dim:
            lc = lc.replace("0.3", "0.06").replace("0.35", "0.06").replace("0.25", "0.04")
            mc = mc.replace("0.7", "0.12").replace("0.65", "0.1").replace("0.6", "0.08").replace("0.9", "0.15")
            lw = max(lw * 0.4, 0.3)
            ms = max(ms - 3, 3)

        show_txt = (is_primary or is_real or is_unknown) and not dim
        fig.add_trace(go.Scattergeo(
            lat=t.lats, lon=t.lons, mode="lines",
            line=dict(width=lw, color=lc),
            name=t.name, showlegend=not dim, hoverinfo="skip",
        ))
        fig.add_trace(go.Scattergeo(
            lat=[t.lat0], lon=[t.lon0],
            mode="markers+text" if show_txt else "markers",
            marker=dict(size=ms, color=mc, symbol=sym,
                        line=dict(width=1.5 if show_txt else 0.5, color="rgba(255,255,255,0.4)")),
            text=[("❓ " if is_unknown else "") + t.name] if show_txt else [],
            textposition="top right",
            textfont=dict(
                color="#ffb300" if is_unknown else ("#ffd700" if is_primary else "rgba(255,255,255,0.9)"),
                size=11, family="monospace",
            ),
            name=t.name, showlegend=False,
            hovertemplate=hover,
        ))

    # Objetos de proximidad extra (last-30-days, etc.)
    for t in (extra_tracks or []):
        hover_ex = (
            f"<b>🔴 {t.name}</b><br>NORAD {t.norad}"
            f"<br>Alt media: {t.alt_mean:.0f} km  ·  Incl: {t.incl:.2f}°"
            f"<br>Período: {t.period_min:.1f} min"
            f"<br><b>⚠ Detectado en órbita cercana a estación</b>"
            "<extra></extra>"
        )
        for gs, ga in ((26, 0.05), (18, 0.1)):
            fig.add_trace(go.Scattergeo(
                lat=[t.lat0], lon=[t.lon0], mode="markers",
                marker=dict(size=gs, color=f"rgba(0,210,200,{ga})", symbol="circle"),
                showlegend=False, hoverinfo="skip",
            ))
        fig.add_trace(go.Scattergeo(
            lat=t.lats, lon=t.lons, mode="lines",
            line=dict(width=1.2, color="rgba(0,210,200,0.4)"),
            name=t.name, showlegend=True, hoverinfo="skip",
        ))
        fig.add_trace(go.Scattergeo(
            lat=[t.lat0], lon=[t.lon0], mode="markers+text",
            marker=dict(size=10, color="rgba(0,210,200,0.9)", symbol="triangle-up",
                        line=dict(width=1, color="white")),
            text=[t.name], textposition="top right",
            textfont=dict(color="#00d2c8", size=10, family="monospace"),
            name=t.name, showlegend=False,
            hovertemplate=hover_ex,
        ))

    # ── Terminador día/noche ─────────────────────────────────────────────────
    now_utc = datetime.now(timezone.utc)
    lat_sun, lon_sun = _subsolar_point(now_utc)
    t_lats, t_lons = _terminator(lat_sun, lon_sun)
    fig.add_trace(go.Scattergeo(
        lat=t_lats, lon=t_lons, mode="lines",
        line=dict(width=1.5, color="rgba(255,220,80,0.55)", dash="dot"),
        name="Terminador día/noche", showlegend=True, hoverinfo="skip",
    ))
    # Punto subsolar ☀
    fig.add_trace(go.Scattergeo(
        lat=[lat_sun], lon=[lon_sun], mode="markers+text",
        marker=dict(size=14, color="rgba(255,220,60,0.9)", symbol="circle",
                    line=dict(width=1.5, color="rgba(255,200,0,0.6)")),
        text=["☀"], textposition="top center",
        textfont=dict(size=14, color="rgba(255,220,60,0.9)"),
        name="Punto subsolar", showlegend=True,
        hovertemplate=(f"<b>☀ Punto subsolar</b><br>Lat: {lat_sun:.1f}°  Lon: {lon_sun:.1f}°"
                       f"<br>{now_utc.strftime('%H:%M UTC')}<extra></extra>"),
    ))

    # ── Frames de rotación automática ────────────────────────────────────────
    frames = [
        go.Frame(layout=dict(geo=dict(projection=dict(rotation=dict(lon=lon)))), name=str(lon))
        for lon in range(0, 360, 2)
    ]
    fig.frames = frames

    # ── Geo: colores realistas "desde el espacio" ────────────────────────────
    for _geo in (
        dict(
            projection=dict(type="orthographic"),
            showland=True,    landcolor="rgb(45,65,38)",    # verde-marrón natural
            showocean=True,   oceancolor="rgb(5,28,80)",    # azul océano profundo real
            showlakes=True,   lakecolor="rgb(10,45,100)",
            showrivers=False,
            showcoastlines=True, coastlinecolor="rgba(180,200,160,0.7)",
            showcountries=True,  countrycolor="rgba(120,140,100,0.3)",
            showgraticules=True, graticulecolor="rgba(60,90,140,0.18)",
            bgcolor="rgb(2,5,15)",
        ),
        dict(  # fallback mínimo
            projection=dict(type="orthographic"),
            showland=True,   landcolor="rgb(45,65,38)",
            showocean=True,  oceancolor="rgb(5,28,80)",
            showcoastlines=True, showcountries=True,
        ),
    ):
        try:
            fig.update_layout(geo=_geo); break
        except Exception:
            continue

    t_label = f"T+{t0_offset//60}h {t0_offset%60:02d}m" if t0_offset else now_utc.strftime("%H:%M UTC")
    fig.update_layout(
        paper_bgcolor="rgb(2,5,15)",
        height=740,
        margin=dict(l=0, r=150, t=46, b=0),
        legend=dict(
            bgcolor="rgba(3,7,20,0.94)", bordercolor="rgba(79,158,255,0.15)",
            borderwidth=1, font=dict(color="#5a6a84", size=9),
            x=1.01, y=0.99, xanchor="left", tracegroupgap=1,
        ),
        title=dict(
            text=f"<b>Vista orbital en tiempo real</b>"
                 f"  <span style='font-size:11px;color:#3a4a60;font-family:monospace'>{t_label}</span>"
                 f"<br><span style='font-size:10px;color:#2a3a50'>"
                 f"Arrastra para rotar · rueda para zoom · hover para detalles · ▶ auto-rotar</span>",
            font=dict(color="#b0bcd0", size=14), x=0.01, y=0.99,
        ),
        updatemenus=[dict(
            type="buttons", showactive=True,
            y=0.01, x=0.01, xanchor="left", yanchor="bottom", direction="left",
            buttons=[
                dict(label="▶  Rotar",  method="animate",
                     args=[None, {"frame": {"duration": 35, "redraw": True},
                                  "fromcurrent": True, "transition": {"duration": 0},
                                  "mode": "immediate"}]),
                dict(label="⏸  Parar", method="animate",
                     args=[[None], {"frame": {"duration": 0}, "mode": "immediate",
                                    "transition": {"duration": 0}}]),
            ],
            bgcolor="rgba(5,10,25,0.92)", bordercolor="rgba(79,158,255,0.25)",
            font=dict(color="#b0bcd0", size=11), pad=dict(r=8, t=6, b=6),
        )],
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

    # ── Carga TLEs anticipada (no bloquea el layout) ──────────────────────────
    tle_text, tle_source = _fetch_live_tles()

    # ── Layout: globo izquierda · panel control derecha ───────────────────────
    col_globe, col_ctrl = st.columns([4, 1], gap="small")

    with col_ctrl:
        now_utc = datetime.now(timezone.utc)
        st.markdown(f'<div class="live-clock">🕐 {now_utc.strftime("%H:%M:%S UTC")}</div>', unsafe_allow_html=True)
        st.markdown('<div class="ctrl-title">Objeto principal</div>', unsafe_allow_html=True)
        case_labels = {_CASE_META.get(c, {}).get("title", c): c for c in cases}
        sel_label = st.radio("", list(case_labels.keys()), key="map_case_radio", label_visibility="collapsed")
        selected = case_labels[sel_label]
        st.session_state["map_case"] = selected

        st.divider()
        st.markdown('<div class="ctrl-title">Búsqueda</div>', unsafe_allow_html=True)
        search_q = st.text_input("", placeholder="Nombre o NORAD…", key="map_search", label_visibility="collapsed")

        st.markdown('<div class="ctrl-title">Proyección temporal</div>', unsafe_allow_html=True)
        t0_offset = st.slider("", 0, 1440, 0, 15, key="map_t0", label_visibility="collapsed",
                               format="%d min", help="Máx 24 h desde época TLE")
        if t0_offset:
            h, m = divmod(t0_offset, 60)
            st.caption(f"T+{h}h {m:02d}m")

        st.markdown('<div class="ctrl-title">Trazas orbitales</div>', unsafe_allow_html=True)
        n_orbits = st.select_slider("", [1, 2, 3], value=2, key="map_orbits", label_visibility="collapsed")
        st.caption(f"{n_orbits} órbita{'s' if n_orbits > 1 else ''} ≈ {n_orbits*92} min")

        st.divider()
        scan_prox = st.toggle("🛰 Detección proximidad", key="map_scan_prox",
                               help="Escanea last-30-days de CelesTrak buscando objetos en órbita similar a las estaciones.")

    # ── Propagación ───────────────────────────────────────────────────────────
    blocks_ref = _parse_blocks(tle_text)
    n_min_steps = 185
    if blocks_ref:
        sat0 = Satrec.twoline2rv(blocks_ref[0][1], blocks_ref[0][2])
        p0 = (2 * math.pi / sat0.no_kozai) if sat0.no_kozai > 0 else 92
        n_min_steps = int(p0 * n_orbits) + 5

    with st.spinner("Propagando órbitas…"):
        try:
            track_list = _tracks(tle_text, t0_offset, n_min_steps)
            case       = _load(selected)
        except Exception as exc:
            st.error(f"Error: {exc}"); return

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
        st.plotly_chart(
            _globe_figure(track_list, case, t0_offset, highlight=highlight, extra_tracks=extra_tracks),
            use_container_width=True,
            config={"displayModeBar": True, "scrollZoom": True, "displaylogo": False},
        )
        st.caption(f"{tle_source}  ·  {n_min_steps} min de propagación  ·  {len(track_list)} objetos")

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
        st.markdown(f"""
<div class="stat-row" style="flex-direction:column;gap:.4rem;">
  <div class="stat-chip" style="flex-direction:row;justify-content:space-between;min-width:0;padding:.4rem .8rem;">
    <span class="sl">Objetos</span><span class="sv" style="font-size:1rem;">{len(track_list)}</span>
  </div>
  <div class="stat-chip" style="flex-direction:row;justify-content:space-between;min-width:0;padding:.4rem .8rem;">
    <span class="sl">Sin catalogar</span><span class="sv" style="font-size:1rem;color:#ffb300">{n_unknown}</span>
  </div>
  <div class="stat-chip" style="flex-direction:row;justify-content:space-between;min-width:0;padding:.4rem .8rem;">
    <span class="sl">Evidencias</span><span class="sv" style="font-size:1rem;">{n_ev}</span>
  </div>
  <div class="stat-chip" style="flex-direction:row;justify-content:space-between;min-width:0;padding:.4rem .8rem;">
    <span class="sl">Acercamientos</span><span class="sv" style="font-size:1rem;color:#ff4757">{n_real}</span>
  </div>{"" if not extra_tracks else f'''
  <div class="stat-chip" style="flex-direction:row;justify-content:space-between;min-width:0;padding:.4rem .8rem;border-color:rgba(0,210,200,.3);">
    <span class="sl">Proximidad</span><span class="sv" style="font-size:1rem;color:#00d2c8">{len(extra_tracks)}</span>
  </div>'''}
</div>""", unsafe_allow_html=True)

        if real_evs:
            st.markdown('<div class="ctrl-title" style="margin-top:.8rem;">⚠ Conjunciones</div>', unsafe_allow_html=True)
            for be in real_evs:
                hp    = be.derived_evidence.honesty_payload
                norad = int(hp.get("other_norad_cat_id", 0))
                miss  = float(hp.get("miss_distance_km", 0))
                tca   = be.derived_evidence.event_epoch.strftime("%d %b %H:%M")
                st.markdown(f"""
<div class="conj-alert" style="flex-direction:column;align-items:flex-start;gap:.2rem;padding:.6rem .8rem;margin:.2rem 0;">
  <div class="ca-name" style="font-size:.85rem;">⚠ {_label(norad)}</div>
  <div class="ca-val" style="font-size:1.1rem;">{miss:.2f} km</div>
  <div class="ca-label">{tca} UTC</div>
</div>""", unsafe_allow_html=True)

        if extra_tracks:
            st.markdown(f'<div class="ctrl-title" style="margin-top:.8rem;">🛰 Proximidad ({len(extra_tracks)})</div>', unsafe_allow_html=True)
            for t in extra_tracks[:6]:
                st.markdown(f"""
<div class="prox-badge" style="flex-direction:column;align-items:flex-start;padding:.4rem .7rem;margin:.2rem 0;">
  <div class="pb-name" style="font-size:.82rem;">🔴 {t.name}</div>
  <div class="pb-detail">{t.norad} · {t.alt_mean:.0f} km · {t.incl:.1f}°</div>
</div>""", unsafe_allow_html=True)

        if unknown_tracks:
            st.markdown(f'<div class="ctrl-title" style="margin-top:.8rem;">❓ Sin catalogar ({n_unknown})</div>', unsafe_allow_html=True)
            for t in unknown_tracks[:5]:
                st.markdown(f"""
<div style="border:1px solid rgba(255,165,0,.2);border-radius:6px;padding:.35rem .6rem;margin:.2rem 0;background:rgba(255,165,0,.05);">
  <div style="color:#ffb300;font-size:.82rem;font-weight:600;">{t.name}</div>
  <div style="color:#5a6a84;font-size:.75rem;">{t.norad} · {t.alt_mean:.0f} km · {t.incl:.1f}°</div>
</div>""", unsafe_allow_html=True)

    # ── Tabla completa ────────────────────────────────────────────────────────
    all_objs = track_list + extra_tracks
    with st.expander(f"📋 Todos los objetos detectados ({len(all_objs)})", expanded=False):
        prox_set = {t.norad for t in extra_tracks}
        rows = []
        for t in sorted(all_objs, key=lambda x: (x.known, x.norad)):
            estado = "🔴 Proximidad" if t.norad in prox_set else ("✓" if t.known else "❓ Desconocido")
            rows.append({
                "Estado": estado, "Nombre": t.name, "NORAD": t.norad,
                "Alt media (km)": round(t.alt_mean, 0),
                "Inclinación (°)": round(t.incl, 2),
                "Período (min)": round(t.period_min, 1),
                "Alt instantánea (km)": round(t.alt0, 0),
            })
        df_all = pd.DataFrame(rows)

        def _row_color(row: pd.Series) -> list[str]:
            s = str(row["Estado"])
            if "Proximidad" in s:
                return ["background-color:rgba(0,210,200,.07);color:#00d2c8"] * len(row)
            if s.startswith("❓"):
                return ["background-color:rgba(255,165,0,.08);color:#ffb300"] * len(row)
            return [""] * len(row)

        st.dataframe(df_all.style.apply(_row_color, axis=1),
                     use_container_width=True, hide_index=True)


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
