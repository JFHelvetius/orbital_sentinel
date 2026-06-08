# Capas de datos: separación estricta de campos

**Audiencia:** contribuidores y autores de nuevas tablas en `catalog/`.
**Relacionado con:** ADR-0006 (inmutabilidad de capas), ADR-0010 (versioning), ADR-0013 (reproducibilidad).

## Principio rector

Cada capa tiene **un único propósito**. Duplicar campos provenientes de una capa "upstream" en una capa "downstream" — lo que llamamos **contaminación entre capas** — introduce riesgo de drift silencioso y rompe la propiedad de regenerabilidad declarada en ADR-0006.

Regla operacional: si un dato existe en una capa, **no se copia** a otra. Se recupera vía la relación de claves (`content_hash_source` u otra FK lógica).

---

## Raw — `tle_snapshots`

**Pregunta a la que responde:** *¿qué bytes recibimos, de dónde, y cuándo?*

| Campo            | Tipo       | Pertenece a Raw porque…                                       |
|------------------|------------|---------------------------------------------------------------|
| `content_hash`   | str (PK)   | Identidad bit-exacta del payload.                             |
| `source`         | str        | Pertenece al origen del payload.                              |
| `dataset`        | str        | Subgrupo dentro del origen.                                   |
| `url`            | str        | URL canónica desde la que se descargó.                        |
| `fetched_at`     | datetime   | Instante de la primera observación.                           |
| `raw_text`       | str        | Bytes recibidos, decodificados ASCII.                         |
| `n_bytes`        | int        | Tamaño; útil como sanity check.                               |
| `schema_version` | str (SemVer)| Versión del esquema **de esta tabla**.                       |

**Nunca pertenece a Raw:**

- Cualquier campo derivado de parsear los bytes (norad_cat_id, inclinación, etc.).
- Cualquier campo que requiera lógica de dominio (epoch derivado, propagación, detección).
- `engine_version`: Raw no es producto de un algoritmo; es la entrada al sistema. La versión del algoritmo de ingesta no tiene sentido aquí (la ingesta no transforma).

---

## Normalized — `orbital_elements`

**Pregunta a la que responde:** *¿qué hay dentro de esos bytes, parseado, validado y trazable?*

| Campo                    | Tipo           | Categoría        | Pertenece a Normalized porque…                                                  |
|--------------------------|----------------|------------------|---------------------------------------------------------------------------------|
| `content_hash_source`    | str            | Provenance       | FK lógica a `tle_snapshots.content_hash`.                                       |
| `tle_index`              | int            | Provenance       | Posición 0-based del TLE dentro del snapshot.                                   |
| `tle_content_hash`       | str            | TLE identity     | SHA-256 del TLE individual; permite dedup cross-snapshot.                       |
| `object_name`            | str ∣ None     | TLE identity     | Línea 0 si está presente (opcional por construcción).                           |
| `norad_cat_id`           | int            | Catalog identity | Identidad del objeto catalogado.                                                |
| `classification`         | str (U/C/S)    | Catalog identity | Marca de clasificación.                                                         |
| `intl_designator`        | str            | Catalog identity | Designador internacional.                                                       |
| `epoch_year`             | int            | Epoch            | Forma original TLE (año de la época).                                           |
| `epoch_day`              | float          | Epoch            | Forma original TLE (día del año + fracción).                                    |
| `epoch_datetime`         | datetime       | Epoch derivado   | Producido determinísticamente de `(epoch_year, epoch_day)`.                     |
| `mean_motion_dot`        | float          | Mean elements    | Primera derivada / 2.                                                           |
| `mean_motion_ddot`       | float          | Mean elements    | Segunda derivada / 6.                                                           |
| `bstar`                  | float          | Mean elements    | Drag BSTAR.                                                                     |
| `ephemeris_type`         | int            | Mean elements    | Típicamente 0.                                                                  |
| `element_set_number`     | int            | Mean elements    | Set number del catálogo emisor.                                                 |
| `inclination_deg`        | float          | Mean elements    | Inclinación.                                                                    |
| `raan_deg`               | float          | Mean elements    | RAAN.                                                                           |
| `eccentricity`           | float          | Mean elements    | Eccentricidad.                                                                  |
| `arg_perigee_deg`        | float          | Mean elements    | Argumento del perigeo.                                                          |
| `mean_anomaly_deg`       | float          | Mean elements    | Anomalía media.                                                                 |
| `mean_motion`            | float          | Mean elements    | Mean motion.                                                                    |
| `rev_number`             | int            | Mean elements    | Revolución en la época.                                                         |
| `schema_version`         | str (SemVer)   | Versioning       | Versión del esquema **de esta tabla** (independiente de Raw).                   |
| `engine_version`         | str (SemVer)   | Versioning       | Versión del normalizador que produjo la fila (ADR-0010).                        |
| `derived_at`             | datetime       | Versioning       | Instante operacional de la derivación.                                          |

