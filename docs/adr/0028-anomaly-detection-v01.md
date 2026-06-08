# ADR-0028: Anomaly detection v0.1 (observacional)

**Estado:** Aceptado
**Fecha:** 2026-06-06
**Autor:** Orbital Sentinel
**Supersede a:** ninguno
**Relacionado con:** ADR-0000 (P1, P2, P3, P7, P8), ADR-0002 enmienda 1, ADR-0006, ADR-0010, ADR-0020, ADR-0027

---

## Contexto

ADR-0027 entregó el primer detector estadístico del proyecto (maniobras: z-score sobre rates de cambio entre TLEs consecutivos). El roadmap de ADR-0000 §"Hoja de ruta" Fase 4 reclama "*Sistema de anomalías: features sobre series temporales y modelos por familia orbital*".

Este ADR introduce el **primer detector observacional general**. La diferencia con ADR-0027 es la naturaleza de la señal:

| Detector | Señal | Pregunta que responde |
|----------|-------|------------------------|
| ADR-0027 (maniobras) | rate of change entre TLEs consecutivos | "¿Esta transición es un salto anómalo?" |
| ADR-0028 (anomalías) | valor absoluto del feature en cada TLE | "¿Este valor está lejos de su propia historia reciente?" |

Son señales **independientes**. Una caída suave de altitud por drag atmosférico no dispara maniobras (rate estable) pero sí dispara anomalías (valor cada vez más lejos de la baseline). Una maniobra instantánea dispara ambas.

## Decisión

Crear `analytics/anomalies/` con cuatro componentes:

### 1. Features v0.1

Cuatro features derivadas exclusivamente del `OrbitalElement` ya presente en el catálogo Normalized (cero nuevas fuentes de datos):

| Feature | Cómputo |
|---------|---------|
| `altitude_km` | Kepler 3rd law: `a = (GM/n²)^(1/3)`, `alt = a − R⊕` |
| `eccentricity` | directo |
| `inclination_deg` | directo |
| `mean_motion` | directo [rev/día] |

Tupla canónica inmutable expuesta como `AVAILABLE_FEATURES`. Una feature nueva v0.2 (hipotética `maneuver_frequency_count`, `conjunction_frequency_count`) **requiere su propio ADR** porque introduce dependencia cross-domain con repositorios distintos.

### 2. Algoritmo

Mismo z-score que ADR-0027 pero sobre valores absolutos, no rates:

Para cada elemento `k` de la serie y cada feature `f`:

1. Baseline `B_k`: elementos `j < k` con `epoch_j > (epoch_k − baseline_window_days)`.
2. Si `|B_k| < min_baseline_samples` → skip (cuenta en `total_evaluations_skipped_insufficient_baseline`).
3. Si no:
   - `values = [feature_value(elements[j], f) for j in B_k]`
   - `μ = mean(values)`, `σ = stdev(values)`
   - `σ_safe = max(σ, σ_floor)`
   - `z = (feature_value(elements[k], f) − μ) / σ_safe`
4. Si `|z| > threshold_sigma` → emit `AnomalyEvent`.

Eventos ordenados por `(epoch_datetime, feature_name)` para determinismo bit-exacto.

### 3. Modelo `AnomalyEvent`

Pydantic `frozen=True, extra="forbid"`. Campos:

```
object_id                   (object_name si presente, sino NORAD-<id>)
norad_cat_id
epoch_datetime
feature_name
observed_value
baseline_mean
baseline_stddev
anomaly_score               (z-score signed)
detection_method_name       = "self_baseline_z_score_v1"
baseline_window_days
threshold_sigma
n_baseline_samples
is_apparent_not_confirmed   = True (siempre v0.1)
analysis_engine_version     = "0.1.0"
```

### 4. Modelo `AnomalyDetectionResult`

```
norad_cat_id
object_id
series_start_epoch / series_end_epoch
total_objects_analyzed                              (=1 en v0.1 CLI single-NORAD)
total_anomalies_found
total_evaluations
total_evaluations_skipped_insufficient_baseline
configuration_used: AnomalyDetectionConfig          (features_used, baseline_window_days,
                                                     threshold_sigma, min_baseline_samples,
                                                     sigma_floor, detection_method_name)
events: list[AnomalyEvent]
is_apparent_not_confirmed = True
schema_version = "0.1.0"
analysis_engine_version = "0.1.0"
derived_at
```

