# ADR-0021: Cierre formal de Fase 2

**Estado:** Aceptado
**Fecha:** 2026-06-06
**Autor:** Orbital Sentinel
**Supersede a:** ninguno
**Relacionado con:** ADR-0000 (visión y fases), ADR-0015 (cierre Fase 1), ADRs 0016-0020 (pairwise v0.1-v1.0)

---

## Contexto

ADR-0000 define cinco fases. **Fase 2 — "Conjunciones y proximidad"** se enumera como: *"screening masivo y probabilidad de colisión"*.

Este ADR registra formalmente que ambos componentes están implementados, verificados y validados arquitectónicamente, y por tanto Fase 2 se considera **cerrada**.

Es el segundo cierre formal del proyecto (tras ADR-0015 para Fase 1) y completa el primer ciclo arquitectónico Raw → Normalized → Derived (on-demand + persistido) con su mecanismo analítico fundamental.

## Decisión

Fase 2 está cerrada con los siguientes artefactos verificables, distribuidos en 5 incrementos progresivos:

### v0.1 — Pairwise analysis (ADR-0016)

- `ConjunctionAnalysis` Pydantic frozen con **doble FK** (provenance binaria Raw → Normalized para ambos objetos).
- `analyze_pairwise_conjunction(element_a, snapshot_a, element_b, snapshot_b, ...)` analiza un par específico.
- Régimen de precisión declarado en cada resultado (mitigación red-team F6).
- **TCA discreto** = step de mínima distancia en la grid.
- CLI: `orbital-sentinel conjunction <a> <b> --from --to --step`.

### v0.2 — TCA refinement por bisección (ADR-0017)

- `_refine_tca_bisection()` privada con bisección sobre `f(t) = (r_a - r_b) · (v_a - v_b)`.
- Tolerancia 1 segundo (~9 iteraciones), coste < 1 ms.
- Campo nuevo `tca_was_refined: bool` desambigua semántica de `tca_resolution_minutes`.
- Edge cases con fallback al discreto (min en borde, bracket degenerado).
- Bump MINOR de versiones: schema y engine 0.1.0 → 0.2.0.

### v0.3 — N-to-N screening con filtro apogeo/perigeo (ADR-0018)

- `analyze_pairwise_screening()` toma lista de `(OrbitalElement, TLESnapshot)` → `ScreeningResult`.
- Filtro previo apogeo/perigeo derivado de `a = (GM/n²)^(1/3)`, `perigee = a(1-e)`, `apogee = a(1+e)`. O(1) por par.
- Cap defensivo `max_pairs = 5000`. Excederlo lanza explícitamente.
- Counts auditable: total / filtered_out / screened / detections.
- CLI: `orbital-sentinel screen --norad-ids X,Y,Z --threshold-km K`.

### v0.4 — Persistencia de detecciones (ADR-0019)

- **Primera tabla Derived persistente del proyecto.**
- `ConjunctionDetection` flat schema 28 campos. Content-addressable por SHA-256 canónico.
- `ConjunctionDetectionsRepository` Parquet/DuckDB con insert idempotente, `find_by_norad`.
- `verify_detections_integrity()` chequea cadena Raw → Detection.
- CLI: `--persist` flag en `screen`, comando `detections [--norad N] [--limit N]`.

### v1.0 — Probability of collision bajo covarianza declarada (ADR-0020)

- **Cierra Fase 2** según definición de ADR-0000.
- Módulo `probability.py` con modelo `tle_isotropic_spherical_v1` (σ₀=1 km, α=1 km/día) y método Foster 1992 fast.
- **7 campos obligatorios** persistidos en cada resultado documentan TODAS las asunciones.
- `combined_hard_body_radius_km` default 0 → Pc=0 (honestidad: sin radio declarado, sin Pc físicamente significativo).
- Bump MINOR: schema y engine 0.2.0 → 0.3.0, persistence 0.1.0 → 0.2.0.
- CLI: `--combined-radius-km KM` opcional en `conjunction` y `screen`.

## Validación arquitectónica

| Test | Resultado |
|------|-----------|
| Suite completa | **292 tests pasando** |
| ConjunctionAnalysis tests | 35+ tests (pairwise + refinamiento + Pc + assumption fields) |
| Screening tests | 20 tests (N-to-N + filtro + edge cases) |
| Detection persistence tests | 22 tests (idempotencia + roundtrip + integridad cross-layer) |
| Probability tests | 20 tests (covarianza + Pc monotonía + edge cases) |
| CLI integration tests | 9 tests (conjunction + screen + detections + Pc end-to-end) |
| Smoke tests manuales | 5 ejecuciones reales documentadas |

## Patrones arquitectónicos establecidos durante Fase 2