**Nunca pertenece a Normalized:**

- `source`, `dataset`, `url`, `fetched_at`: viven en Raw. Se recuperan vía JOIN sobre `content_hash_source`. Duplicarlos crea drift si Raw se actualiza (no debería pasar por ADR-0006, pero el invariante es de defensa en profundidad).
- `raw_text`: redundante; el snapshot Raw lo conserva.
- Resultados de propagación, conjunciones, maniobras, anomalías: pertenecen a Derived.
- Cualquier dato producido por SGP4 o cualquier otra librería de física.

---

## Derived

**Pregunta a la que responde:** *¿qué inferencia hicimos sobre los elementos parseados?*

### Estado de implementación

- **Efemérides** (`Ephemeris`): implementado en v1 vía SGP4 (ADR-0014). **On-demand puro** por defecto (ADR-0006 enmienda 1); no se persiste en disco.
- **Conjunciones** (`ConjunctionAnalysis` on-demand + `ConjunctionDetection` persistido): implementado en Fase 2 cerrada (ADRs 0016-0021). Análisis pairwise + N-to-N screening + Pc con covarianza declarada. Persistencia content-addressable en `data/derived/conjunctions/` con integridad cross-layer (ADR-0019). **Primera tabla Derived persistente del proyecto.**
- **Maniobras y anomalías**: no implementado. Trabajo de fases 3-4 con sus propios ADRs.

### Modelo de datos: `Ephemeris`

| Campo | Tipo | Categoría | Pertenece a Derived porque… |
|-------|------|-----------|-------------------------------|
| `orbital_element_content_hash_source` | str | Provenance | FK lógica a `tle_snapshots.content_hash`. |
| `orbital_element_tle_index` | int | Provenance | Posición del TLE en el snapshot. |
| `tle_content_hash` | str | Provenance | Identidad canónica del TLE individual. |
| `norad_cat_id` | int | Identity (denormalizada) | Queries hot-path filtran por NORAD; excepción justificada a la regla de no-contaminación. |
| `evaluation_time` | datetime UTC | Evaluation | Instante al que se evaluó la propagación. |
| `minutes_from_epoch` | float | Evaluation derived | Offset signed desde el epoch del TLE. |
| `position_teme_*_km` (×3) | float | State vector | Componentes TEME de posición [km]. |
| `velocity_teme_*_km_s` (×3) | float | State vector | Componentes TEME de velocidad [km/s]. |
| `sgp4_error_code` | int | Quality | Código de SGP4; 0 = OK. Preservado sin filtrar (ADR-0000 P2). |
| `schema_version` | str | Versioning | SemVer del esquema de Ephemeris. |
| `engine_version` | str | Versioning | SemVer del wrapper SGP4 (ADR-0010). |
| `derived_at` | datetime UTC | Versioning | Instante de la derivación. |

