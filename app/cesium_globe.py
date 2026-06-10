"""Cesium 3D globe — render fotorealístico con tiles satelitales públicos.

Implementa la decisión de ADR-0008 (enmienda 1): Cesium embebido vía
`streamlit.components.v1.html`. Sin dependencia de Cesium Ion para
imagery — usa tiles públicos sin token.

Estrategia robusta v0.2:
- baseLayer creado explícitamente con OpenStreetMap (siempre funciona,
  CORS abierto, sin token, sin rate limits agresivos).
- Capas adicionales (NASA GIBS Blue Marble, Esri Imagery, etc.) en el
  baseLayerPicker para alternar.
- Si una capa externa falla por CORS desde el iframe sandbox de Streamlit,
  OSM sigue mostrando el globo — degradación elegante.

Deuda técnica (ADR-0008 enmienda 1, plan v0.1 → v0.3):
- v0.1 (este módulo): puntos animados + línea fina como traza.
- v0.2: opacidad de traza proporcional a edad TLE.
- v0.3: tubos de error con covarianza declarada (ADR-0020).
"""

from __future__ import annotations

import json
from typing import Any


def _tracks_to_json(tracks: list[Any], primary_norad: int) -> str:
    payload = []
    for t in tracks:
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
            "lats": lats[:200],
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
    real_norads = real_norads or set()
    extra_tracks = extra_tracks or []
    tracks_json = _tracks_to_json(tracks, primary_norad)
    extra_json = _tracks_to_json(extra_tracks, primary_norad)
    real_json = json.dumps([int(n) for n in real_norads])

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <!-- CDN unpkg con CORS abierto. Cesium.com a veces no sirve workers
       correctamente cuando el iframe srcdoc tiene origin=null. -->
  <script>
    window.CESIUM_BASE_URL = 'https://unpkg.com/cesium@1.119.0/Build/Cesium/';
  </script>
  <link rel="stylesheet" href="https://unpkg.com/cesium@1.119.0/Build/Cesium/Widgets/widgets.css">
  <script src="https://unpkg.com/cesium@1.119.0/Build/Cesium/Cesium.js"></script>
  <script>
    if (typeof Cesium !== 'undefined' && Cesium.buildModuleUrl && Cesium.buildModuleUrl.setBaseUrl) {{
      Cesium.buildModuleUrl.setBaseUrl(window.CESIUM_BASE_URL);
    }}
    // Aumenta la concurrencia de tiles por servidor — el default de 6
    // puede dejar la cola enorme contra Esri/NASA GIBS desde iframe.
    if (typeof Cesium !== 'undefined' && Cesium.RequestScheduler) {{
      Cesium.RequestScheduler.maximumRequestsPerServer = 18;
    }}
  </script>
  <style>
    html, body {{
      width: 100%; height: 100%; margin: 0; padding: 0; overflow: hidden;
      background: #000;
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    }}
    #cesiumContainer {{
      width: 100%; height: {height}px;
      border-radius: 14px; overflow: hidden;
      position: relative;
    }}
    .cesium-viewer-bottom {{ display: none !important; }}
    .cesium-viewer-toolbar {{ top: 10px !important; right: 10px !important; }}
    .cesium-button {{
      background: rgba(21,27,44,.92) !important;
      border: 1px solid rgba(95,168,245,.3) !important;
      color: #5fa8f5 !important;
      width: 36px !important; height: 36px !important;
      line-height: 32px !important;
    }}
    .cesium-button:hover {{ background: rgba(74,144,226,.3) !important; }}
    .cesium-baseLayerPicker-dropDown {{
      background: rgba(15,20,38,.98) !important;
      border: 1px solid rgba(95,168,245,.35) !important;
      box-shadow: 0 8px 32px rgba(0,0,0,.6);
      max-height: 540px !important;
      width: 320px !important;
      padding: 8px !important;
    }}
    .cesium-baseLayerPicker-sectionTitle {{
      color: #5fa8f5 !important;
      font-size: 11px !important;
      letter-spacing: .08em !important;
      text-transform: uppercase !important;
      font-weight: 600 !important;
      margin: 8px 4px 4px !important;
    }}
    .cesium-baseLayerPicker-choices {{ padding: 0 !important; }}
    .cesium-baseLayerPicker-item {{
      background: rgba(30,40,65,.5) !important;
      border: 1px solid rgba(95,168,245,.15) !important;
      border-radius: 6px !important;
      margin: 4px !important;
      padding: 4px !important;
      cursor: pointer !important;
    }}
    .cesium-baseLayerPicker-item:hover {{
      background: rgba(74,144,226,.2) !important;
      border-color: rgba(95,168,245,.5) !important;
    }}
    .cesium-baseLayerPicker-selectedItem {{
      background: rgba(74,144,226,.3) !important;
      border-color: rgba(95,168,245,.7) !important;
    }}
    .cesium-baseLayerPicker-itemLabel {{
      color: #e8eef7 !important;
      font-size: 12px !important;
      margin-left: 6px !important;
    }}
    .cesium-baseLayerPicker-itemIcon {{
      width: 48px !important; height: 48px !important;
      border-radius: 4px !important;
    }}
    .hud {{
      position: absolute; top: 12px; left: 14px; z-index: 999;
      color: #e8eef7; padding: 8px 12px;
      background: rgba(15,25,50,.65);
      border: 1px solid rgba(95,168,245,.3);
      border-radius: 6px; backdrop-filter: blur(8px);
      pointer-events: none;
    }}
    .hud .title {{ font-size: 13px; font-weight: 700; letter-spacing: .03em; }}
    .hud .sub   {{
      font-size: 10px; color: #5fa8f5;
      font-family: 'JetBrains Mono',monospace; margin-top: 2px;
    }}
    .loading {{
      position: absolute; top: 50%; left: 50%; transform: translate(-50%,-50%);
      color: #5fa8f5; font-size: 14px; z-index: 100;
      padding: 12px 18px; background: rgba(15,20,38,.85);
      border: 1px solid rgba(95,168,245,.3); border-radius: 6px;
    }}
    .err-banner {{
      position: absolute; bottom: 16px; left: 14px; right: 14px;
      background: rgba(80,20,30,.96); color: #ffcfd6;
      padding: 12px 16px; border-radius: 8px; font-size: 12px;
      border: 1px solid rgba(239,68,68,.6); display: none;
      z-index: 1000;
      max-height: 280px; overflow: auto;
      font-family: 'JetBrains Mono', monospace;
      line-height: 1.55;
      box-shadow: 0 6px 24px rgba(0,0,0,.5);
      white-space: pre-wrap;
    }}
    .err-banner-title {{ font-weight: 700; color: #ff8294; margin-bottom: 6px; font-size: 13px; }}
    /* Panel diagnóstico siempre visible */
    .diag {{
      position: absolute; top: 12px; right: 14px; z-index: 999;
      max-width: 340px;
      background: rgba(15,20,38,.94); color: #c9d8e8;
      padding: 10px 12px; border-radius: 6px;
      font-family: 'JetBrains Mono', monospace; font-size: 11px;
      border: 1px solid rgba(95,168,245,.3);
      line-height: 1.5;
      pointer-events: auto;
    }}
    .diag .row {{ display: flex; gap: 6px; }}
    .diag .lbl {{ color: #5fa8f5; min-width: 90px; }}
    .diag .ok {{ color: #10b981; }}
    .diag .ko {{ color: #ef4444; }}
    .diag .wait {{ color: #f59e0b; }}
  </style>
</head>
<body>
  <div id="cesiumContainer">
    <div class="loading" id="loadingMsg">Cargando Cesium…</div>
  </div>
  <div class="hud">
    <div class="title">🌐 VISTA CESIUM · 3D fotorealístico</div>
    <div class="sub" id="hudSub">Iniciando…</div>
  </div>
  <div class="diag" id="diagPanel">
    <div style="font-weight:700;color:#5fa8f5;margin-bottom:6px;">DIAGNÓSTICO</div>
    <div class="row"><span class="lbl">Cesium SDK</span><span id="d-sdk" class="wait">…</span></div>
    <div class="row"><span class="lbl">BASE_URL</span><span id="d-base" class="wait">…</span></div>
    <div class="row"><span class="lbl">Viewer</span><span id="d-viewer" class="wait">…</span></div>
    <div class="row"><span class="lbl">WebGL</span><span id="d-webgl" class="wait">…</span></div>
    <div class="row"><span class="lbl">Imagery</span><span id="d-imagery" class="wait">…</span></div>
    <div class="row"><span class="lbl">Canvas</span><span id="d-canvas" class="wait">…</span></div>
    <div class="row"><span class="lbl">Client</span><span id="d-client" class="wait">…</span></div>
    <div class="row"><span class="lbl">Tiles cargados</span><span id="d-tiles" class="wait">…</span></div>
    <div class="row"><span class="lbl">Globe show</span><span id="d-show" class="wait">…</span></div>
    <div class="row"><span class="lbl">Layers count</span><span id="d-layers" class="wait">…</span></div>
    <div class="row"><span class="lbl">Frames</span><span id="d-frames" class="wait">…</span></div>
    <div class="row"><span class="lbl">Errores</span><span id="d-errs" class="wait">0</span></div>
    <div style="margin-top:8px;pointer-events:auto;">
      <button id="forceRenderBtn" style="
        background: rgba(74,144,226,.3); color: #5fa8f5;
        border: 1px solid rgba(95,168,245,.5); border-radius: 4px;
        padding: 4px 10px; font-size: 11px; cursor: pointer;
        font-family: 'JetBrains Mono', monospace;
      ">Forzar render</button>
    </div>
  </div>
  <div class="err-banner" id="errBanner"></div>
  <script>
    // ── Diagnóstico visible: cualquier error en la consola se ve en pantalla
    const DIAG = {{
      errors: [],
      set(id, status, msg) {{
        const el = document.getElementById(id);
        if (el) {{
          el.className = status;
          el.textContent = msg;
        }}
      }},
      addErr(src, msg) {{
        const entry = '[' + src + '] ' + msg;
        this.errors.push(entry);
        // Dedupe: si hay 30+ del mismo tipo, agrupa
        this.set('d-errs', 'ko', String(this.errors.length));
        const banner = document.getElementById('errBanner');
        banner.style.display = 'block';
        const counts = {{}};
        for (const e of this.errors) {{
          const key = e.split(' @ ')[0].slice(0, 80);
          counts[key] = (counts[key] || 0) + 1;
        }}
        const lines = Object.entries(counts)
          .sort((a, b) => b[1] - a[1])
          .map(([k, n]) => (n > 1 ? '×' + n + '  ' : '     ') + k);
        banner.innerHTML = '<div class="err-banner-title">⚠ Errores (' + this.errors.length + '):</div>' +
          lines.join('\\n');
      }},
    }};

    window.addEventListener('error', function(e) {{
      DIAG.addErr('error', (e.message || 'unknown') + ' @ ' + (e.filename || '?') + ':' + (e.lineno || '?'));
    }});
    window.addEventListener('unhandledrejection', function(e) {{
      DIAG.addErr('promise', String(e.reason));
    }});

    DIAG.set('d-base', (window.CESIUM_BASE_URL ? 'ok' : 'ko'),
      window.CESIUM_BASE_URL ? 'definido' : 'NO DEFINIDO');

    if (typeof Cesium === 'undefined') {{
      DIAG.set('d-sdk', 'ko', 'NO CARGÓ');
      DIAG.addErr('sdk', 'window.Cesium es undefined — el script Cesium.js no se evaluó');
    }} else {{
      DIAG.set('d-sdk', 'ok', 'v' + Cesium.VERSION);
    }}

    const TRACKS = {tracks_json};
    const EXTRA  = {extra_json};
    const REAL_NORADS = new Set({real_json});

    function showError(msg) {{
      const el = document.getElementById('errBanner');
      el.style.display = 'block';
      el.textContent = msg;
    }}
    function setHudSub(s) {{
      document.getElementById('hudSub').textContent = s;
    }}

    // ── Imagery providers públicos sin token ─────────────────────────
    function osmStandard() {{
      return new Cesium.OpenStreetMapImageryProvider({{
        url: 'https://tile.openstreetmap.org/',
        credit: '© OpenStreetMap contributors',
      }});
    }}
    function osmHumanitarian() {{
      return new Cesium.OpenStreetMapImageryProvider({{
        url: 'https://tile-a.openstreetmap.fr/hot/',
        credit: '© OSM Humanitarian',
      }});
    }}
    function nasaGibsBlueMarble() {{
      return new Cesium.UrlTemplateImageryProvider({{
        url: 'https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/BlueMarble_ShadedRelief_Bathymetry/default/EPSG3857_500m/{{z}}/{{y}}/{{x}}.jpeg',
        credit: 'NASA Earth Observatory — Blue Marble',
        tilingScheme: new Cesium.WebMercatorTilingScheme(),
        maximumLevel: 8,
      }});
    }}
    function nasaGibsViirs() {{
      const today = new Date();
      today.setDate(today.getDate() - 2); // VIIRS tiene 1-2 días de lag
      const ds = today.toISOString().slice(0, 10);
      return new Cesium.UrlTemplateImageryProvider({{
        url: 'https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/VIIRS_SNPP_CorrectedReflectance_TrueColor/default/' + ds + '/GoogleMapsCompatible_Level9/{{z}}/{{y}}/{{x}}.jpeg',
        credit: 'NASA EOSDIS — VIIRS (' + ds + ')',
        tilingScheme: new Cesium.WebMercatorTilingScheme(),
        maximumLevel: 9,
      }});
    }}
    function nasaGibsCityLights() {{
      return new Cesium.UrlTemplateImageryProvider({{
        url: 'https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/VIIRS_Black_Marble/default/EPSG3857_500m/{{z}}/{{y}}/{{x}}.jpeg',
        credit: 'NASA — Black Marble',
        tilingScheme: new Cesium.WebMercatorTilingScheme(),
        maximumLevel: 8,
      }});
    }}
    function esriImagery() {{
      return new Cesium.UrlTemplateImageryProvider({{
        url: 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{{z}}/{{y}}/{{x}}',
        credit: 'Esri · Maxar · Earthstar Geographics · USGS',
        maximumLevel: 19,
      }});
    }}
    function esriTopo() {{
      return new Cesium.UrlTemplateImageryProvider({{
        url: 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{{z}}/{{y}}/{{x}}',
        credit: 'Esri Topo', maximumLevel: 19,
      }});
    }}

    // Modelos para el baseLayerPicker
    const imageryModels = [
      new Cesium.ProviderViewModel({{
        name: 'NASA Blue Marble',
        iconUrl: Cesium.buildModuleUrl('Widgets/Images/ImageryProviders/blueMarble.png'),
        tooltip: 'Imagery fotorealística NASA (Blue Marble + Shaded Relief + Bathymetry). Recomendado.',
        creationFunction: nasaGibsBlueMarble,
      }}),
      new Cesium.ProviderViewModel({{
        name: 'NASA VIIRS (ayer)',
        iconUrl: Cesium.buildModuleUrl('Widgets/Images/ImageryProviders/naturalEarthII.png'),
        tooltip: 'Imagen satelital real del último día disponible (NASA VIIRS True Color).',
        creationFunction: nasaGibsViirs,
      }}),
      new Cesium.ProviderViewModel({{
        name: 'NASA Black Marble',
        iconUrl: Cesium.buildModuleUrl('Widgets/Images/ImageryProviders/blackMarble.png'),
        tooltip: 'Luces nocturnas (Black Marble). Bonito para ver ciudades.',
        creationFunction: nasaGibsCityLights,
      }}),
      new Cesium.ProviderViewModel({{
        name: 'OpenStreetMap',
        iconUrl: Cesium.buildModuleUrl('Widgets/Images/ImageryProviders/openStreetMap.png'),
        tooltip: 'OSM clásico — siempre funciona, mapa político.',
        creationFunction: osmStandard,
      }}),
      new Cesium.ProviderViewModel({{
        name: 'Esri World Imagery',
        iconUrl: Cesium.buildModuleUrl('Widgets/Images/ImageryProviders/esriWorldImagery.png'),
        tooltip: 'Tiles satelitales Esri/Maxar (zoom alto, puede no cargar si hay bloqueo CORS).',
        creationFunction: esriImagery,
      }}),
      new Cesium.ProviderViewModel({{
        name: 'Esri Topográfico',
        iconUrl: Cesium.buildModuleUrl('Widgets/Images/ImageryProviders/esriWorldStreetMap.png'),
        tooltip: 'Mapa topográfico — relieve y geografía física.',
        creationFunction: esriTopo,
      }}),
      new Cesium.ProviderViewModel({{
        name: 'OSM Humanitarian',
        iconUrl: Cesium.buildModuleUrl('Widgets/Images/ImageryProviders/openStreetMap.png'),
        tooltip: 'OSM con énfasis en infraestructura humanitaria.',
        creationFunction: osmHumanitarian,
      }}),
    ];

    let viewer;
    try {{
      // Inicializa SIN baseLayer del picker — luego añadimos a mano para
      // garantizar imagery activa.
      viewer = new Cesium.Viewer('cesiumContainer', {{
        animation: false,
        timeline: false,
        baseLayer: false,
        baseLayerPicker: true,
        imageryProviderViewModels: imageryModels,
        selectedImageryProviderViewModel: imageryModels[0],  // Blue Marble
        terrainProviderViewModels: [],
        geocoder: false,
        homeButton: true,
        sceneModePicker: true,
        navigationHelpButton: false,
        fullscreenButton: true,
        infoBox: true,
        selectionIndicator: true,
        shouldAnimate: false,
      }});
      DIAG.set('d-viewer', 'ok', 'creado');

      // Verifica WebGL
      try {{
        const ctx = viewer.scene.context;
        DIAG.set('d-webgl', 'ok', ctx.webgl2 ? 'WebGL 2' : 'WebGL 1');
      }} catch (e) {{
        DIAG.set('d-webgl', 'ko', 'falla: ' + e.message);
        DIAG.addErr('webgl', e.message);
      }}

      // GARANTIZA que haya una capa de imagery, capturando errores por provider
      function attachErrHook(provider, name) {{
        if (provider && provider.errorEvent && provider.errorEvent.addEventListener) {{
          provider.errorEvent.addEventListener(function(err) {{
            const msg = err && err.message ? err.message : String(err);
            DIAG.addErr(name, msg.slice(0, 150));
          }});
        }}
      }}
      try {{
        const osmProv = osmStandard();
        attachErrHook(osmProv, 'osm');
        viewer.imageryLayers.addImageryProvider(osmProv);
        const bmProv = nasaGibsBlueMarble();
        attachErrHook(bmProv, 'blueMarble');
        viewer.imageryLayers.addImageryProvider(bmProv);
        DIAG.set('d-imagery', 'ok', 'OSM + Blue Marble');
      }} catch (e) {{
        DIAG.set('d-imagery', 'ko', 'falla: ' + e.message);
        DIAG.addErr('imagery', e.message);
      }}

      setHudSub('Blue Marble · NASA Earth Observatory');
    }} catch (e) {{
      DIAG.set('d-viewer', 'ko', 'FALLA');
      DIAG.addErr('viewer-init', e.message + ' | stack: ' + (e.stack || '').slice(0, 300));
      document.getElementById('loadingMsg').style.display = 'none';
      throw e;
    }}

    // Atmósfera (sin lighting — el lighting oscurece el hemisferio nocturno
    // y daba la impresión de globo invisible cuando la cámara miraba allí).
    const scene = viewer.scene;
    // CRÍTICO: render continuo. Por default en Cesium 1.119 hay
    // requestRenderMode que solo pinta cuando algo se mueve, lo cual
    // deja el globo en negro si el usuario no toca nada al cargar.
    scene.requestRenderMode = false;
    scene.maximumRenderTimeChange = Infinity;
    scene.globe.enableLighting = false;
    scene.globe.showGroundAtmosphere = true;
    if (scene.globe.atmosphereLightIntensity !== undefined)
      scene.globe.atmosphereLightIntensity = 10.0;
    scene.skyAtmosphere.show = true;
    scene.skyAtmosphere.hueShift = 0.0;
    scene.skyAtmosphere.saturationShift = 0.05;
    scene.skyAtmosphere.brightnessShift = 0.0;
    scene.fog.enabled = true;
    scene.fog.density = 0.00006;
    scene.backgroundColor = Cesium.Color.fromCssColorString('#01020a');
    // DIAGNÓSTICO: verde fluo MUY visible — imposible perderlo si pinta.
    scene.globe.baseColor = Cesium.Color.fromCssColorString('#00ff77');
    // También subimos el screen-space-error para forzar tiles más grandes
    // y que carguen rápido aunque sean groseros.
    scene.globe.maximumScreenSpaceError = 8;

    // Reporta tamaño del canvas y del container client
    function reportDims() {{
      try {{
        const cnv = viewer.canvas;
        DIAG.set('d-canvas', cnv.width > 0 ? 'ok' : 'ko',
          cnv.width + ' × ' + cnv.height);
        const cont = document.getElementById('cesiumContainer');
        DIAG.set('d-client', cont.clientWidth > 0 ? 'ok' : 'ko',
          cont.clientWidth + ' × ' + cont.clientHeight);
      }} catch (e) {{ DIAG.set('d-canvas', 'ko', 'sin canvas'); }}
    }}
    reportDims();
    // CRÍTICO: forzar resize varias veces, el iframe Streamlit puede tardar
    // en estabilizar dimensiones mientras Cesium ya inicializó.
    setTimeout(function() {{ viewer.resize(); reportDims(); }}, 100);
    setTimeout(function() {{ viewer.resize(); reportDims(); }}, 500);
    setTimeout(function() {{ viewer.resize(); reportDims(); }}, 2000);
    window.addEventListener('resize', function() {{ viewer.resize(); reportDims(); }});
    let lastTilePending = -1;
    scene.globe.tileLoadProgressEvent.addEventListener(function(pending) {{
      if (pending !== lastTilePending) {{
        lastTilePending = pending;
        DIAG.set('d-tiles', pending === 0 ? 'ok' : 'wait',
          pending === 0 ? 'completos' : (pending + ' pendientes'));
      }}
    }});

    // ASEGURA que el globe esté visible y reporta su estado
    scene.globe.show = true;
    DIAG.set('d-show', scene.globe.show ? 'ok' : 'ko',
      scene.globe.show ? 'true' : 'false');
    DIAG.set('d-layers', viewer.imageryLayers.length > 0 ? 'ok' : 'ko',
      String(viewer.imageryLayers.length));

    // Contador de frames vivos (cada postRender incrementa)
    let frameCount = 0;
    scene.postRender.addEventListener(function() {{
      frameCount++;
      if (frameCount % 30 === 0) {{
        DIAG.set('d-frames', frameCount > 30 ? 'ok' : 'wait', String(frameCount));
      }}
    }});

    // Botón de forzar render — útil si requestRenderMode quedó activo
    document.getElementById('forceRenderBtn').addEventListener('click', function() {{
      scene.requestRender();
      scene.render();
      viewer.resize();
    }});

    try {{ viewer.cesiumWidget.creditContainer.style.display = 'none'; }} catch (e) {{}}

    // Quita el loading message cuando el globo está listo
    viewer.scene.postRender.addEventListener(function removeLoading() {{
      const el = document.getElementById('loadingMsg');
      if (el) el.style.display = 'none';
      viewer.scene.postRender.removeEventListener(removeLoading);
    }});

    // ── Render satélites ─────────────────────────────────────────────
    function addSat(t, opts) {{
      const pos = Cesium.Cartesian3.fromDegrees(t.lon0, t.lat0, t.alt0 * 1000.0);
      viewer.entities.add({{
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
          backgroundColor: new Cesium.Color(0.04, 0.06, 0.12, 0.75),
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
          }},
        }});
      }}
    }}

    TRACKS.forEach(t => {{
      const isReal = REAL_NORADS.has(t.norad);
      if (t.is_primary) {{
        addSat(t, {{
          size: 18, color: Cesium.Color.fromCssColorString('#ffd700'),
          outline: 2, label: true,
          labelColor: Cesium.Color.fromCssColorString('#ffd700'),
          drawTrack: true, trackWidth: 2.5,
          trackColor: new Cesium.PolylineGlowMaterialProperty({{
            color: Cesium.Color.fromCssColorString('#ffd700'),
            glowPower: 0.25,
          }}),
        }});
      }} else if (isReal) {{
        addSat(t, {{
          size: 14, color: Cesium.Color.fromCssColorString('#ff3547'),
          outline: 2, label: true,
          labelColor: Cesium.Color.fromCssColorString('#ff7a85'),
          drawTrack: true, trackWidth: 2,
          trackColor: Cesium.Color.fromCssColorString('#ff3547').withAlpha(0.65),
        }});
      }} else if (!t.known) {{
        addSat(t, {{
          size: 10, color: Cesium.Color.fromCssColorString('#ffb300'),
          outline: 1.5, label: true,
          labelColor: Cesium.Color.fromCssColorString('#ffb300'),
          drawTrack: true, trackWidth: 1,
          trackColor: Cesium.Color.fromCssColorString('#ffb300').withAlpha(0.45),
        }});
      }} else {{
        addSat(t, {{
          size: 7, color: Cesium.Color.fromCssColorString('#7eff9e'),
          outline: 1, label: false,
          labelColor: Cesium.Color.WHITE,
          drawTrack: true, trackWidth: 0.8,
          trackColor: Cesium.Color.fromCssColorString('#7eff9e').withAlpha(0.35),
        }});
      }}
    }});

    EXTRA.forEach(t => {{
      addSat(t, {{
        size: 12, color: Cesium.Color.fromCssColorString('#00d2c8'),
        outline: 1.5, label: true,
        labelColor: Cesium.Color.fromCssColorString('#00d2c8'),
        drawTrack: true, trackWidth: 1.5,
        trackColor: Cesium.Color.fromCssColorString('#00d2c8').withAlpha(0.55),
      }});
    }});

    // Vista global garantizada — primero un setView (instantáneo) para
    // dejar la cámara en una posición conocida. Luego, opcionalmente,
    // vuela al primary si existe.
    viewer.camera.setView({{
      destination: Cesium.Cartesian3.fromDegrees(0, 15, 28_000_000),
      orientation: {{
        heading: 0, pitch: -Cesium.Math.PI_OVER_TWO, roll: 0,
      }},
    }});
    const primary = TRACKS.find(t => t.is_primary);
    if (primary) {{
      setTimeout(function() {{
        viewer.camera.flyTo({{
          destination: Cesium.Cartesian3.fromDegrees(
            primary.lon0, primary.lat0, 22_000_000
          ),
          duration: 2.0,
        }});
      }}, 1500);
    }}
  </script>
</body>
</html>
"""
