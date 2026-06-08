# ADR-0019: Persistencia de detecciones de conjunción — Pairwise v0.4

**Estado:** Aceptado
**Fecha:** 2026-06-06
**Autor:** Orbital Sentinel
**Supersede a:** ninguno
**Relacionado con:** ADR-0006 (capas + enmienda 1), ADR-0010 (versioning), ADR-0016-18 (pairwise v0.1-v0.3)

---

## Contexto

Hasta este ADR, **todos los productos Derived** del proyecto han sido on-demand:

- `Ephemeris` (ADR-0014 + ADR-0006 enmienda 1) explícitamente **no se materializa** por consideraciones físicas (catalog completo ~8 TB en 5 años, F5 del red-team review).
- `ConjunctionAnalysis` (ADR-0016/17/18) vive en memoria y se descarta al final del run.

v0.4 introduce **la primera tabla Derived persistente del proyecto**: detecciones de conjunción producidas por screening. Es un salto arquitectónico real — el primer artefacto Derived materializado en Parquet.

## Decisión

### Por qué SÍ persistir detecciones (cuando ADR-0006 enmienda 1 prohíbe Ephemeris)

Las propiedades son **fundamentalmente distintas**:

| Propiedad | Ephemeris (NO persistido) | ConjunctionDetection (SÍ persistido) |
|---|---|---|
| **Densidad** | Millones/día por catálogo | Decenas/mes |
| **Tamaño catálogo completo** | ~8 TB / 5 años | ~MB / 5 años |
| **Naturaleza** | Estado continuo | Evento discreto |
| **Pérdida si no se persiste** | Recomputable (función pura) | Pierde auditabilidad histórica |
| **Coste de regenerar** | Trivial (call SGP4) | Caro (re-screen todo el catálogo en la ventana correcta) |

Persistir detecciones alinea con la lógica original de ADR-0006: materializar lo escaso, importante y económico.

### Modelo: `ConjunctionDetection`

Pydantic frozen, **flat schema** (no nested) para queries DuckDB directas. Es una `ConjunctionAnalysis` materializada con metadata de persistencia añadida:

```
detection_content_hash      ← PK content-addressable

(todos los campos de ConjunctionAnalysis copiados flat)
norad_a, norad_b
element_a_content_hash_source, element_a_tle_index, element_a_tle_content_hash
element_b_content_hash_source, element_b_tle_index, element_b_tle_content_hash
window_start, window_end, step_minutes, n_samples
tca, miss_distance_km, relative_velocity_km_s
minutes_from_epoch_a_at_tca, minutes_from_epoch_b_at_tca
sgp4_uncertainty_baseline_km, sgp4_uncertainty_growth_km_per_day
tca_resolution_minutes, tca_was_refined

analysis_schema_version     ← version metadata del análisis original
analysis_engine_version
analysis_derived_at

persistence_schema_version  ← version metadata de la persistencia
persisted_at
```

Tres versiones distintas en una sola fila: `analysis_schema_version`, `analysis_engine_version`, `persistence_schema_version`. Versionado independiente entre modelos (ADR-0010) ejercitado en producción.

### Identidad: SHA-256 content-addressable

```python
def compute_detection_hash(analysis):
    pair = sorted([analysis.element_a_tle_content_hash,
                   analysis.element_b_tle_content_hash])
    canonical = "|".join([
        pair[0], pair[1],
        analysis.window_start.isoformat(),
        analysis.window_end.isoformat(),
        f"{analysis.step_minutes:.6f}",
        analysis.engine_version,
    ])
    return sha256(canonical.encode("ascii")).hexdigest()
```

Propiedades:
- **Determinístico**: misma entrada → mismo hash.
- **Canónico**: `sorted(tle_hashes)` hace que `(A,B)` y `(B,A)` produzcan el mismo hash. Una conjunción es una conjunción independientemente del orden de los dos objetos.
- **NO incluye `derived_at`** (wall-clock no es parte de la identidad).
- **NO incluye outputs** (`miss`, `tca`, `relative_velocity`) — son derivados de los inputs.
- **Incluye `engine_version`**: detecciones de v0.2 y v0.3 (cuando exista) son rows distintas en la misma tabla.

### Storage: Parquet/DuckDB content-addressable

Mismo patrón que `tle_snapshots`:

```
data/derived/conjunctions/
└── year=YYYY/month=MM/
    └── det_<detection_content_hash>.parquet  (1 fila por archivo)
```

Particionado por `persisted_at`. Idempotente por construcción: archivo existe → no-op. ADR-0006 "sin UPDATE" se respeta.

### Verificación de integridad cross-layer

`verify_detections_integrity(snapshots, detections) → DetectionsIntegrityReport`.

Para cada detection, comprueba que `element_a_content_hash_source` y `element_b_content_hash_source` existen en `tle_snapshots`. Si no, `DetectionOrphan`.

**Por qué NO comprueba referencia a `orbital_elements`**:
- La cadena llega al Raw via `content_hash_source` directamente.
- Normalized es **regenerable** desde Raw (ADR-0006).
- Verificar Raw es suficiente para la trazabilidad real.

### CLI

`orbital-sentinel screen ... --persist [--detections-root PATH]`

Flag opcional. Cuando se especifica, escribe todas las detecciones del run al repositorio. La respuesta JSON incluye `n_persisted` (cuántas se escribieron realmente, contando idempotencia).

`orbital-sentinel detections [--norad N] [--limit N] [--detections-root PATH]`

