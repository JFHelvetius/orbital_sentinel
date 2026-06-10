# ADR-0008: Visualización con Cesium embebido y honestidad sobre incertidumbre

**Estado:** Aceptado (enmienda 1)
**Fecha:** 2026-06-03
**Autor:** Orbital Sentinel
**Supersede a:** ninguno
**Relacionado con:** ADR-0000 (P2, P3, P8), ADR-0001

---

## Contexto

- Necesidad de visualización 3D de miles de satélites sobre la Tierra y dashboards 2D analíticos.
- ADR-0000 P2 prohíbe representar precisión que el dato no tiene.
- ADR-0001 prohíbe dependencia obligatoria de servicios externos.
- Cesium es el estado del arte libre para Earth 3D web; Cesium Ion (cloud) y Bing Maps son los tile providers comunes pero implican llamadas externas.

## Decisión

- **Cesium** (JavaScript, Apache-2.0) embebido vía Dash bridge para visualización 3D.
- **Plotly + Dash** (Python) para dashboards 2D analíticos.
- **Assets de Cesium bundleados** en el paquete; no se contactan endpoints de Cesium Ion ni Bing en baseline.
- **Tiles de fuentes abiertas** (NaturalEarth, OpenStreetMap) cacheables localmente. Cesium Ion solo como opt-in para resolución mayor.
- **Toda visualización de trayectoria** debe representar incertidumbre visualmente: tubos de error, opacidad proporcional a edad del TLE, bandas en lugar de líneas. **Una línea fina como trayectoria está prohibida** como salida del proyecto.

## Justificación

- Cesium produce calidad visual no replicable con stack puro Python a escala de miles de objetos.
- Bundling local satisface ADR-0001 sin compromiso.
- Representar incertidumbre no es opcional: es la implementación gráfica de P2. ADR-0005 ya estableció la magnitud típica del error (~1–3 km en época); la visualización debe mostrarlo.

## Consecuencias

**Positivas**
- Calidad visual de referencia.
- Cumple P2 por diseño, no por convención.
- Funciona offline.

**Negativas**
- JS embebido en distribución → paquete más grande.
- Bridge Dash↔Cesium requiere mantenimiento.
- Tiles abiertas tienen menor resolución que Bing en algunas zonas (aceptable; resolución suficiente para vista global).

**Neutras**
- Backend de visualización aislado tras un `viz/` plano (ADR-0002); swap futuro posible.

## Alternativas consideradas

### A. Solo Plotly 3D
**Razón de rechazo:** rendimiento y calidad insuficientes para miles de objetos simultáneos.

### B. `pyvista`
**Razón de rechazo:** requiere VTK (binarios pesados, fricción de instalación en Windows).

### C. Three.js manual
**Razón de rechazo:** Cesium ya resuelve geodesia, marcos de referencia y tiles; reimplementar es desperdicio.

### D. Cesium Ion como default (cloud tiles)
**Razón de rechazo:** viola ADR-0001. Aceptable como opt-in.

### E. Bing Maps tiles
**Razón de rechazo:** viola ADR-0001 y términos de uso requieren API key.

## Alineación con ADR-0000

- **Refuerza P2** (la implementa visualmente).
- **Refuerza P8** vía bundling local.
- **Compatible con P3** (sin coste recurrente).
- **Sin tensiones.**

## Referencias

- CesiumJS. *Documentation and asset licensing.*
- Tufte, E. (1983, 2001). *The Visual Display of Quantitative Information.*
- Munzner, T. (2014). *Visualization Analysis and Design* — Cap. sobre representación de incertidumbre.

---

## Historial de enmiendas

### Enmienda 1 (2026-06-10) — Bridge Streamlit, no Dash

**Contexto que ha cambiado:** la app distribuida públicamente (`app/streamlit_app.py`, desplegada en Streamlit Cloud) es Streamlit, no Dash. Dash quedó como aspiración no realizada. La decisión central del ADR (Cesium como motor 3D) se mantiene; cambia el mecanismo de embebido.

**Aclaraciones:**

1. **Bridge revisado.** Donde el ADR original decía "Cesium embebido vía Dash bridge", léase: "Cesium embebido vía `streamlit.components.v1.html`". Es un iframe sandboxed; los datos (tracks, época, highlight) se serializan a JSON y se inyectan al `<script>` del template. Streamlit → Cesium es unidireccional en el MVP (no hay event bridge JS → Python).

2. **Tiles en el contexto deploy-público.** El ADR original prefería tiles open bundleados como default (alineación con ADR-0012 local-first). Para la app desplegada en Streamlit Cloud — que ya es online por construcción y no satisface ADR-0012 — se permite **Cesium Ion default token público** como imagery provider (Bing Aerial), por dos razones:
   - El componente público sirve adopción/divulgación, no operación local. ADR-0022 ya formalizó que el scheduling vive en el OS del operador; análogamente, la app web es escaparate, no infraestructura.
   - Bundlear los assets de Cesium (~12 MB JS + tiles) en el repo es viable pero degrada la experiencia de install local que sí sigue siendo objetivo. Deferimos el bundling a una iteración posterior cuando exista un build distinto "offline desktop".
   - Cuando exista la versión offline-first del frontend (separada del deploy público), el default se invierte: tiles open bundleados, Ion como opt-in. Esto NO es una violación del ADR — es una segmentación entre dos consumidores con propiedades P3/P8 distintas.

3. **Honestidad sobre incertidumbre — deuda técnica reconocida.** El frontend actual usa líneas finas como trayectoria, lo cual el ADR explícitamente prohíbe. La integración inicial de Cesium hereda esa deuda y la traslada al MVP. Plan de remediación:
   - **v0.1 (MVP, este commit):** entidades puntuales animadas; trayectoria como línea fina, igual que hoy en plotly. Inadecuado pero no peor que el estado actual.
   - **v0.2 (siguiente iteración):** opacidad de la traza proporcional a la edad del TLE; banda de error visible para los objetos con detección de conjunción.
   - **v0.3:** tubos de error verdaderos (`PolylineVolumeGraphics` en Cesium) para los objetos con covarianza declarada por ADR-0020.
   La deuda se cierra en v0.2 / v0.3, no en el MVP. Esto se trackea como issue.

**Estado tras la enmienda:** Aceptado (enmienda 1). El ADR sigue gobernando la decisión "Cesium es el motor 3D"; lo que cambia es el bridge y la política de tiles en el contexto deploy-público.