**Marco de referencia: TEME** (nativo SGP4). Conversiones a ECI/ECEF/ITRF son trabajo de un módulo futuro.

### Nunca pertenecerá a Derived

- Elementos orbitales completos parseados (vienen vía JOIN sobre `tle_content_hash` o `orbital_element_tle_index` → `orbital_elements`).
- `source`, `dataset`, `url`, `fetched_at` (vienen vía JOIN doble Derived → Normalized → Raw).
- `raw_text` (vive solo en Raw).
- Inferencias que requieran modelos LLM (esos no son fuente de verdad, ADR-0009 enmienda 1).

### Materialización: política on-demand

`Sgp4Propagator.propagate()` devuelve `list[Ephemeris]` en memoria. **No persiste**. Coherente con ADR-0006 enmienda 1 (las efemérides no se materializan por defecto). Si en el futuro se introduce caché de ventana corta, será módulo aparte (`propagation/cache.py`) con TTL declarado y fuera del régimen de inmutabilidad de Derived.

---

## Relación entre capas

```
tle_snapshots.content_hash
     │
     │ FK lógica
     ▼
orbital_elements.content_hash_source
     │
     │ FK lógica futura
     ▼
(futuras tablas Derived).source_*_hash
```

Trazabilidad siempre **hacia atrás**: cualquier fila Derived → la Normalized que la originó → el Raw del que se parseó. Ninguna fila "huye" de su procedencia.

---

## Versionado independiente por capa (ADR-0010)

Cada capa tiene su propio `schema_version`. **Los SemVer no están sincronizados entre capas**:

- Cambiar el esquema de Normalized **no obliga** a bump de Raw.
- Cambiar el esquema de Raw **no obliga** a bump de Normalized.
- Las capas son independientes para que un fix en una no inunde el resto.

Además, las capas derivadas llevan `engine_version` para identificar la versión del algoritmo. ADR-0006 admite la coexistencia de múltiples `engine_version` sobre la misma `content_hash_source`: el almacenamiento parquet usa `engine_version=` como partición física para que esa coexistencia sea trivial de gestionar.

---

## Tabla resumen visual

| Campo                  | Raw | Normalized | Derived (futuro) |
|------------------------|:---:|:----------:|:----------------:|
| `content_hash` (PK)    | ✓   |            |                  |
| `source` / `dataset` / `url` | ✓ | ✗ (vía JOIN) | ✗ (vía JOIN→JOIN) |
| `fetched_at`           | ✓   | ✗          | ✗                |
| `raw_text`             | ✓   | ✗          | ✗                |
| `content_hash_source`  |     | ✓ (FK)     | ✓ (FK)           |
| `tle_index`            |     | ✓          |                  |
| `tle_content_hash`     |     | ✓          |                  |
| `norad_cat_id`         |     | ✓          | (denormalizado OK)|
| Campos orbitales       |     | ✓          | ✗ (vía JOIN)     |
| `epoch_datetime`       |     | ✓ derivado |                  |
| `engine_version`       |     | ✓          | ✓                |
| `derived_at`           |     | ✓          | ✓                |
| `schema_version`       | ✓   | ✓ (otro)   | ✓ (otro)         |

**Leyenda:** ✓ presente · ✗ contaminación (prohibido) · (vía JOIN) recuperable sin duplicar · (denormalizado OK) duplicación permitida con justificación explícita en ADR.

---

## Cómo añadir una capa nueva

1. Decidir su pregunta: *¿qué pregunta responde esta capa que ninguna otra responde?* Si la respuesta es vaga, la capa no debe existir.
2. Definir su identidad (PK).
3. Definir su FK lógica hacia atrás.
4. Listar sus campos en una tabla como las anteriores, con la columna *"pertenece a esta capa porque…"*.
5. Listar explícitamente qué **no** pertenece.
6. Abrir un ADR específico si la decisión afecta a contratos públicos (esquemas Parquet, columnas estables).
