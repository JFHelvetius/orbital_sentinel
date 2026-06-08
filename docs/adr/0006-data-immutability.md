# ADR-0006: Inmutabilidad de datos, capas raw/normalized/derived, versionado por columna

**Estado:** Aceptado
**Fecha:** 2026-06-03
**Autor:** Orbital Sentinel
**Supersede a:** ninguno
**Relacionado con:** ADR-0000 (P1, P4), ADR-0001, ADR-0004

---

## Contexto

- ADR-0001 fija reproducible-first como principio.
- Necesidad de auditar cualquier inferencia pasada y permitir comparación A/B entre versiones de algoritmos.
- Operaciones típicas mezclan datos crudos descargados, datos derivados por parsing/validación, y outputs de propagación/analítica.

## Decisión

Tres capas estrictamente separadas y reglas universales sobre ellas:

### Capas

1. **Raw** — append-only, inmutable. Cada artefacto identificado por `content_hash` (SHA-256) del bytes original. Nunca se modifica, nunca se borra salvo política de retención explícita por antigüedad.
2. **Normalized** — derivable determinísticamente desde Raw. Cada fila referencia el `content_hash` que la originó. Regenerable desde cero si Raw está intacto.
3. **Derived** — outputs analíticos (efemérides, conjunciones, maniobras, anomalías). Cada fila incluye una columna de versión específica de la etapa (`engine_version`, `model_version`, `detector_version`, etc.).

### Reglas universales

- **Sin UPDATE.** Toda corrección es una nueva fila con epoch posterior. Las filas viejas no se borran; quedan como evidencia histórica.
- **Versionado por columna**, no por sufijo de tabla. Múltiples versiones coexisten en la misma tabla y se filtran por SELECT.
- **Retención configurable por capa**: Raw es eternamente inmutable salvo política explícita; Normalized puede regenerarse desde Raw; Derived puede limpiarse si Raw permite regenerarlo.
- **Content-addressable**: dos descargas del mismo TLE desde fuentes distintas se deduplican automáticamente al compartir hash.

## Justificación

- Reproducibilidad bit-exacta requiere inputs inmutables identificables.
- Sin UPDATE elimina toda una clase de race conditions y consistency bugs.
- Versionado por columna permite comparar resultados entre versiones de un mismo detector sin proliferar tablas.
- Hash-based addressing convierte a Raw en almacén content-addressable.

## Consecuencias

**Positivas**
- Auditabilidad total.
- Cualquier paper, post o issue puede citar un `content_hash` y ser reproducido.
- Comparar versión N vs N+1 de un detector es un SELECT con filtro de versión.

**Negativas**
- Más espacio en disco (mitigado por compresión Parquet y retention sobre Derived).
- Disciplina requerida en analytics: no se permite "update in place" como atajo.

**Neutras**
- Política de retención explícita por capa requerida; se documenta en `docs/operations/retention.md`.

## Alternativas consideradas

### A. Tablas mutables + audit log
**Razón de rechazo:** consistency entre tabla y log es propensa a divergencia; sin garantía de reproducibilidad bit-exacta.

### B. Snapshotting con Iceberg / Delta Lake
**Razón de rechazo:** overkill para single-node; coste operacional injustificado.

### C. Append-only sin versionado por columna
**Razón de rechazo:** imposibilita comparación entre versiones de un mismo algoritmo.

### D. Borrar Raw cuando Derived esté validado
**Razón de rechazo:** rompe la propiedad de reproducibilidad ante revisión retrospectiva.

## Alineación con ADR-0000

- **Refuerza P1, P4** explícitamente; son los principales clientes de esta decisión.
- **Compatible con P3** (Parquet comprimido controla coste).
- **Sin tensiones.**

## Referencias

- Kleppmann, M. (2017). *Designing Data-Intensive Applications*, Cap. 11 (stream processing y log inmutable).
- Git internals y Software Heritage: content-addressable storage.

---

## Historial de enmiendas

### 2026-06-03 — Enmienda 1
**Política de no-materialización de efemérides.** El red-team review (F5) calculó que materializar efemérides de ~30 000 objetos con paso de 60 s durante 5 años produciría del orden de 8 TB, incompatible con la propiedad P3 y la promesa de "ejecutarse en portátil moderno como producto principal" de ADR-0000.

Decisión: **las efemérides no se materializan por defecto.** Las trayectorias se calculan on-demand desde elementos normalizados + motor SGP4 (ADR-0005) en la ventana temporal solicitada por la query.

Excepciones permitidas, requieren ADR específico justificando la política:

- Caché de ventana corta para queries repetidas (TTL configurable, no inmutable).
- Materialización de eventos detectados (conjunciones, maniobras) — estos sí persisten como Derived inmutable, pero su tamaño es órdenes de magnitud menor que el de las efemérides completas.

Implicaciones para el modelo de datos:

- La tabla `ephemerides` mencionada en el cuerpo de este ADR no existe como capa Derived persistente por defecto.
- El cache opcional de ventana se aloja en una capa transitoria separada (`cache/`), explícitamente fuera del régimen de inmutabilidad de Derived.

Esta enmienda invalida la asunción implícita del cuerpo original de que las efemérides se almacenan. El cuerpo se mantiene como contexto histórico; las decisiones operacionales siguen esta enmienda.
