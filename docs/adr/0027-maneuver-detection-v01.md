# ADR-0027: Maneuver detection v0.1 + catalog historical query

**Estado:** Aceptado
**Fecha:** 2026-06-06
**Autor:** Orbital Sentinel
**Supersede a:** ninguno
**Relacionado con:** ADR-0000 (P1, P2, P3, P7, P8), ADR-0002 enmienda 1, ADR-0005, ADR-0006, ADR-0010, ADR-0020

---

## Contexto

ADR-0000 §"Hoja de ruta" define Fase 3 como *"Detección de maniobras — saltos en elementos medios y residuos de propagación"*.

El catálogo Normalized ya soporta múltiples filas para el mismo `norad_cat_id` con distinto `tle_content_hash` (ADR-0006); pero la API pública del repositorio solo exponía `find_latest_by_norad_id`. Para detectar maniobras necesitamos la serie temporal completa: todos los TLEs de un objeto ordenados por epoch.

Adicionalmente, este es el **primer detector estadístico del proyecto**. ADR-0020 estableció el patrón de honesty para modelos físicos con covarianza declarada (Pc). Maniobras tienen forma distinta: clasificación (jump / no-jump) bajo asunciones estadísticas. El patrón de honesty debe extenderse a este dominio sin perder rigor.

## Decisión

Crear `analytics/maneuvers/` con tres componentes encadenados + una extensión mínima al repositorio Normalized.

### 1. Catalog historical query

Añadido a `OrbitalElementsRepository`:

```python
def find_all_by_norad_id(
    self, norad_cat_id: int, *, engine_version: str | None = None,
) -> list[OrbitalElement]
```

Devuelve todos los `OrbitalElement` del NORAD ID ordenados por `epoch_datetime` ascendente. Orden por epoch (NO por `fetched_at`): la detección de maniobras requiere secuencia física, no orden de ingestión.

### 2. Time-series model

`OrbitalElementSeries` envuelve una lista de `OrbitalElement` con validación estricta:

- `len ≥ 2`
- Mismo `norad_cat_id` en todos
- `epoch_datetime` estrictamente ascendente
- `tle_content_hash` únicos

### 3. Detector v0.1 — algoritmo

Para cada transición consecutiva `i → i+1`:

```
Δt_i = (epoch_{i+1} − epoch_i) en días
rate_n_i = Δ(mean_motion) / Δt_i
rate_e_i = Δ(eccentricity) / Δt_i
rate_ι_i = Δ(inclination_deg) / Δt_i
```

Para evaluar la transición `k`:

1. Baseline `B_k`: transiciones `j < k` con `epoch_j > epoch_k − baseline_window_days`.
2. Si `|B_k| < min_baseline_samples` → skip (cuenta en `n_transitions_skipped_insufficient_baseline`).
3. Sino: `μ_*, σ_* = mean, stdev` per componente; `σ_safe = max(σ_*, σ_floor)`; `z_* = (rate_* − μ_*) / σ_safe`.
4. Si `max(|z_n|, |z_e|, |z_ι|) > detection_threshold_sigma` → emit `ManeuverEvent` con `dominant_component`.

### 4. Modelos

`ManeuverEvent` (frozen, extra=forbid): provenance binaria FK (epochs + tle_content_hash + content_hash_source ANTES y DESPUÉS de la maniobra), deltas absolutas, z-scores, dominant_component, honesty fields (`detection_method_name`, `baseline_window_days`, `detection_threshold_sigma`, `n_baseline_samples`, `is_apparent_not_confirmed=True`).

`ManeuverDetectionResult` (frozen, extra=forbid): identidad de serie, counts auditables (`n_transitions_total/skipped/evaluated`, `n_events`), lista de eventos, configuración declarada, versioning ADR-0010.

### 5. Identificadores machine-readable

| Constante | Valor v0.1 |
|----------|-----------|
| `MANEUVER_DETECTION_SCHEMA_VERSION` | `0.1.0` |
| `MANEUVER_DETECTION_ENGINE_VERSION` | `0.1.0` |
| `DETECTION_METHOD_NAME` | `element_jump_z_score_v1` |
| `BASELINE_WINDOW_DAYS_DEFAULT` | `14.0` |
| `DETECTION_THRESHOLD_SIGMA_DEFAULT` | `3.0` |
| `MIN_BASELINE_SAMPLES_DEFAULT` | `5` |
| `SIGMA_FLOOR_DEFAULT` | `1e-12` |

### 6. CLI

```
orbital-sentinel maneuvers <norad_id>
    [--baseline-days N]                # default 14.0
    [--threshold-sigma S]              # default 3.0
    [--min-baseline-samples N]         # default 5
    [--engine-version X.Y.Z]
    [--raw-root PATH] [--normalized-root PATH]
```

