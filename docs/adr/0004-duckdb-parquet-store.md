# ADR-0004: DuckDB + Parquet como store primario

**Estado:** Aceptado
**Fecha:** 2026-06-03
**Autor:** Orbital Sentinel
**Supersede a:** ninguno
**Relacionado con:** ADR-0000 (P1, P3, P4, P7, P8), ADR-0001, ADR-0002, ADR-0006

---

## Contexto

- Tipos de datos a almacenar: TLEs raw, elementos normalizados, efemérides propagadas, eventos analíticos (conjunciones, maniobras, anomalías), salidas de agente.
- Volumen orden de magnitud: catálogo público ~30 000 objetos; TLE rate ~1–3 por objeto por semana → serie temporal acumulativa de millones de filas/año en `orbital_elements`, decenas de millones/año en `ephemerides`.
- Query patterns: analíticos (ventanas temporales, agregaciones, joins), no OLTP transaccional.
- ADR-0001 exige embebido, sin servidor en baseline.

## Decisión

- **Parquet** como formato canónico en disco.
- **Particionamiento temporal** por mes para datos de serie temporal; por objeto para datos por entidad.
- **DuckDB** como motor analítico embebido sobre Parquet.
- **Sin client-server database** en baseline. Si en el futuro se requiere multi-writer concurrente con baja latencia, un ADR posterior puede añadir Postgres+TimescaleDB sin tocar Parquet (que sigue siendo el formato canónico).
- **Pin de versión de DuckDB** en `pyproject.toml`; bumps deliberados con tests de regresión.

## Justificación

- DuckDB es embebido → satisface ADR-0001 sin compromiso.
- Parquet es columnar, comprimido, portable; lo leen `pyarrow`, `polars`, Spark, Dask y herramientas externas sin importar.
- DuckDB lee Parquet directamente sin paso de import.
- Migración futura a Postgres es trivial porque los datos canónicos viven en Parquet, no en formato propietario.
- Compresión Parquet (snappy/zstd) reduce footprint local en orden de magnitud frente a CSV/JSON.

## Consecuencias

**Positivas**
- Cero ops.
- Queries analíticas rápidas sobre datasets de GB en un portátil.
- Backups por copia de directorio.

**Negativas**
- Single-writer en momentos dados (aceptable para writes orquestados).
- Versión de DuckDB puede afectar estabilidad de queries → mitigado por pin + tests de regresión.

**Neutras**
- Disciplina de esquemas Parquet requerida; gestionada en `catalog/schemas/`.

## Alternativas consideradas

### A. SQLite
**Razón de rechazo:** maduro pero subóptimo para queries analíticas sobre series temporales largas; sin compresión columnar.

### B. PostgreSQL + TimescaleDB (baseline)
**Razón de rechazo:** requiere servidor, viola ADR-0001.

### C. InfluxDB / TimescaleDB Cloud / ClickHouse Cloud
**Razón de rechazo:** SaaS, viola ADR-0001 y P3.

### D. Solo Parquet sin engine
**Razón de rechazo:** queries analíticas más complejas; DuckDB añade SQL sin coste de lock-in (formato sigue siendo Parquet).

### E. ClickHouse embebido (`clickhouse-local`)
**Razón de rechazo:** menor madurez de binding Python; binarios pesados.

## Alineación con ADR-0000

- **Refuerza P1, P4** (Parquet inmutable es ideal para inmutabilidad por hash; ADR-0006 lo formaliza).
- **Refuerza P3, P8** (cero ops, local).
- **Refuerza P7** (Parquet abierto, sin vendor lock).
- **Sin tensiones.**

## Referencias

- Raasveldt, M., Mühleisen, H. (2019). *DuckDB: an Embeddable Analytical Database.*
- DuckDB Foundation. *DuckDB documentation.*
- Apache Parquet specification.

---

## Historial de enmiendas

### 2026-06-03 — Enmienda 1
**Benchmark obligatorio durante Fase 1.** El red-team review (F4) identificó la concurrencia single-writer de DuckDB como riesgo de cuello de botella en Fase 2 (ingestor + conjuncionador escribiendo simultáneamente). Antes de cerrar el diseño de Fase 2, Fase 1 debe incluir:

1. Benchmark de patrones de escritura concurrente sobre la arquitectura propuesta (ingestor + un segundo escritor sintético) con cargas representativas de Fase 2.
2. Medición de latencia de write contention y tasa de fallos.
3. Decisión documentada: mantener DuckDB single-writer con orquestador serializador, particionar por archivo DuckDB, o iniciar migración a Postgres+TimescaleDB.

La decisión queda pendiente del benchmark. Mientras tanto, DuckDB se mantiene como elección provisional.

### 2026-06-06 — Enmienda 2
**Benchmark ejecutado. Decisión: mantener el patrón actual sin cambios.**

El benchmark requerido por la enmienda 1 se ejecutó. Reporte completo en `docs/benchmarks/duckdb_concurrency.md`. JSON crudo en `benchmarks/duckdb_concurrency/results/`.

**Reformulación del supuesto de F4.** El red-team review supuso un único archivo `.duckdb` nativo con lock global de single-writer. **No es lo que implementa Orbital Sentinel.** El stack real es `pyarrow.parquet.write_table` por archivo idempotente (atomicidad por `tmp.replace`) + `DuckDB read_parquet` read-only. No hay `.duckdb` file y no hay lock global. El supuesto operativo de F4 era incorrecto.

**Resultados** (200 snapshots/escenario sobre Windows 10, Python 3.11.9, DuckDB 1.5.3, PyArrow 19.0.1):

| Escenario | Throughput (ins/s) | Fallos | Integridad |
|---|---:|---:|:---:|
| 1 writer baseline | 1 047 | 0 | OK |
| 2 writers | 1 534 | 0 | OK |
| 4 writers | **1 959** | 0 | OK |
| 8 writers | 1 884 | 0 | OK |
| 1 writer + 1 reader | 758 | 0 | OK |
| 4 writers + 1 reader | 1 379 | 0 | OK |

Cero corrupción, cero fallos, integridad completa en los seis escenarios. Pico a 4 workers (~2 000 ins/s); saturación entre 4 y 8.

**Decisión:** mantener el patrón actual. **No** se requiere serializador, particionado adicional, ni migración a Postgres+TimescaleDB. Una ingesta representativa de CelesTrak (10–30 snapshots) tarda decenas de milisegundos a estos throughputs; hay un orden de magnitud de margen respecto a Fase 2.

**Condiciones para reabrir** (cualquiera de los siguientes dispara nueva evaluación):

- Catálogos con > 50 000 archivos Parquet en un mismo directorio donde el reader degrade `count()`/`iter_all()` por encima de 1 segundo. Mitigación esperada: compactación periódica.
- Throughput requerido > 5 000 ins/s sostenidos (ingestión multi-fuente concurrente).
- Fallos de escritura no asociados a disco lleno o permisos en operación normal.
- Necesidad de transaccionalidad cross-tabla (insertar snapshot + sus normalized rows atómicamente). Esto sí justifica considerar Postgres+TimescaleDB.

DuckDB+Parquet deja de ser "elección provisional" y pasa a ser **elección validada empíricamente para el régimen de Fase 1–2**.

**Limitaciones del benchmark documentadas explícitamente**: no se midió el coste de queries con 10 000+ archivos pre-existentes, ni mem profile bajo carga sostenida, ni alternativas (Postgres, otros engines). Si la siguiente fase encuentra un problema concreto, se drillará en él. Reproducible vía `python -m benchmarks.duckdb_concurrency.runner`.
