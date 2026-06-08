# ADR-0029: Derived Evidence Layer v0.1

**Estado:** Aceptado
**Fecha:** 2026-06-06
**Autor:** Orbital Sentinel
**Supersede a:** ninguno
**Relacionado con:** ADR-0000 (P1, P2, P3, P7, P8), ADR-0002 enmienda 1, ADR-0006, ADR-0010, ADR-0020, ADR-0019, ADR-0027, ADR-0028

---

## Contexto

Los tres detectores existentes — conjunctions (ADR-0019), maneuvers (ADR-0027) y anomalies (ADR-0028) — emiten cada uno su propio modelo de output con su propio esquema. Para un operador que se preguntara *"¿qué evidencia tenemos sobre este objeto?"* no existía representación común.

Este ADR introduce una **capa derivada de consolidación**. No clasifica. No infiere causas. No asigna probabilidades. Solo proyecta los outputs de los detectores en un modelo común con honesty fields preservados, para que cualquier consumidor downstream tenga el contexto estadístico/físico necesario sin re-leer cada detector.

El sistema antes respondía *"¿Qué pasó?"*. Después de este ADR responde *"¿Qué evidencia tenemos de que algo inusual ocurrió?"* — sin intentar responder *"¿Qué significa?"*.

## Decisión

Crear `analytics/evidence/` con dos modelos públicos, tres builders y un catálogo consultable.

### 1. `DerivedEvidence` (modelo)

`frozen=True, extra="forbid"`. Campos:

```
evidence_id: str                  (SHA-256 content-addressable)
object_id: int                    (NORAD cat ID)
evidence_type: str                (maneuver_jump_detected | anomaly_observed
                                   | conjunction_detected)
source_detector: SourceDetector   (Literal restringido a v0.1)
detector_event_id: str            (identidad del evento dentro del detector)
event_epoch: datetime             (instante UTC del evento subyacente)
honesty_payload: dict             (campos críticos preservados del detector)
analysis_engine_version: str
schema_version: str               (= "0.1.0")
is_apparent_not_confirmed: bool   (= True en v0.1)
```

`SourceDetector` es `Literal["maneuver_detection_v01", "anomaly_detection_v01", "conjunction_detection_v01"]`. Cualquier identificador fuera de la lista produce error en construcción. Nuevos detectores requieren su propio ADR.

`evidence_id = SHA256("|".join([source_detector, str(object_id), detector_event_id, event_epoch.isoformat(), analysis_engine_version]))`. Determinístico y content-addressable.

### 2. `EvidenceCatalog` (contenedor)

Inmutable, sin persistencia. Constructor único `from_evidence(items, derived_at)` que:

1. De-duplica por `evidence_id` conservando la primera ocurrencia.
2. Ordena por `(event_epoch ascendente, evidence_id ascendente)`.

Filtros read-only:

- `list_all() → list[DerivedEvidence]`
- `list_by_norad(norad_cat_id) → list[DerivedEvidence]`
- `list_by_detector(source_detector) → list[DerivedEvidence]`
- `list_by_epoch_range(start, end) → list[DerivedEvidence]`

Cada filtro devuelve lista nueva; mutarla no afecta al catálogo.

### 3. Builders

Tres funciones puras, sin agregación entre sí:

```python
build_maneuver_evidence(result: ManeuverDetectionResult) -> list[DerivedEvidence]
build_anomaly_evidence(result: AnomalyDetectionResult) -> list[DerivedEvidence]
build_conjunction_evidence(
    detections: Iterable[ConjunctionDetection],
    *,
    only_for_norad: int | None = None,
) -> list[DerivedEvidence]
```

Conjunciones involucran dos NORADs: el builder emite un `DerivedEvidence` por lado (`side='a'` y `side='b'`); cuando `only_for_norad` se especifica, solo se emite el lado coincidente. El payload incluye `other_norad_cat_id` para preservar la trazabilidad de la otra parte.

### 4. Honesty payload preservado

Por cada detector, el payload conserva al mínimo:

