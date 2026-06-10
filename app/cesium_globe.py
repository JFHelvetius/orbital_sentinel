"""Cesium 3D globe — render fotorealístico con tiles satelitales reales.

Implementa la decisión de ADR-0008 (enmienda 1): Cesium embebido vía
`streamlit.components.v1.html`, Cesium Ion default token en el contexto
deploy-público (Streamlit Cloud).

API mínima: `render(tracks, *, primary_norad, height=880)` → renderiza
un iframe sandboxed con un globo 3D Cesium centrado y rotable, mostrando
cada TLE como una entidad puntual con label y altitud real.

Deuda técnica (ADR-0008 enmienda 1, plan v0.1 → v0.3):
- v0.1 (este módulo): puntos animados + línea fina como traza.
- v0.2: opacidad de traza proporcional a edad TLE.
- v0.3: tubos de error con covarianza declarada (ADR-0020).
"""

from __future__ import annotations

import json
from typing import Any

# Cesium Ion default token público — válido para apps de demostración
# públicas. Si se excede la cuota mensual, el usuario debe registrar su
# propio token gratuito en cesium.com/ion y reemplazar esta constante.
# Ver ADR-0008 enmienda 1.
_CESIUM_ION_TOKEN = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    "eyJqdGkiOiJhYWQ3OTM5NS00NWIyLTRiMWUtOWQzMC1mYmNkNzg2NjQ1MzciLCJpZCI6"
    "MjU5LCJpYXQiOjE2NzcxNzYzNzh9.0Mh7VVgvJVOpJ7CCdyB5lDxsZdHX9wqXrLrYWBlhUtg"
)


def _tracks_to_json(tracks: list[Any], primary_norad: int) -> str:
    """Serializa los tracks a JSON consumible por Cesium JS.

    Cada track: { norad, name, lat0, lon0, alt0, lats[], lons[], known,
                  is_primary, period_min, incl }
    """
    payload = []
    for t in tracks:
        # Filtrar Nones del path para no romper PolylinePositions
        lats = [v for v in (t.lats or []) if v is not None]
        lons = [v for v in (t.lons or []) if v is not None]
        payload.append({
            "norad": int(t.norad),
            "name": str(t.name),
            "lat0": float(t.lat0),
            "lon0": float(t.lon0),
            "alt0": float(t.alt0),
            "alt_mean": float(t.alt_mean),
            "incl": float(t.incl),
            "period_min": float(t.period_min),
            "known": bool(t.known),
            "is_primary": int(t.norad) == int(primary_norad),
            "lats": lats[:200],  # cap para no inflar el iframe
            "lons": lons[:200],
        })
    return json.dumps(payload, separators=(",", ":"))


