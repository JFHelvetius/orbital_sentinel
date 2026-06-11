"""Cesium 3D globe — wrapper que carga el HTML real desde GitHub Pages.

El HTML real vive en `docs/cesium/index.html` y se sirve desde
GitHub Pages (`https://jfhelvetius.github.io/orbital_sentinel/cesium/`).

Tras la cadena de debugging que confirmó que el iframe srcdoc de
streamlit.components.v1.html bloquea Workers cross-origin (origin=null),
la solución es:

1. Streamlit components.v1.html renderea un wrapper de tamaño completo
   (esto sí va por srcdoc).
2. El wrapper contiene un `<iframe src="https://...github.io/.../cesium/">`
   hijo. Ese hijo tiene origin real `jfhelvetius.github.io`.
3. Con origin real, los Workers cross-origin a unpkg.com sí pueden
   instanciarse, y todo Cesium funciona normalmente.
4. El wrapper pasa los datos (tracks, primary, etc.) al iframe hijo
   vía window.postMessage, evitando límites de URL.

ADR-0008 enmienda 1 cubre esta arquitectura.
"""

from __future__ import annotations

import json
from typing import Any

# URL de GitHub Pages donde vive el HTML real. Si cambia el repo o el
# usuario, actualizar aquí.
_PAGES_URL = "https://jfhelvetius.github.io/orbital_sentinel/cesium/"

# Carga opcional del catálogo satcat embebido. Si falta, los infobox
# muestran solo la info derivada del TLE (altitud, inclinación, etc.).
try:
    from app.satcat_embedded import SATCAT as _SATCAT
except Exception:
    try:
        from satcat_embedded import SATCAT as _SATCAT  # type: ignore
    except Exception:
        _SATCAT = {}


def _tracks_to_dict(tracks: list[Any], primary_norad: int) -> list[dict]:
    out = []
    for t in tracks:
        lats = [v for v in (t.lats or []) if v is not None]
        lons = [v for v in (t.lons or []) if v is not None]
        meta = _SATCAT.get(int(t.norad), {}) if _SATCAT else {}
        out.append({
            "norad": int(t.norad),
            "name": str(t.name),
            "lat0": float(t.lat0),
            "lon0": float(t.lon0),
            "alt0": float(t.alt0),
            "alt_mean": float(t.alt_mean),
            "incl": float(t.incl),
            "period_min": float(t.period_min),
            "known": bool(t.known),
            "lats": lats[:200],
            "lons": lons[:200],
            # Metadata satcat — claves opcionales
            "full_name": meta.get("name", ""),
            "intl_id":   meta.get("intl_id", ""),
            "sat_type":  meta.get("type", ""),
            "status":    meta.get("status", ""),
            "owner":     meta.get("owner", ""),
            "launch_date": meta.get("launch_date", ""),
            "launch_site": meta.get("launch_site", ""),
        })
    return out


def html(
    tracks: list[Any],
    *,
    primary_norad: int,
    real_norads: set[int] | None = None,
    extra_tracks: list[Any] | None = None,
    layers: dict[str, bool] | None = None,
    series: dict[int, dict] | None = None,
    clock: dict | None = None,
    height: int = 880,
) -> str:
    """Genera el wrapper HTML que carga el iframe Cesium desde GitHub Pages.

    series: dict de NORAD → {"times":[iso8601...], "positions":[[lon,lat,alt_km]...]}
            para los objetos importantes que deben animarse en el timeline.
    clock:  {"start_iso": ..., "stop_iso": ..., "current_iso": ...} para
            inicializar el reloj del viewer.
    """
    real_norads = real_norads or set()
    extra_tracks = extra_tracks or []
    layers = layers or {}
    payload = {
        "tracks": _tracks_to_dict(tracks, primary_norad),
        "primary_norad": int(primary_norad),
        "real_norads": [int(n) for n in real_norads],
        "extra_tracks": _tracks_to_dict(extra_tracks, primary_norad),
        "layers": {k: bool(v) for k, v in layers.items()},
        "series": {str(k): v for k, v in (series or {}).items()},
        "clock": clock,
    }
    payload_json = json.dumps(payload, separators=(",", ":"))

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <style>
    html, body {{
      margin: 0; padding: 0; overflow: hidden; background: #01020a;
      width: 100%; height: 100%;
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    }}
    /* iframe ocupa el 100% del wrapper — el contenedor padre fija la
       altura, evitando el gap negro que había con height fijo en px */
    #cesium-frame {{
      width: 100%; height: 100%;
      border: 0; border-radius: 14px;
      display: block;
      background: #01020a;
    }}
    .err {{
      position: absolute; top: 14px; left: 14px; right: 14px;
      padding: 14px 18px; border-radius: 8px;
      background: rgba(80,20,30,.95); color: #ffd6dc;
      border: 1px solid rgba(239,68,68,.5);
      font-size: 13px; line-height: 1.5;
      display: none;
    }}
    .err.show {{ display: block; }}
    .err b {{ color: #ff9ba9; }}
    .err code {{
      font-family: 'JetBrains Mono', monospace; font-size: 12px;
      background: rgba(0,0,0,.4); padding: 1px 5px; border-radius: 3px;
    }}
  </style>
</head>
<body>
  <iframe id="cesium-frame"
          src="{_PAGES_URL}"
          allow="fullscreen"
          loading="eager"></iframe>
  <div class="err" id="errMsg">
    <b>⚠ GitHub Pages no responde aún.</b><br>
    El iframe intentó cargar <code>{_PAGES_URL}</code> pero no obtuvo respuesta.<br>
    Verifica que GitHub Pages esté activado en el repositorio
    (<i>Settings → Pages → main branch + /docs folder</i>) y que el
    deploy haya terminado.
  </div>
  <script>
    const PAYLOAD = {payload_json};
    const frame = document.getElementById('cesium-frame');

    // Cuando el iframe hijo dice "listo", le mandamos los datos
    window.addEventListener('message', function(event) {{
      if (event.data && event.data.type === 'orbital-sentinel-ready') {{
        frame.contentWindow.postMessage({{
          type: 'orbital-sentinel-tracks',
          payload: PAYLOAD,
        }}, '*');
      }}
    }});

    // Fallback: si después de 6 s no recibimos "ready", también
    // intentamos mandar los datos (puede ser que el listener no llegue).
    setTimeout(function() {{
      try {{
        frame.contentWindow.postMessage({{
          type: 'orbital-sentinel-tracks',
          payload: PAYLOAD,
        }}, '*');
      }} catch (e) {{}}
    }}, 6000);

    // Si después de 12 s el iframe no cargó, mostrar mensaje de error
    let loaded = false;
    frame.addEventListener('load', function() {{ loaded = true; }});
    setTimeout(function() {{
      if (!loaded) document.getElementById('errMsg').classList.add('show');
    }}, 12000);
  </script>
</body>
</html>
"""