Salida JSON. Mismo patrón que los 10 subcomandos previos.

## Justificación

### Per-rate, no per-delta crudo

TLEs no llegan a cadencia uniforme. Normalizar por `Δt` convierte la comparación en rate of change, físicamente significativo.

### Z-score sobre rates por componente

Las tres componentes tienen volatilidades muy distintas. Computar baseline per-componente y reportar el dominante hace el detector robusto sin hiperparámetros adicionales.

### `is_apparent_not_confirmed = True` siempre en v0.1

Honestidad declarada literal. Detectar un salto z > threshold no prueba que el operador del satélite hizo una maniobra. Causas alternativas:

- TLE de baja calidad (ajuste SGP4 pobre)
- Evento atmosférico (tormenta geomagnética en LEO bajo)
- Cambio de catálogo emisor (USSF reprocessing)
- Cambio de `engine_version` del normalizador en una porción de la serie
- Discontinuidad por TLE faltante

V0.1 reporta "saltos aparentes". El operador humano clasifica. Extensión natural de ADR-0020 al dominio estadístico: emitimos la señal con sus asunciones, no concluimos.

### Cero dependencias nuevas

Solo `statistics` stdlib. P3 preservado.

## Lo que este ADR NO decide

- **Detección sobre datos reales acumulados.** v0.1 funciona con cualquier serie (real o sintética). Hasta que la ingesta operacional acumule meses, los tests son sintéticos. El detector es operacionalmente útil el día que el catálogo lo sea; no antes. Declaración honesta vía `is_apparent_not_confirmed`.
- **Kalman filter / SGP4 propagation residuals.** ADR posterior si v0.1 demuestra insuficiente.
- **Clasificación de tipos de maniobra** (station-keeping vs orbit raise vs phasing vs deorbit). v0.1 solo dice "salto detectado en componente X".
- **Multi-NORAD scan de maniobras** (análogo a Observatory scan). Defer.
- **Persistencia de detecciones como tabla Derived.** Defer; on-demand cumple.
- **Confidence / probability / Bayesian posterior.** Explícitamente fuera. V0.1 emite z-score; el operador clasifica.

## Consecuencias

### Positivas

- Primera capacidad clasificatoria del proyecto.
- Cero dependencias nuevas.
- Establece el patrón para detectores estadísticos antes de Fase 4 (anomalías).
- `find_all_by_norad_id` es útil más allá de maniobras.

### Negativas

- Hasta que haya ingesta real acumulada, el detector se prueba solo con series sintéticas. ADR declarado.
- Nueva superficie pública (subcomando + módulo) que mantener.

### Neutras

- v0.1 deliberadamente no normaliza por `engine_version` por defecto. La mezcla produce señal extra que el operador puede separar via `--engine-version`. Honesty declarada en `is_apparent_not_confirmed`.

## Alternativas consideradas

### A. SGP4 propagation residuals desde v0.1
Rechazo: complejidad alta (doble propagación). V0.2 si v0.1 demuestra insuficiente.

### B. Kalman filter sobre elements
Rechazo: hiperparámetros adicionales (process noise, measurement noise) requerirían su propio ADR de honesty. V0.1 minimalista primero.

### C. Threshold absoluto en lugar de z-score
Rechazo: requiere conocer volatilidad típica por familia orbital (LEO ≠ MEO ≠ GEO). Z-score absorbe heterogeneidad.

### D. Persistir eventos como tabla Derived
Rechazo: YAGNI. On-demand cumple.

### E. Bayesian posterior de "is maneuver"
Rechazo: requiere prior, likelihood, asunciones que el proyecto no puede defender hoy. Honestidad → no lo emitimos.

## Alineación con ADR-0000

- **Refuerza P1, P4**: provenance FK binaria por evento; determinismo total con clock inyectable.
- **Refuerza P2**: 5 honesty fields + `is_apparent_not_confirmed=True` siempre en v0.1.
- **Refuerza P3**: `statistics` stdlib only.
- **Refuerza P7, P8**: catálogo existente, sin red.
- **Sin tensiones.**

## Referencias

- ADR-0006 (capas inmutables; multiple `engine_version` coexisten).
- ADR-0010 (versioning policy).
- ADR-0020 (patrón de honesty fields; este ADR es su extensión al dominio estadístico).
- Vallado, D. (2008). *Fundamentals of Astrodynamics.* §6 (TLE quality notes).
- Hejduk, M.D. (2011). *Satellite Conjunction Assessment Risk Analysis.* (Patrón z-score sobre residuals).

---

## Historial de enmiendas

*Sin enmiendas a fecha de aceptación.*