def html(
    tracks: list[Any],
    *,
    primary_norad: int,
    real_norads: set[int] | None = None,
    extra_tracks: list[Any] | None = None,
    height: int = 880,
) -> str:
    """Genera el HTML completo del iframe Cesium para st.components.html."""
    real_norads = real_norads or set()
    extra_tracks = extra_tracks or []
    tracks_json = _tracks_to_json(tracks, primary_norad)
    extra_json = _tracks_to_json(extra_tracks, primary_norad)
    real_json = json.dumps([int(n) for n in real_norads])

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <link rel="stylesheet" href="https://cesium.com/downloads/cesiumjs/releases/1.119/Build/Cesium/Widgets/widgets.css">
  <script src="https://cesium.com/downloads/cesiumjs/releases/1.119/Build/Cesium/Cesium.js"></script>
  <style>
    html, body, #cesiumContainer {{
      width: 100%; height: 100%; margin: 0; padding: 0; overflow: hidden;
      background: #000;
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    }}
    #cesiumContainer {{ height: {height}px; border-radius: 14px; overflow: hidden; }}
    .cesium-viewer-bottom {{ display: none !important; }}
    .cesium-viewer-toolbar {{ top: 10px !important; right: 10px !important; }}
    .cesium-button {{
      background: rgba(21,27,44,.85) !important;
      border: 1px solid rgba(95,168,245,.25) !important;
      color: #5fa8f5 !important;
    }}
    .cesium-button:hover {{ background: rgba(74,144,226,.2) !important; }}
    .hud {{
      position: absolute; top: 12px; left: 14px; z-index: 999;
      color: #e8eef7; padding: 8px 12px;
      background: rgba(15,25,50,.55);
      border: 1px solid rgba(95,168,245,.25);
      border-radius: 6px; backdrop-filter: blur(8px);
      pointer-events: none;
    }}
    .hud .title {{ font-size: 13px; font-weight: 700; letter-spacing: .03em; }}
    .hud .sub   {{ font-size: 10px; color: #5fa8f5; font-family: 'JetBrains Mono',monospace; margin-top: 2px; }}
  </style>
</head>
<body>
  <div id="cesiumContainer"></div>
  <div class="hud">
    <div class="title">🌐 VISTA CESIUM · 3D fotorealístico</div>
    <div class="sub">Cesium Ion · Bing Maps Aerial · ECEF</div>
  </div>
  <script>
    Cesium.Ion.defaultAccessToken = "{_CESIUM_ION_TOKEN}";

    const TRACKS = {tracks_json};
    const EXTRA  = {extra_json};
    const REAL_NORADS = new Set({real_json});

    const viewer = new Cesium.Viewer('cesiumContainer', {{
      animation: false,
      timeline: false,
      baseLayerPicker: true,
      geocoder: false,
      homeButton: true,
      sceneModePicker: false,
      navigationHelpButton: false,
      fullscreenButton: true,
      infoBox: true,
      selectionIndicator: true,
      shouldAnimate: false,
      terrainProvider: undefined,
    }});

    // Atmósfera + ground lighting estilo NASA Blue Marble
    const scene = viewer.scene;
    scene.globe.enableLighting = true;
    scene.globe.atmosphereLightIntensity = 12.0;
    scene.globe.showGroundAtmosphere = true;
    scene.skyAtmosphere.show = true;
    scene.skyAtmosphere.hueShift = 0.0;
    scene.skyAtmosphere.saturationShift = 0.1;
    scene.skyAtmosphere.brightnessShift = 0.05;
    scene.fog.enabled = true;
    scene.fog.density = 0.0001;
    scene.backgroundColor = Cesium.Color.fromCssColorString('#01020a');

    // Quitar logo/credits visualmente (estamos atribuyendo en HUD)
    try {{ viewer.cesiumWidget.creditContainer.style.display = 'none'; }} catch (e) {{}}

    // Render satélites — altitud REAL en km (Cesium acepta metros)
    function addSat(t, opts) {{
      const pos = Cesium.Cartesian3.fromDegrees(t.lon0, t.lat0, t.alt0 * 1000.0);
      const entity = viewer.entities.add({{
        name: t.name,
        position: pos,
        point: {{
          pixelSize: opts.size,
          color: opts.color,
          outlineColor: Cesium.Color.WHITE.withAlpha(0.8),
          outlineWidth: opts.outline,
          disableDepthTestDistance: Number.POSITIVE_INFINITY,
        }},
        label: opts.label ? {{
          text: t.name,
          font: '11px Inter, sans-serif',
          fillColor: opts.labelColor,
          outlineColor: Cesium.Color.BLACK,
          outlineWidth: 2,
          style: Cesium.LabelStyle.FILL_AND_OUTLINE,
          pixelOffset: new Cesium.Cartesian2(10, 0),
          showBackground: true,
          backgroundColor: new Cesium.Color(0.04, 0.06, 0.12, 0.7),
          backgroundPadding: new Cesium.Cartesian2(6, 4),
          disableDepthTestDistance: Number.POSITIVE_INFINITY,
        }} : undefined,
        description: `
          <h3>${{t.name}}</h3>
          <p><b>NORAD:</b> ${{t.norad}}</p>
          <p><b>Altitud:</b> ${{t.alt0.toFixed(0)}} km</p>
          <p><b>Altitud media:</b> ${{t.alt_mean.toFixed(0)}} km</p>
          <p><b>Inclinación:</b> ${{t.incl.toFixed(2)}}°</p>
          <p><b>Período:</b> ${{t.period_min.toFixed(1)}} min</p>
        `,
      }});

      // Traza orbital (línea fina por ahora — v0.1, según ADR-0008 enmienda 1)
      if (t.lats && t.lats.length > 1 && opts.drawTrack) {{
        const positions = [];
        for (let i = 0; i < t.lats.length; i++) {{
          positions.push(t.lons[i]);
          positions.push(t.lats[i]);
          positions.push(t.alt0 * 1000.0);
        }}
        viewer.entities.add({{
          polyline: {{
            positions: Cesium.Cartesian3.fromDegreesArrayHeights(positions),
            width: opts.trackWidth,
            material: opts.trackColor,
            clampToGround: false,
          }},
        }});
      }}
    }}

    // Estilos por tipo
    TRACKS.forEach(t => {{
      const isReal = REAL_NORADS.has(t.norad);
      if (t.is_primary) {{
        addSat(t, {{
          size: 18,
          color: Cesium.Color.fromCssColorString('#ffd700'),
          outline: 2,
          label: true,
          labelColor: Cesium.Color.fromCssColorString('#ffd700'),
          drawTrack: true,
          trackWidth: 2.5,
          trackColor: new Cesium.PolylineGlowMaterialProperty({{
            color: Cesium.Color.fromCssColorString('#ffd700'),
            glowPower: 0.25,
          }}),
        }});
      }} else if (isReal) {{
        addSat(t, {{
          size: 14,
          color: Cesium.Color.fromCssColorString('#ff3547'),
          outline: 2,
          label: true,
          labelColor: Cesium.Color.fromCssColorString('#ff7a85'),
          drawTrack: true,
          trackWidth: 2,
          trackColor: Cesium.Color.fromCssColorString('#ff3547').withAlpha(0.65),
        }});
      }} else if (!t.known) {{
        addSat(t, {{
          size: 10,
          color: Cesium.Color.fromCssColorString('#ffb300'),
          outline: 1.5,
          label: true,
          labelColor: Cesium.Color.fromCssColorString('#ffb300'),
          drawTrack: true,
          trackWidth: 1,
          trackColor: Cesium.Color.fromCssColorString('#ffb300').withAlpha(0.45),
        }});
      }} else {{
        addSat(t, {{
          size: 7,
          color: Cesium.Color.fromCssColorString('#7eff9e'),
          outline: 1,
          label: false,
          labelColor: Cesium.Color.WHITE,
          drawTrack: true,
          trackWidth: 0.8,
          trackColor: Cesium.Color.fromCssColorString('#7eff9e').withAlpha(0.35),
        }});
      }}
    }});

    // Objetos de proximidad (color cyan)
    EXTRA.forEach(t => {{
      addSat(t, {{
        size: 12,
        color: Cesium.Color.fromCssColorString('#00d2c8'),
        outline: 1.5,
        label: true,
        labelColor: Cesium.Color.fromCssColorString('#00d2c8'),
        drawTrack: true,
        trackWidth: 1.5,
        trackColor: Cesium.Color.fromCssColorString('#00d2c8').withAlpha(0.55),
      }});
    }});

    // Centrar en el primary, si existe; si no, vista global
    const primary = TRACKS.find(t => t.is_primary);
    if (primary) {{
      viewer.camera.flyTo({{
        destination: Cesium.Cartesian3.fromDegrees(
          primary.lon0, primary.lat0, 24_000_000
        ),
        duration: 1.5,
      }});
    }} else {{
      viewer.camera.setView({{
        destination: Cesium.Cartesian3.fromDegrees(0, 15, 32_000_000),
      }});
    }}
  </script>
</body>
</html>
"""
