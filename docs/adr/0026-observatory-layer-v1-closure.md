# ADR-0026: Cierre formal de Observatory Layer v1

**Estado:** Aceptado
**Fecha:** 2026-06-06
**Autor:** Orbital Sentinel
**Supersede a:** ninguno
**Relacionado con:** ADR-0015 (cierre Fase 1), ADR-0021 (cierre Fase 2), ADR-0023, ADR-0024, ADR-0025

---

## Contexto

ADR-0015 cerró Fase 1 (Observabilidad orbital — ingesta + propagación + groundtrack). ADR-0021 cerró Fase 2 (Conjunciones y proximidad). Entre Fase 2 y la futura Fase 3 (detección de maniobras) se introdujo una nueva capa observer-centric — *Observatory Layer v1* — compuesta por tres ADRs encadenados (0023, 0024, 0025) y cuatro nuevos subcomandos CLI.

Este ADR no introduce nuevas decisiones arquitectónicas. Documenta el cierre formal de la capa siguiendo el mismo patrón de ADR-0015 y ADR-0021.

## Decisión

Declarar **Observatory Layer v1 cerrada** en estado funcional, deterministico, sin red y sin persistencia nueva.

## Componentes incluidos

### ADR-0023 — Pass prediction v0.1

- `analytics/passes/{geometry,analysis}.py`
- `predict_passes(element, snapshot, observer, window, step) → PassPrediction`
- Honesty fields: `frame_model`, `gmst_model`, `aos_los_resolution_seconds`, `culmination_method`, `sgp4_uncertainty_*`
- 5 enmiendas integradas (tca→culmination, GEO 88°N, observer validation, UT1≈UTC cuantificado, política sub-grid)
- CLI: `orbital-sentinel passes`

### ADR-0024 — Solar geometry primitives v0.1

- `analytics/solar/{sun_position,context}.py`
- `sun_position_eci(when) → ECI [km]` (Vallado 2008 §5.1, ~0.01° angular)
- `solar_context_at(observer, when) → SolarContext` con clasificación USNO de twilight
- `is_satellite_illuminated(sat_eci, when) → bool` (sombra cilíndrica v1)
- Honesty fields: `solar_position_model`, `shadow_model`, `atmospheric_refraction_assumed_zero`, `valid_date_range_iso`
- Sin CLI propio (consumido por ADR-0025)

### ADR-0025 — Observatory scan v0.1

- `analytics/observatory/{scan,ranking,conflicts}.py`
- `scan_observatory(...) → ObservatoryScan` con pre-filtro geométrico O(1) (análogo a ADR-0018)
- `rank_passes(scan, criterion, limit) → list[RankedPass]` con 4 criterios declarados
- `detect_pass_conflicts(scan, overlap_threshold) → list[PassConflict]`
- Honesty fields propagados: filtro útil declarado + identifiers de los modelos físicos heredados
- CLI: `orbital-sentinel scan`, `best`, `conflicts`

### Refactor preparatorio (ADR-0023 Fase 1)

- `propagation/frames.py` extraído con `gmst_iau_1982`, `teme_to_ecef`, `GMST_MODEL_NAME`
- `orchestration/groundtrack.py` preserva alias `gmst_radians` por compatibilidad

## Criterios de aceptación verificados

| Criterio | Estado |
|----------|--------|
| Los 3 ADRs (0023, 0024, 0025) aceptados | ✅ |
| 4 nuevos subcomandos CLI funcionales | ✅ `passes`, `scan`, `best`, `conflicts` |
| Determinismo bit-exacto | ✅ verificado en tests P15 + observatory_determinism |
| Sin nuevas dependencias | ✅ |
| Sin red en runtime | ✅ |
| Sin persistencia nueva | ✅ todo on-demand |
| Honesty fields ADR-0020 en cada output | ✅ |
| Versioning ADR-0010 en cada capacidad | ✅ |
| Provenance FK Raw→Normalized→Derived preservada | ✅ |
| Tests verdes | ✅ **396 passed, 2 skipped intencionales** |
| Cero regresión vs estado pre-Observatory Layer (299 base) | ✅ |
| Frozen models + `extra="forbid"` | ✅ |

## Componentes Derived implementados

Modelos Pydantic (`frozen=True, extra="forbid"`):
- `Pass`, `PassPrediction` (ADR-0023)
- `SolarContext`, `TwilightPhase` (ADR-0024)
- `UsefulPassFilter`, `SatellitePasses`, `ObservatoryScan`, `RankingCriterion`, `RankedPass`, `PassConflict` (ADR-0025)