| Origen | Campos preservados |
|--------|---------------------|
| Maneuver | `detection_method_name`, `baseline_window_days`, `detection_threshold_sigma`, `n_baseline_samples`, `dominant_component`, `delta_t_days`, `z_score_*` (3), tle hashes y content_hash_source de ambos lados |
| Anomaly | `detection_method_name`, `baseline_window_days`, `threshold_sigma`, `n_baseline_samples`, `feature_name`, `observed_value`, `baseline_mean`, `baseline_stddev`, `anomaly_score` |
| Conjunction | `miss_distance_km`, `pc`, `pc_method`, `covariance_model_name`, `covariance_*sigma*`, `sgp4_uncertainty_*`, `tca_resolution_minutes`, `tca_was_refined`, `combined_hard_body_radius_km`, `combined_sigma_at_tca_km`, `other_norad_cat_id`, `detection_content_hash`, `side` |

La capa de evidencia **no remueve** ni transforma estos campos.

### 5. Identificadores machine-readable

| Constante | Valor v0.1 |
|-----------|-----------|
| `EVIDENCE_LAYER_SCHEMA_VERSION` | `0.1.0` |
| `EVIDENCE_LAYER_ENGINE_VERSION` | `0.1.0` |
| `EVIDENCE_TYPE_MANEUVER` | `maneuver_jump_detected` |
| `EVIDENCE_TYPE_ANOMALY` | `anomaly_observed` |
| `EVIDENCE_TYPE_CONJUNCTION` | `conjunction_detected` |

### 6. CLI

```
orbital-sentinel evidence <norad_id>
    [--from ISO_UTC]
    [--to ISO_UTC]
    [--detector {maneuver|anomaly|conjunction}]
    [--baseline-days N] [--threshold-sigma S]
    [--min-baseline-samples N] [--engine-version X.Y.Z]
    [--raw-root PATH] [--normalized-root PATH]
    [--detections-root PATH]
```

Internamente: lee elementos para el NORAD, ejecuta maneuver + anomaly si la serie tiene ≥2 elementos; lee detecciones de conjunción del catálogo persistido si existe; consolida con `EvidenceCatalog.from_evidence`. Aplica filtros opcionales. Emite JSON únicamente.

## Lo que este ADR NO incluye

Prohibiciones explícitas heredadas del briefing:

- **No clasifica** anomalías ni conjuntions.
- **No infiere causas** ni explicaciones.
- **No asigna threat assessment, danger level ni risk score.**
- **No emite confidence percentages, probabilidades, recommendations.**
- **No hace ranking ni scoring** de evidencia.
- **No fusiona** evidencia entre detectores (no inventa "este maneuver + este anomaly = X").
- **No pondera** evidencia (no asigna pesos por detector ni por epoch).
- **No persiste** evidencia (sin tablas Derived nuevas).
- **No genera alertas** ni notificaciones.

El detector responde una pregunta nueva:

> "¿Qué evidencia existe respecto a este objeto?"

No intenta responder:

> "¿Qué significa esa evidencia?"

## Justificación

### Reutiliza el patrón ADR-0020 y ADR-0028

`is_apparent_not_confirmed=True` se hereda y se garantiza a nivel de capa. El honesty payload es contractual: la capa existe precisamente para que esos campos sobrevivan downstream.

### Determinismo total

`evidence_id` content-addressable. Catálogo ordenado por `(epoch, evidence_id)`. Sin RNG. Sin wall clock no inyectable (la única lectura del clock es en `derived_at` del catálogo, que solo describe cuándo se consolidó).

### Cero dependencias nuevas, cero persistencia

`hashlib` stdlib. Pydantic ya presente. Catálogo en memoria.

## Alineación con ADR-0000

- **Refuerza P1, P4**: `evidence_id` content-addressable + provenance preservado en payload + determinismo verificable.
- **Refuerza P2**: capa que **garantiza** que el honesty pattern sobrevive. Cero scoring, cero clasificación.
- **Refuerza P3**: stdlib only.
- **Refuerza P7, P8**: sin red, sin servicios externos.
- **Sin tensiones.**

## Referencias

- ADR-0010 (versioning policy).
- ADR-0020 (patrón de honesty fields).
- ADR-0019 (ConjunctionDetection persistido).
- ADR-0027 (ManeuverDetectionResult).
- ADR-0028 (AnomalyDetectionResult).

---

## Historial de enmiendas

*Sin enmiendas a fecha de aceptación.*
