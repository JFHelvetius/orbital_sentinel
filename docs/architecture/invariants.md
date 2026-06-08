# Invariantes verificados entre Raw y Normalized

**Audiencia:** contribuidores que toquen `tle_snapshots`, `orbital_elements`, el normalizador o el pipeline.
**Alcance:** invariantes verificables programáticamente sobre el contenido de ambas tablas.
**Relacionado con:** ADR-0006 (inmutabilidad), ADR-0010 (versioning), `docs/architecture/layers.md`.

## Filosofía

Estos invariantes son los que el pipeline normal mantiene **por construcción**. La función `verify_integrity()` los comprueba post-hoc para detectar:

- Corrupción manual (archivos borrados o movidos fuera del repo).
- Inserciones ad-hoc en Normalized sin pasar por el normalizador.
- Bugs futuros en migraciones, fixes del normalizador o cambios de esquema que rompan la trazabilidad.

Cualquier violación es un bug **operacional** o **de software**, nunca un estado esperado.

---

## I1 · Integridad referencial Normalized → Raw

**Enunciado:** para toda fila en `orbital_elements`, debe existir una fila en `tle_snapshots` con `content_hash` igual al `content_hash_source` de la Normalized.

**Por qué importa:** ADR-0006 declara la regenerabilidad de Normalized desde Raw. Si una fila Normalized apunta a un Raw inexistente, la regeneración es imposible y la trazabilidad queda rota.

**Cómo se viola en la práctica:**

- Corrupción manual: borrar archivos de Raw después de haber persistido Normalized.
- Migración mal escrita que mueve Raw sin actualizar Normalized.
- Inserción ad-hoc en Normalized desde un script externo sin pasar por el pipeline.

**Cómo se reporta:** `IntegrityReport.orphan_elements: list[OrphanElement]` con `content_hash_source`, `tle_index`, `engine_version` de cada fila huérfana.

---

## I2 · Continuidad de `tle_index` por grupo

**Enunciado:** para cada grupo `(content_hash_source, engine_version)` con N filas, el conjunto de valores `tle_index` debe ser exactamente `{0, 1, …, N-1}`.

**Por qué importa:** el normalizador asigna `tle_index` secuencialmente al iterar los bloques TLE del snapshot. Si hay saltos, duplicados o índices fuera de rango, algo ha insertado filas sin pasar por el normalizador, o se ha perdido alguna fila durante una operación.

**Cómo se viola:**

- Inserción ad-hoc con índices arbitrarios.
- Bug en `iter_tle_blocks` que se salta bloques (no debería ocurrir; está cubierto por tests).
- Batch fragmentado por error (por ejemplo, intentar dos `insert_many` con la misma `(engine_version, content_hash_source)` esperando que se acumulen — el segundo es no-op por idempotencia).

**Cómo se reporta:** `IntegrityReport.index_gaps: list[IndexGap]` con `content_hash_source`, `engine_version`, `expected_size` y `missing_indices`.

---

## Estado observable que NO es violación

### Raw sin Normalized correspondiente

Un snapshot Raw puede existir sin que se haya normalizado todavía. Es operacionalmente válido: la ingesta puede preceder a la normalización (batches retrasados, retroceder en el tiempo para procesar histórico).

**Reportado como:** `IntegrityReport.unnormalized_snapshots: list[str]`. Informativo, no error. `has_violations` ignora este campo.

**Cuándo preocuparse:** si un snapshot lleva mucho tiempo sin normalizar y debería estarlo. Es una decisión operacional, no de invariante.

---

## Invariantes que esta validación NO comprueba (todavía)

- **Equivalencia de re-derivación.** No reejecuta el normalizador para verificar que el output actual coincide con el almacenado. Sería caro pero potente; se podría añadir como `verify_integrity(..., reverify_derivation=True)` cuando se justifique con un incidente real.
- **Consistencia de `schema_version` dentro de un `engine_version`.** Caso edge: filas producidas por la misma versión de motor con distintas versiones de esquema. Posible pero requiere bug específico de migración.
- **Integridad de los bytes de Raw.** El `content_hash` almacenado se asume correcto; no se re-hashea el `raw_text` al cargar. Defensa adicional opcional.
- **Equivalencia entre `engine_version`s.** Si dos versiones del normalizador producen rows distintas para el mismo Raw, ambas son válidas (coexistencia ADR-0010). No es una violación.

La política: **añadir checks cuando se encuentre un bug real**, no preventivamente. Los checks tienen su propio coste de mantenimiento.

---

## Cómo se ejecuta

```python
from orbital_sentinel.catalog import verify_integrity

report = verify_integrity(snapshots_repo, elements_repo)
if report.has_violations:
    # Fallar CI / alertar operacionalmente
    for orphan in report.orphan_elements:
        ...
    for gap in report.index_gaps:
        ...
```

Complejidad: `O(N)` filas Normalized + `O(M)` filas Raw, ambas materializadas en memoria. Para Fase 1 (≤ 10⁵ filas) es aceptable. Si escala, sustituir por queries DuckDB selectivas con `EXCEPT` y `LEFT JOIN`.

---

## Tests que demuestran detección

Cubiertos en `tests/unit/test_integrity.py`:

| Test                                                    | Invariante | Tipo de violación                     |
|---------------------------------------------------------|------------|---------------------------------------|
| `test_empty_state_has_no_violations`                    | —          | Baseline                              |
| `test_clean_state_when_raw_and_normalized_consistent`   | —          | Baseline                              |
| `test_only_raw_marks_unnormalized_but_not_violation`    | (informativo) | unnormalized_snapshots               |
| `test_detects_orphan_element_pointing_nowhere`          | I1         | Inserción ad-hoc                      |
| `test_detects_orphan_after_manual_raw_deletion`         | I1         | Corrupción manual de archivos         |
| `test_orphan_report_carries_engine_version`             | I1         | Validación de campos del reporte      |
| `test_multiple_orphans_in_same_batch`                   | I1         | Múltiples huérfanos                   |
| `test_detects_index_gap_missing_zero`                   | I2         | Índice 0 ausente                      |
| `test_detects_index_gap_in_middle`                      | I2         | Índice intermedio ausente             |
| `test_no_gap_when_indices_contiguous`                   | I2         | Negativo: no falso positivo           |
| `test_index_gap_isolated_per_engine_version`            | I2         | Aislamiento por engine_version        |
| `test_orphan_and_unnormalized_coexist`                  | I1 + info  | Mezcla de estados                     |
| `test_report_is_pydantic_frozen_violations`             | —          | Inmutabilidad del reporte             |

Y en `tests/integration/test_ingest_pipeline.py`:

| Test                                | Demuestra                                                          |
|-------------------------------------|--------------------------------------------------------------------|
| `test_end_to_end_passes_integrity`  | Tras un pipeline completo end-to-end, `has_violations is False`.   |