Funciones puras públicas (16 total):
- `observer_to_ecef`, `ecef_to_enu`, `enu_to_elevation_azimuth` (geometría)
- `gmst_iau_1982`, `teme_to_ecef` (frames)
- `predict_passes` (pases)
- `sun_position_eci`, `solar_context_at`, `is_satellite_illuminated`, `twilight_darkness_rank` (solar)
- `is_geometrically_unreachable`, `scan_observatory`, `rank_passes`, `detect_pass_conflicts` (observatory)

Constantes machine-readable de honestidad (10 identifiers v0.1):
- `FRAME_MODEL_NAME`, `GMST_MODEL_NAME`, `CULMINATION_METHOD_NAME`
- `SOLAR_POSITION_MODEL_NAME`, `SHADOW_MODEL_NAME`, `VALID_DATE_RANGE_ISO`
- `OVERLAP_DEFINITION_NAME`, `USEFUL_PASS_FILTER_VERSION`, `RANKING_CRITERIA_VERSION`
- `SGP4_UNCERTAINTY_BASELINE_KM`, `SGP4_UNCERTAINTY_GROWTH_KM_PER_DAY`

## Preguntas operacionales cubiertas

| # | Pregunta | Subcomando |
|---|----------|------------|
| 1 | ¿Cuándo es visible un satélite desde mi ubicación? | `passes` |
| 2 | ¿Dónde debe mirar el observador? | `passes` (azimuth en AOS / culminación / LOS) |
| 3 | ¿Cuántos pases útiles tendré en una ventana? | `scan` con filtros twilight + illumination |
| 4 | ¿Qué pases exceden una elevación mínima? | `passes` / `scan` con `--min-elevation` |
| 5 | ¿Qué satélite es mejor desde aquí? | `best` con criterio elegible |
| 6 | ¿Qué pases entran en conflicto simultáneo? | `conflicts` |

## Lo que Observatory Layer v1 NO incluye

Diferido explícitamente:

- **WGS84 elipsoidal** — sub-dominante al régimen SGP4.
- **Refracción atmosférica** — sub-dominante en elevaciones ≥5°.
- **Modelo sombra cónica** (umbra/penumbra) — error ~10s acotado, declarado.
- **Doppler / range-rate / range** en el modelo `Pass` — derivables externamente con la velocidad TEME existente.
- **Persistencia de pases o scans** — on-demand puro, mismo régimen que `Ephemeris`.
- **Multi-observador** (varios sitios a la vez) — asimétrico al caso típico.
- **CLI subcomando `sun`** — primitiva consumible internamente, sin caso de uso CLI inmediato.
- **Fuentes autenticadas** (Space-Track) — fuera de scope.
- **Vista satélite-from-space** — pases inversos sin caso de uso.
- **Conflictos triples** — v0.1 solo pares.

Cada uno de estos puede entrar como enmienda o nuevo ADR si la realidad operacional lo justifica.

## Alineación con ADR-0000

- **Refuerza P2** (honestidad sobre incertidumbre): 10 honesty identifiers + 7 constantes de incertidumbre física emitidos en cada output relevante.
- **Refuerza P3** (cost zero baseline): cero dependencias nuevas; stdlib + Pydantic + sgp4 ya presentes.
- **Refuerza P7** (fuentes públicas): no introduce fuente nueva.
- **Refuerza P8** (local-first): sin red, sin servicios externos.
- **Compatible con P1/P4** (trazabilidad/reproducibilidad): provenance FK preservada; determinismo verificado.
- **Sin tensiones.**

## Posición en la hoja de ruta

Observatory Layer v1 se sitúa entre Fase 1 (Observabilidad orbital) y Fase 3 (Detección de maniobras), extendiendo la dimensión "observabilidad" desde el groundtrack abstracto hasta la planificación observer-centric concreta. **No es una nueva fase del roadmap original**; es la maduración operativa de Fase 1 ahora que Fase 2 cerró.

La próxima decisión arquitectónica significativa será el alcance y modelo de **Fase 3 — Detección de maniobras**, que requerirá su propio ADR-0027 + cadena.

## Referencias

- ADR-0015 (cierre Fase 1, patrón de cierre seguido por este ADR).
- ADR-0021 (cierre Fase 2, idem).
- ADR-0023 (Pass prediction v0.1).
- ADR-0024 (Solar geometry primitives v0.1).
- ADR-0025 (Observatory scan v0.1).

---

## Historial de enmiendas

*Sin enmiendas a fecha de aceptación.*
