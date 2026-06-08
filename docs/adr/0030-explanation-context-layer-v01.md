# ADR-0030: Explanation Context Layer v0.1

**Estado:** Aceptado
**Fecha:** 2026-06-06
**Autor:** Orbital Sentinel
**Supersede a:** ninguno
**Relacionado con:** ADR-0000 (P1, P2, P3, P7, P8), ADR-0002 enmienda 1, ADR-0006, ADR-0010, ADR-0020, ADR-0027, ADR-0028, ADR-0029

---

## Contexto

ADR-0029 introdujo el `EvidenceCatalog`: un contenedor inmutable de `DerivedEvidence`. Responde *"¿qué evidencia tenemos?"* en forma lineal. Cualquier consumidor estructurado (LLM downstream, API, dashboard, exportador, reporte) requiere una vista con agregaciones, referencias cruzadas y hashes de integridad por payload. Si cada consumidor lo computa por su cuenta, surgen N implementaciones divergentes con probabilidad alta de drift.

Este ADR introduce una **capa intermedia, observacional, pura**, que proyecta un `EvidenceCatalog` filtrado al objeto en un `ExplanationContext` estructurado. La capa **no explica**, **no interpreta**, **no clasifica**, **no asigna probabilidades**. Es la última capa determinista y libre de IA antes del agente explicativo (Fase 5).

| Capa | Pregunta que responde |
|------|------------------------|
| Evidence Layer (ADR-0029) | "¿Qué evidencia detectable existe?" |
| **Context Layer (ADR-0030)** | **"¿En qué forma estructurada está esa evidencia, lista para consumo?"** |
| Agente Explicativo (Fase 5, futuro) | "¿Qué significa esa evidencia?" |

## Decisión

Crear `analytics/explanation/` con cinco modelos públicos, dos helpers de hash, un builder y un subcomando CLI.

### Modelos

#### `ExplanationContext` (root)

Vista consolidada para un objeto. Campos: `object_id`, `context_id` (SHA-256 content-addressable), `source_catalog_signature` (SHA-256 sobre evidence_ids ordenados), `n_evidence_total`, `coverage_window_start/end`, `coverage_duration_seconds`, `evidence_type_counts` (dict alfabético), `detector_summaries` (lista con los 3 detectores canónicos siempre presentes), `timeline`, `evidence_references`, `schema_version`, `explanation_engine_version`, `derived_at`.

#### `ExplanationEvidenceReference`

Puntero ligero a un `DerivedEvidence`. No duplica el `honesty_payload`; preserva su hash (`honesty_payload_hash`) para verificación de integridad downstream.

#### `ExplanationDetectorSummary`

Resumen por detector: `source_detector`, `n_events`, `first/last_event_epoch`, `evidence_ids`, `evidence_type_breakdown`.

Siempre se emite una entrada por cada detector de `CANONICAL_DETECTORS_V01`, aunque `n_events = 0`. Shape predecible.

#### `ExplanationTimeline` y `ExplanationTimelineEntry`

Secuencia temporal consolidada ordenada `(epoch asc, evidence_id asc)`.

### Helpers deterministas

```python
compute_payload_hash(payload: dict) -> str       # SHA-256 sobre JSON canónico (sort_keys=True)
compute_source_catalog_signature(evidence_ids) -> str  # SHA-256 sobre IDs ordenados
compute_context_id(object_id, explanation_engine_version, source_catalog_signature) -> str
```

### Builder

```python
def build_explanation_context(
    catalog: EvidenceCatalog,
    *,
    object_id: int,
    clock: Callable[[], datetime] | None = None,
) -> ExplanationContext
```

Función pura. El `clock` solo se usa para `derived_at` (metadata); `context_id` y `source_catalog_signature` son content-addressable y no dependen del instante de construcción.

### Identificadores machine-readable

| Constante | Valor v0.1 |
|----------|-----------|
| `EXPLANATION_LAYER_SCHEMA_VERSION` | `0.1.0` |
| `EXPLANATION_LAYER_ENGINE_VERSION` | `0.1.0` |
| `CANONICAL_DETECTORS_V01` | tupla alfabética de los 3 detectores autorizados |
| `EVIDENCE_TYPES_V01` | tupla alfabética de los 3 evidence_types autorizados |

### CLI

```
orbital-sentinel context <norad_id>
    [--from ISO_UTC] [--to ISO_UTC]
    [--detector {maneuver|anomaly|conjunction}]
    [--baseline-days N] [--threshold-sigma S]
    [--min-baseline-samples N] [--engine-version X.Y.Z]
    [--raw-root PATH] [--normalized-root PATH]
    [--detections-root PATH]
```

Construye el mismo `EvidenceCatalog` que `orbital-sentinel evidence`, aplica filtros opcionales sobre la evidencia antes de invocar al builder. Emite JSON únicamente.

## Lo que este ADR NO incluye

Prohibiciones contractuales:

- **No interpreta** ni explica el significado de la evidencia.
- **No clasifica** anomalías ni conjunciones.
- **No infiere causas** ni atribuciones.
- **No usa** ML, IA, NN, clustering, forecasting, Bayesian inference.
- **No emite** scoring, ranking, ordenamiento por importancia, confidence percentage, probability, threat level, danger level, recommendation, alerta.
- **No persiste** estado.
- **No modifica** detectores, repositorios, ingest, propagación, analytics existentes, `DerivedEvidence` ni `EvidenceCatalog`.
- **No introduce** dependencias nuevas (`hashlib`, `json` stdlib).
- **No usa** red, servicios externos, bases de datos.
- **No emite** narrativa, lenguaje interpretativo ni textos generados.
- **No fusiona** evidencia entre detectores.
- **No genera** nuevos `evidence_id`.

## Justificación

### Por qué una capa separada y no extender EvidenceCatalog

ADR-0029 deliberadamente mantiene `EvidenceCatalog` como contenedor mínimo + filtros. Añadir agregaciones lo infla hacia "contenedor + vista". La separación preserva un principio útil: cada modelo responde una pregunta, no diez.

### Por qué `honesty_payload_hash` y no copia del payload

Copiar el payload duplicaría datos y permitiría drift silencioso entre contexto y evidencia. El hash es contractual: cualquier consumidor verifica integridad sin duplicación. ADR-0020 reforzado.

### Por qué tres detectores siempre presentes

Shape predecible para consumidores. Un LLM o un dashboard puede asumir que existirán siempre las tres entradas; si una tiene `n_events = 0`, es información negativa válida ("este detector no produjo nada"), no ausencia ambigua.

## Alineación con ADR-0000

- **Refuerza P1, P4**: `context_id` content-addressable, hashes por payload, timeline determinista, round-trip Pydantic verificable.
- **Refuerza P2**: cero interpretación; honesty preservado por referencia + hash.
- **Refuerza P3**: stdlib only.
- **Refuerza P7, P8**: sin red, sin servicios.
- **Sin tensiones.**

## Referencias

- ADR-0006 (inmutabilidad / on-demand).
- ADR-0010 (versioning policy).
- ADR-0020 (honesty pattern).
- ADR-0029 (Evidence Layer — input de este ADR).

---

## Historial de enmiendas

*Sin enmiendas a fecha de aceptación.*
