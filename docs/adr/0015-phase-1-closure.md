# ADR-0015: Cierre formal de Fase 1

**Estado:** Aceptado
**Fecha:** 2026-06-06
**Autor:** Orbital Sentinel
**Supersede a:** ninguno
**Relacionado con:** ADR-0000 (visión y fases), ADR-0014 (SGP4)

---

## Contexto

ADR-0000 define cinco fases del proyecto. **Fase 1 — "Observabilidad orbital"** se enumera como: *"Ingesta de TLEs, propagación SGP4, visualización"*.

Este ADR registra formalmente que los tres componentes están implementados, verificados y validados arquitectónicamente, y por tanto Fase 1 se considera **cerrada**.

## Decisión

Fase 1 está cerrada con los siguientes artefactos verificables:

### Ingesta de TLEs

- `CelesTrakSource` (sin credenciales, ADR-0011) con `FetchCache` content-addressable.
- `IngestPipeline` (`fetch → persist Raw → normalize → persist Normalized`).
- Trazabilidad: `content_hash` de bytes recibidos == FK lógica desde toda fila Normalized.
- ADRs relacionados: 0011 (secrets), 0012 (local-first).

### Propagación SGP4

- `Sgp4Propagator` wrapper sobre librería `sgp4` con `Satrec.twoline2rv` sobre líneas originales.
- Golden master contra librería de referencia (bit-exact).
- `Ephemeris` con FK completa `(content_hash_source, tle_index, tle_content_hash, norad_cat_id)`.
- On-demand puro (sin persistencia, ADR-0006 enmienda 1).
- ADR-0014.

### Visualización

- `plot_groundtrack` en `orchestration/groundtrack.py`: PNG 2D estático equirectangular.
- Conversiones TEME → ECEF (via GMST IAU 1982 simplificado) → lat/lon esférica.
- Caption documenta explícitamente: SGP4 ~1–3 km + crecimiento ~1–3 km/día, lat/lon esférica sub-km error vs WGS84.
- ADR-0008 Cesium queda reservado para 3D interactivo en Fase 2+. Son escalas distintas, no alternativas.

### Validación arquitectónica

- **197 tests pasando**.
- Capas Raw / Normalized / Derived completamente trazables.
- Integridad referencial verificable con `verify_integrity()` (ADR-0006).
- Benchmark DuckDB+Parquet ejecutado y decidido (ADR-0004 enmienda 2).
- Pipeline orchestration end-to-end testeado sin red (ADR-0002 enmienda 1).

### Interfaz de usuario

- `orbital-sentinel ingest <dataset>`
- `orbital-sentinel propagate <norad_id> --from --to --step`
- `orbital-sentinel plot-groundtrack <norad_id> --from --to --step --output`

Entry point registrado en `pyproject.toml [project.scripts]`.

## Qué congela este ADR

Lo que se congela aquí es el **alcance funcional** de Fase 1, no el código. Cambios futuros sobre estos componentes (mejoras, fixes, refactors) siguen permitidos vía PRs normales. Lo que cambia es la lectura de esos cambios: pasan a ser **modificaciones de un componente Fase 1 cerrado**, no ampliaciones de fase abierta.

## Qué NO está incluido en Fase 1 (queda para fases posteriores)

- Conjunciones (Fase 2 — iniciada con ADR-0016 v0.1).
- Detección de maniobras (Fase 3).
- Anomalías (Fase 4).
- Agente LLM explicativo (Fase 5, ADR-0009).
- Cesium 3D interactivo (Fase 2+, ADR-0008).
- Persistencia automática de efemérides (no planificada; ADR-0006 enmienda 1).
- Multi-fuente de TLEs (Space-Track, etc.) — opt-in futuro.

## Consecuencias

**Positivas**
- Hito explícito que fija el alcance entregado.
- Cambios futuros sobre componentes Fase 1 se identifican como tales, no como ampliaciones de roadmap abierto.
- Habilita formalmente el inicio de Fase 2.

**Negativas**
- Ninguna.

**Neutras**
- Este ADR no introduce código nuevo. Es un sello de estado.

## Alineación con ADR-0000

- **Implementa** Fase 1 declarada en ADR-0000.
- Refuerza P1 (trazabilidad), P3 (coste cero), P4 (validación operacional de reproducibilidad), P8 (local-first).
- **Sin tensiones.**

## Referencias

- ADR-0000 §"Hoja de ruta por fases".
- ADR-0014 SGP4.
- README §"Estado actual".

---

## Historial de enmiendas

*Sin enmiendas a fecha de aceptación.*
