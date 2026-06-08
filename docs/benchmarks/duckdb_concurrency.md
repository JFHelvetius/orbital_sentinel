# Benchmark: concurrencia DuckDB + Parquet sobre la capa Raw

**Estado:** ejecutado y decidido.
**Fecha:** 2026-06-06.
**Motivado por:** ADR-0004 enmienda 1 (precondición de Fase 2), red-team review F4.
**Decisión registrada en:** ADR-0004 enmienda 2.

---

## Pregunta arquitectónica única

Bajo cargas concurrentes representativas de Fase 2, ¿el patrón actual de almacenamiento — `pyarrow.parquet.write_table` por archivo idempotente + `DuckDB read_parquet` para queries — mantiene throughput aceptable y consistencia de lectura sin corrupción?

## Reformulación del concepto de "DuckDB single-writer"

El red-team F4 supuso un único archivo `.duckdb` nativo con lock global. **No es lo que implementa Orbital Sentinel.** El stack real es:

- **Escritura:** `pyarrow.parquet.write_table()` a un archivo Parquet por snapshot (nombrado por `content_hash`). Atomicidad por `tmp.replace(path)`. Sin `.duckdb` file y sin lock global.
- **Lectura:** `duckdb.connect(":memory:")` por query, ejecuta `read_parquet(glob)` con `hive_partitioning=false`, cierra.

El cuello de botella relevante por tanto **no es** "DuckDB single-writer" sino: contención del filesystem en escrituras concurrentes a Parquet + coherencia de lectura de DuckDB sobre directorios mientras se escriben.

## Workload sintético

- 200 snapshots por escenario, ~700 bytes de payload cada uno (tamaño realista de un GP TLE multi-objeto de CelesTrak).
- `content_hash` único por snapshot (sintético, no hash real del payload — para este benchmark no importa).
- Todos los snapshots caen en la misma partición temporal (`year=2026/month=06/`), forzando contención máxima en un único directorio.

## Entorno

| | |
|---|---|
| Plataforma | Windows-10-10.0.26200-SP0 |
| Python | 3.11.9 |
| DuckDB | 1.5.3 |
| PyArrow | 19.0.1 |
| Orbital Sentinel | 0.0.1 |
| N por escenario | 200 |

## Resultados

| Escenario | Writers | Readers | Tiempo (ms) | Throughput (ins/s) | Fallos | Integridad |
|---|---:|---:|---:|---:|---:|:---:|
| baseline (1 writer) | 1 | 0 | 191 | 1 047 | 0 | OK |
| concurrent 2 writers | 2 | 0 | 130 | 1 534 | 0 | OK |
| concurrent 4 writers | 4 | 0 | **102** | **1 959** | 0 | OK |
| concurrent 8 writers | 8 | 0 | 106 | 1 884 | 0 | OK |
| 1 writer + 1 reader | 1 | 1 | 264 | 758 | 0 | OK |
| 4 writers + 1 reader | 4 | 1 | 145 | 1 379 | 0 | OK |

Reader query latency observada (`count()` sobre directorio mientras se escribe):

| Escenario | Queries | p50 (ms) |
|---|---:|---:|
| 1 writer + 1 reader | 18 | 17.06 |
| 4 writers + 1 reader | 16 | 0.88 |

**Nota:** la latencia del reader baja en el escenario de 4 writers no porque DuckDB sea más rápido sino porque el escenario completo dura menos (145 ms vs 264 ms) y el reader captura menos queries, todas con menos archivos presentes en el directorio. No es una métrica fiable de "cómo se comporta el reader bajo carga". Para esa pregunta hace falta un benchmark dedicado con catálogo pre-poblado, fuera del scope de este ejercicio.

## Hallazgos

1. **Cero corrupción y cero fallos** en los seis escenarios. Las 1 200 inserciones (200 × 6) se persistieron correctamente. La atomicidad de `tmp.replace(path)` se sostiene bajo concurrencia threading sobre NTFS.
2. **Escalado positivo hasta 4 workers.** Throughput crece de 1 047 → 1 534 → 1 959 ins/s al pasar de 1 → 2 → 4 workers (~1.9× respecto al baseline). El cuello dominante a baja concurrencia es CPU + I/O secuencial; threading lo desacopla.
3. **Saturación entre 4 y 8 workers.** A 8 workers el throughput desciende ligeramente (1 884 ins/s) por overhead de scheduling y contención de filesystem.
4. **El reader no se ve bloqueado por los writers.** Las queries `count()` completan en milisegundos sin fallos durante toda la ejecución concurrente.
5. **Throughput suficiente para Fase 2.** Una ingesta representativa de CelesTrak completa ~10–30 snapshots reales por ejecución. A ~2 000 ins/s, una ingesta entera tarda decenas de milisegundos.

## Decisión

**Mantener el patrón actual sin cambios.** No se requiere serializador, particionado adicional, ni migración a Postgres+TimescaleDB.

Argumentación:

- El supuesto del red-team F4 (single-writer DuckDB lock) **no aplica al stack real**.
- El stack real (pyarrow por archivo + DuckDB read-only) **no muestra contención observable** bajo cargas un orden de magnitud superiores a Fase 2 representativa.
- La idempotencia por `content_hash` previene escritura al mismo archivo desde dos workers distintos por construcción.
- El cierre se hace **con datos**, no con asunciones.

## Condiciones para reabrir esta decisión

Bumper la prioridad y rehacer benchmark si **alguno** de los siguientes se materializa:

- Catálogos con > 50 000 archivos Parquet en un mismo directorio donde el reader degrada en `count()`/`iter_all()` por encima de 1 segundo. Mitigación esperada: compactación periódica de Parquet (no migración a otro motor).
- Throughput requerido > 5 000 ins/s sostenidos (e.g., ingestión multi-fuente concurrente con normalizadores múltiples).
- Aparición de fallos de escritura no asociados a disco lleno o permisos en operación normal.
- Necesidad de transaccionalidad cross-tabla (e.g., insertar snapshot + sus normalized rows atómicamente). Esto sí requeriría un motor con transacciones, y entonces Postgres+TimescaleDB entraría en juego.

Hasta que alguno de esos disparadores ocurra, **no es razonable invertir en migración**.

## Lo que este benchmark NO mide (acotación de scope deliberada)

- Compresión Parquet alternativa (snappy, zstd levels).
- Mem profile bajo carga sostenida.
- Otras versiones de DuckDB o PyArrow.
- Comparación contra Postgres/TimescaleDB.
- Recovery tras kill -9 en medio de un write.
- Long-duration tests (horas).
- Coste de `count()` / `iter_all()` con 10 000+ archivos pre-existentes en el directorio.

Si la siguiente fase encuentra problemas, se drillará en el ítem específico. No se mide preventivamente.

## Reproducción

```powershell
cd c:\Users\USER\Desktop\orbital-sentinel
$env:PYTHONIOENCODING="utf-8"
.venv\Scripts\python.exe -m benchmarks.duckdb_concurrency.runner
```

JSON crudo: `benchmarks/duckdb_concurrency/results/<timestamp>.json`.
