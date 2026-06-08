# ADR-0008: Visualización con Cesium embebido y honestidad sobre incertidumbre

**Estado:** Aceptado
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

*Sin enmiendas a fecha de aceptación.*
