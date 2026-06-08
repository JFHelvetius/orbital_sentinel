# ADR-0005: SGP4 como único motor de propagación en v1

**Estado:** Aceptado
**Fecha:** 2026-06-03
**Autor:** Orbital Sentinel
**Supersede a:** ninguno
**Relacionado con:** ADR-0000 (P1, P2, P4)

---

## Contexto

- TLEs son la fuente primaria del proyecto. TLEs están diseñados específicamente para ser propagados con SGP4/SDP4.
- Existen propagadores numéricos (RK4/8/9 + force models) y herramientas de alta fidelidad (HPOP, GMAT).
- Usar otro propagador sobre TLEs es físicamente inconsistente: las TLEs incluyen "fitted residuals" que solo SGP4 puede deshacer correctamente.
- Precisión típica de SGP4 sobre TLE: ~1–3 km en época, crecimiento ~1–3 km/día.

## Decisión

- **SGP4** vía la librería `sgp4` (port directo del Fortran de Vallado) es el único propagador del baseline.
- **No se incluyen** propagadores numéricos en v1.
- **No se reabre** sin ADR posterior que demuestre necesidad concreta.
- **API del propagador** se diseña con una interfaz (`Propagator` abstracto) para no bloquear extensión futura, pero solo SGP4 la implementa.

## Justificación

- Usar SGP4 sobre TLE es la única combinación físicamente coherente.
- Propagadores numéricos requieren force models (gravedad, drag, SRP, third-body) que son explosión de scope y dependencias.
- SGP4 es rápido (~µs/objeto/instante), determinista, vectorizable con numpy.
- Su precisión es suficiente para los casos de uso del proyecto (screening, detección de maniobras, anomalías estadísticas).
- Casos que requieran mayor precisión deberían usar OMM/SP catalogs, fuera del scope baseline.

## Consecuencias

**Positivas**
- Coherencia física garantizada.
- Performance suficiente para catálogo completo en un portátil (<60s para propagación de 30k objetos sobre 24h con paso de 60s, estimación a validar en Fase 1).
- Determinismo: prerrequisito para ADR-0001.

**Negativas**
- Casos de evitación operacional de colisiones con garantías formales quedan fuera de scope (alineado con no-objetivos de ADR-0000).
- Aplicaciones de investigación de alta fidelidad no soportadas directamente.

**Neutras**
- La interfaz `Propagator` deja la puerta abierta a futuros motores sin refactor en analytics.

## Alternativas consideradas

### A. `skyfield`'s SGP4
**Razón de rechazo:** wrapper sobre la misma implementación. Sin ventaja técnica; añade dependencia.

### B. Propagador numérico (`hapsira` o custom)
**Razón de rechazo:** físicamente inconsistente con TLE como entrada; explosión de scope.

### C. Implementación custom de SGP4
**Razón de rechazo:** bus factor inaceptable. Validación contra Vallado costosa y reproducible solo con set canónico de vectores.

### D. Multi-engine desde día 1
**Razón de rechazo:** complejidad prematura. Sin caso de uso identificado en Fases 1–4.

## Alineación con ADR-0000

- **Refuerza P1, P4** (determinismo, reproducibilidad).
- **Compatible con P2**: no fingimos precisión que SGP4 no entrega. ADR-0008 lo materializa visualmente.
- **Sin tensiones.**

## Referencias

- Hoots, F. R., & Roehrich, R. L. (1980). *Spacetrack Report No. 3.*
- Vallado, D. A. et al. (2006). *Revisiting Spacetrack Report #3.*
- Brandon Rhodes. *python-sgp4 documentation.*

---

## Historial de enmiendas

### 2026-06-03 — Enmienda 1
**Precisión SGP4 como riesgo conocido aceptado.** El red-team review (F6) demostró que el ratio señal-ruido entre el error de propagación (~1–3 km) y los thresholds típicos de conjunción (1–10 km) es ≤ 3, lo que implica tasa de falsos positivos alta en Fase 2.

Decisión: aceptar esta limitación como propiedad conocida del régimen TLE+SGP4, no como fallo arquitectónico. Mitigaciones:

1. Toda salida de Fase 2 debe declarar el régimen de precisión utilizado y su intervalo de confianza.
2. La interfaz `Propagator` (decisión original de este ADR) permanece como punto de extensión: si en el futuro se justifica un propagador de mayor precisión (OMM/SP, propagación numérica con force models), su incorporación no requiere refactorizar Analytics.
3. Comparaciones contra CDM público se reportan como ejercicio de calibración, no como métrica de calidad operacional.

Esta enmienda no cambia la decisión técnica; documenta el alcance honesto de lo que el motor puede entregar.