### 5. Identificadores

| Constante | Valor v0.1 |
|-----------|-----------|
| `ANOMALY_DETECTION_SCHEMA_VERSION` | `0.1.0` |
| `ANOMALY_DETECTION_ENGINE_VERSION` | `0.1.0` |
| `DETECTION_METHOD_NAME` | `self_baseline_z_score_v1` |
| `BASELINE_WINDOW_DAYS_DEFAULT` | `14.0` |
| `THRESHOLD_SIGMA_DEFAULT` | `3.0` |
| `MIN_BASELINE_SAMPLES_DEFAULT` | `5` |
| `SIGMA_FLOOR_DEFAULT` | `1e-12` |

### 6. CLI

```
orbital-sentinel anomalies <norad_id>
    [--baseline-days N]               # default 14.0
    [--threshold-sigma S]             # default 3.0
    [--min-baseline-samples N]        # default 5
    [--engine-version X.Y.Z]
    [--raw-root PATH] [--normalized-root PATH]
```

Salida **machine-readable únicamente** (JSON). Sin colores, sin texto narrativo, sin alertas, sin niveles de criticidad.

## Lo que este ADR NO incluye

Prohibiciones explícitas heredadas del briefing:

- **Sin ML**, sin clustering, sin redes neuronales, sin forecasting.
- **Sin clasificación**, sin causal inference, sin root-cause analysis.
- **Sin alertas**, sin dashboards, sin notificaciones.
- **Sin confidence percentages**, sin probability estimates, sin risk scores, sin threat scores.
- **Sin persistencia** de anomalías, sin tablas Derived nuevas.
- **Sin lenguaje interpretativo**: el output nunca contiene "likely", "probably", "suspicious", "dangerous", "malicious", "threat", "intent", "operator action".
- **Sin features cross-domain** (maneuver_frequency, conjunction_frequency) — requieren ADR-0029 si se justifica.
- **Sin multi-NORAD scan** (`total_objects_analyzed=1` en v0.1).
- **Sin SGP4 residuals**, sin RNG, sin wall clock no inyectable.

El detector responde una sola pregunta:

> "¿Qué features del objeto se desvían significativamente de su propia historia reciente?"

El operador humano asigna significado. La máquina no.

## Justificación

### Reutiliza ADR-0027 exactamente

Mismo patrón: `signal → baseline → deviation score → apparent observation → operator interpretation`. Mismo `is_apparent_not_confirmed=True`. Mismo z-score con σ_floor. Mismas validaciones (`min_baseline_samples ≥ 2`, `baseline_window_days > 0`, etc.).

La distinción está solo en la naturaleza del signal (valor vs rate), no en la arquitectura. Mantener el patrón estable refuerza ADR-0020 y reduce coste cognitivo en Fase 4+.

### Cero dependencias nuevas

`statistics` stdlib only. P3 preservado.

### Determinismo total

Sin RNG. Sin wall clock no inyectable. Eventos ordenados por `(epoch, feature_name)`. Salida bit-exacta para mismo input + mismo clock.

## Alineación con ADR-0000

- **Refuerza P1, P4**: cada `AnomalyEvent` lleva `epoch_datetime` y `analysis_engine_version` exactos; determinismo verificable.
- **Refuerza P2**: 5 honesty fields + `is_apparent_not_confirmed=True` + `analysis_engine_version` declarado. El número anomaly_score nunca viaja solo.
- **Refuerza P3**: stdlib only.
- **Refuerza P7, P8**: catálogo Normalized existente, sin red.
- **Sin tensiones.**

## Referencias

- ADR-0010 (versioning policy).
- ADR-0020 (patrón de honesty fields).
- ADR-0027 (maniobras: patrón estadístico que este ADR reutiliza).

---

## Historial de enmiendas

*Sin enmiendas a fecha de aceptación.*