1. **Triple versionado por fila persistida.** Una `ConjunctionDetection` lleva `persistence_schema_version`, `analysis_schema_version`, `analysis_engine_version` — tres SemVers independientes. Pattern ADR-0010 ejercitado en producción, no solo declarado.

2. **Content-addressable identity con ordering canónico.** `compute_detection_hash` usa `sorted(tle_content_hashes)` para que `(A,B)` y `(B,A)` produzcan el mismo hash. Una conjunción es una conjunción independientemente del orden de los argumentos.

3. **Régimen de precisión como dato, no como nota.** Cada resultado materializa los parámetros de incertidumbre en campos explícitos del modelo (no en docstrings ni README). Implementa ADR-0000 P2 al nivel de fila.

4. **Assumption fields obligatorios para honestidad.** Pc v1.0 lleva 7 campos requeridos que contextualizan el número. Un caller que devuelve solo el número viola el contrato del módulo.

5. **Filtro O(1) preferido sobre algoritmos más sofisticados.** Apogee/perigee descarta >90% en catálogos mixtos LEO+MEO+GEO. Smart-sieve y otras optimizaciones quedan diferidas hasta evidencia de necesidad.

6. **Defaults conservadores en lugar de comportamiento por defecto comprometedor.** `combined_hard_body_radius_km = 0.0` significa "el caller debe declarar el radio para obtener Pc significativo" en lugar de asumir un radio típico. Honesto > conveniente.

7. **Primera tabla Derived persistida** con justificación arquitectónica explícita en ADR-0019: detecciones son raras + económicas + auditoría histórica importante. Distinto de Ephemeris (densas, costosas, regenerables).

## Qué congela este ADR

El **alcance funcional** de Fase 2, no el código. Cambios futuros sobre estos componentes (mejoras, fixes, refactors) siguen permitidos vía PRs normales. Lo que cambia es la lectura de esos cambios: pasan a ser **modificaciones de un componente Fase 2 cerrado**, no ampliaciones de fase abierta.

## Qué NO está incluido en Fase 2 (queda para fases posteriores)

- **Detección de maniobras** (Fase 3). Sigue requiriendo ingesta periódica de TLEs para producir time-series.
- **Sistema de anomalías** (Fase 4).
- **Agente LLM explicativo** (Fase 5, ADR-0009 enmienda 1: nunca fuente de verdad).
- **Cesium 3D interactivo** (Fase 2+ en ADR-0008, no en Fase 2 cerrada per esta interpretación).
- **Comparación contra CDM público** (US Space Force). Útil para validación, ADR posterior si se justifica.
- **Propagación de covarianza a través de SGP4** (v2.0 hipotética). Requiere derivadas de SGP4.
- **Múltiples modelos de covarianza comparativos**.
- **Persistencia de Ephemeris** (sigue prohibido por ADR-0006 enmienda 1, F5 red-team).
- **Compactación de archivos en `conjunctions/`** (operacional, futuro si se justifica).

## Consecuencias

**Positivas**
- Segundo hito explícito que fija el alcance entregado. El proyecto puede declarar honestamente: *"Fase 2 según ADR-0000 está implementada y verificable"*.
- Cambios futuros sobre estos componentes se identifican como tales.
- Habilita formalmente el inicio de Fase 3 (cuando se justifique).
- El patrón "assumption fields obligatorios para honestidad" queda establecido como **el** método del proyecto para componentes con incertidumbre inherente. Aplicable a Fase 3, 4, 5.

**Negativas**
- Ninguna.

**Neutras**
- Este ADR no introduce código. Es un sello de estado.

## Alineación con ADR-0000

- **Implementa** Fase 2 declarada en ADR-0000.
- **Refuerza P1, P4** (trazabilidad y reproducibilidad mantenidas).
- **Refuerza P2** (honestidad sobre incertidumbre): Pc v1.0 es **el caso prototípico** del cumplimiento de P2 en un componente que tradicionalmente miente. ADR-0020 demuestra que el principio funciona en código real, no solo en documentación.
- **Refuerza P3, P8** (sin red, sin coste recurrente).
- **Compatible con no-objetivos**: Pc se entrega con todas las advertencias arquitectónicas; no se promete como "operacional aplicable sin verificación independiente".
- **Sin tensiones.**

## Referencias

- ADR-0000 §"Hoja de ruta por fases" (Fase 2).
- ADR-0015 (precedente: cierre formal de Fase 1).
- ADRs 0016-0020 (componentes de Fase 2).
- README §"Estado actual".
- `docs/architecture/layers.md` §"Derived".

---

## Historial de enmiendas

*Sin enmiendas a fecha de aceptación.*