Lista detecciones persistidas. `--norad` filtra por NORAD ID (cualquier lado, A o B). `--limit` por defecto 100.

### Exclusiones v0.4 explícitas

- **No persistencia de Ephemeris**. Sigue on-demand (ADR-0006 enmienda 1).
- **No persistencia automática**. El caller declara `--persist` cada vez.
- **No retention/compaction**. Append-only puro. Compactación es operacional futura.
- **No exportación CSV/JSON**. Parquet es el formato; consulta vía CLI.
- **No dedup cross-window**. Dos screenings con ventanas distintas que encuentran "el mismo evento físico" persisten **ambos** (son análisis distintos). El usuario que quiera dedup geográfico lo hace con queries.
- **No Pc**. Sigue diferido a v1.0 con ADR de covarianzas.

### Versionado

| Constante | Valor | Significado |
|---|---|---|
| `PERSISTED_CONJUNCTION_SCHEMA_VERSION` | `0.1.0` | Primera versión del esquema persistido |

Cada row almacena tres versiones independientes:
- `persistence_schema_version` = `"0.1.0"` (este esquema)
- `analysis_schema_version` = `"0.2.0"` (ConjunctionAnalysis actual, ADR-0017)
- `analysis_engine_version` = `"0.2.0"` (pairwise engine actual)

Cuando pairwise bumpe a v1.0 (Pc añadido), nuevas detecciones tendrán `analysis_engine_version = "1.0.0"`. Las viejas con `"0.2.0"` permanecen. Ambos versionados coexisten — patrón ADR-0010.

### Criterios de aceptación v0.4

1. ADR-0019 aceptado.
2. `ConjunctionDetection` Pydantic frozen con todos los campos.
3. `compute_detection_hash` con canonical ordering (sorted tle_hashes).
4. `ConjunctionDetectionsRepository` Parquet/DuckDB con insert/get/iter/find_by_norad.
5. `verify_detections_integrity()` detecta orphans.
6. CLI: `--persist` en `screen`, comando `detections`.
7. Tests verificables:
   - Insert idempotente por content_hash.
   - Hash canónico: `(A,B)` y `(B,A)` mismo hash.
   - `find_by_norad` busca en ambos lados.
   - `verify` detecta orphan cuando snapshot borrado manualmente.
   - Round-trip preserva todos los campos.
   - CLI end-to-end con persist + listing.
8. 243 tests previos siguen verdes.

## Justificación

- **Content-addressable identity** es coherente con el patrón ya usado en `tle_snapshots`. Idempotencia gratis.
- **Flat schema** es feo pero fácil de query y mantener. Nested Parquet sería elegante pero introduce complejidad de PyArrow structs sin ganar nada operacionalmente para v0.4.
- **Canonical ordering** `sorted(tle_hashes)` evita duplicación lógica de eventos. Un par de objetos puede tener "una conjunción" en una ventana; el orden no cambia eso.
- **`--persist` opcional explícito** mantiene el patrón de "el caller decide qué materializar". No imponemos persistencia.
- **Verificación cross-layer separada** (`verify_detections_integrity` ≠ `verify_integrity`) mantiene cada función con scope acotado.

## Consecuencias

**Positivas**
- Primer Derived persistente. Patrón establecido para futuras tablas (maniobras, anomalías).
- Auditabilidad histórica de detecciones.
- Idempotencia por construcción.
- Tres versionados independientes ejercitados (analysis_schema, analysis_engine, persistence_schema).

**Negativas**
- Una nueva tabla más que mantener, migrar y backupear.
- Si pairwise bumpa schema MAJOR, la persistencia necesita su propio bump (mitigado por versioning explícito).

**Neutras**
- Retention futuro es decisión separada (ADR posterior).
- Compactación de archivos pequeños futura es operacional.

## Alternativas consideradas

### A. Nested Pydantic + Parquet struct
**Razón de rechazo:** elegante en código, complejo en PyArrow + DuckDB queries. Para v0.4 minimum, flat es predecible.

### B. Persistencia automática (siempre)
**Razón de rechazo:** sobrescribe la decisión del caller. `--persist` explícito mantiene el control.

### C. Hash incluyendo `derived_at`
**Razón de rechazo:** rompería idempotencia (cada run produce hash distinto aunque inputs sean iguales).

### D. Hash sin `engine_version`
**Razón de rechazo:** dos analyses con motores distintos (v0.2 vs hipotético v1.0) producen detecciones potencialmente distintas; merecen rows distintas.

### E. Sin canonical ordering (preservar `(A,B)` vs `(B,A)`)
**Razón de rechazo:** duplica lógicamente el mismo evento físico. Idempotencia rota.

### F. Almacenar también `ScreeningResult` completo (no solo detecciones)
**Razón de rechazo:** counts auditable se reconstruye queryeando detecciones por window+engine. No necesario duplicar el contexto del run.

## Alineación con ADR-0000

- **Refuerza P1, P4**: trazabilidad y reproducibilidad por content_hash.
- **Refuerza P2**: persistimos los campos de incertidumbre declarada (uncertainty_baseline, etc.) junto a cada detección.
- **Compatible con P3, P8**: Parquet local, sin red, sin coste recurrente.
- **Sin tensiones.**

## Referencias

- ADR-0006 enmienda 1 (efemérides no materializadas).
- ADR-0010 §"Reglas de versionado por columna".
- ADR-0018 (screening que produce las detecciones).

---

## Historial de enmiendas

*Sin enmiendas a fecha de aceptación.*
