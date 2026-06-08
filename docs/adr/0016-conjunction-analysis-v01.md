# ADR-0016: Análisis de conjunción pairwise v0.1

**Estado:** Aceptado
**Fecha:** 2026-06-06
**Autor:** Orbital Sentinel
**Supersede a:** ninguno
**Relacionado con:** ADR-0005 (SGP4 only), ADR-0006 (capas), ADR-0010 (versioning), ADR-0014 (SGP4 integration)

---

## Contexto

ADR-0000 Fase 2 cubre "conjunciones y proximidad: screening masivo y probabilidad de colisión". Es el primer producto analítico no trivial sobre la capa Derived.

El red-team review F6 ya señaló: el ratio señal-ruido entre el error de propagación (~1–3 km) y los thresholds típicos de conjunción (1–10 km) es ≤ 3, lo que implica alta tasa de falsos positivos. ADR-0014 enmienda 1 aceptó esta precisión como riesgo conocido con la mitigación: *"Toda salida de Fase 2 debe declarar el régimen de precisión utilizado y su intervalo de confianza."*

Este ADR define el primer paso (v0.1) hacia Fase 2: **análisis pairwise entre dos objetos específicos**. No es mass screening (eso es v1.0). Es el cimiento arquitectónico binario.

## Decisión

### Alcance v0.1

**Análisis pairwise entre dos objetos identificados por NORAD ID.** El sistema:

1. Localiza el último `OrbitalElement` para cada NORAD.
2. Recupera sus respectivos `TLESnapshot`.
3. Propaga ambos con SGP4 sobre una grid de tiempos uniforme.
4. Calcula la distancia euclidiana en cada instante.
5. Devuelve el **TCA discreto** (= instante de la grid con mínima distancia), miss distance, velocidad relativa, y la declaración explícita del régimen de incertidumbre.

### Explícitamente excluido de v0.1

| Excluido | Razón | Cuándo |
|----------|-------|--------|
| Mass screening (N-to-N) | Complejidad prematura; el cimiento pairwise debe validar el modelo de datos binario primero. | v0.3+ |
| Refinamiento de TCA por bisección | La grid discreta es honesta sobre su limitación; refinar es scope creep. | v0.2 |
| Probabilidad de colisión (Pc) | Pc requiere covarianzas. SGP4 no las entrega. Asumir covarianzas estándar viola ADR-0000 P2 (honestidad sobre incertidumbre). | v1.0 con ADR específico de covarianzas |
| Persistencia de eventos | ADR-0006 enmienda 1 ya estableció el patrón on-demand. Persistir requiere decisión separada sobre retención, política de re-derivación, esquema. | v0.4 |
| Filtros pre-screening (apogeo/perigeo, smart-sieve) | Son optimizaciones de mass screening; pairwise no las necesita. | v0.3+ |
| Conversión de marco (TEME → ECI/ECEF) | El cálculo de distancia en TEME es físicamente correcto y suficiente. | nunca para esta tabla, sí en `viz` |

### Plano arquitectónico

La analítica vive en plano 6 `analytics/` (ADR-0002). Importa de Catalog (4), Propagation (5), Core (1). No importa de Orchestration ni Agent.

Estructura:
```
src/orbital_sentinel/analytics/
└── conjunctions/
    └── analysis.py    # ConjunctionAnalysis + analyze_pairwise_conjunction()
```

### Modelo de datos: `ConjunctionAnalysis`

Pydantic frozen con tres bloques:

**Identidad y provenance (doble FK Raw → Normalized → Derived):**

- `norad_a`, `norad_b`
- `element_a_content_hash_source`, `element_a_tle_index`, `element_a_tle_content_hash`
- `element_b_content_hash_source`, `element_b_tle_index`, `element_b_tle_content_hash`

**Ventana + resultado:**

- `window_start`, `window_end`, `step_minutes`, `n_samples`
- `tca`, `miss_distance_km`, `relative_velocity_km_s`
- `minutes_from_epoch_a_at_tca`, `minutes_from_epoch_b_at_tca`

**Régimen de precisión declarado** (ADR-0000 P2 + ADR-0014 enmienda 1 mitigación de F6):

- `sgp4_uncertainty_baseline_km = 3.0`
- `sgp4_uncertainty_growth_km_per_day = 3.0`
- `tca_resolution_minutes = step_minutes`

**Versioning** (ADR-0010): `schema_version`, `engine_version`, `derived_at`.

Esta es la **primera derivación binaria** del sistema. Es la primera fila Derived con doble FK.

### Versionado (ADR-0010)

- `CONJUNCTION_SCHEMA_VERSION = "0.1.0"`.
- `CONJUNCTION_ENGINE_VERSION = "0.1.0"`.

Bump rules:
- PATCH: bug fix sin cambio de output.
- MINOR: nueva capacidad opcional (e.g. refinamiento de TCA → v0.2 = `0.2.0`).
- MAJOR: cambio de signature, unidades o semántica.

### Honestidad sobre incertidumbre (ADR-0000 P2)

Cada `ConjunctionAnalysis` persiste explícitamente:

- `sgp4_uncertainty_baseline_km = 3.0` — error típico SGP4 en época.
- `sgp4_uncertainty_growth_km_per_day = 3.0` — crecimiento típico.
- `tca_resolution_minutes = step_minutes` — granularidad temporal del TCA.

**Lectura operacional**: si `miss_distance_km < 5 km` con `step_minutes = 10`, el resultado es "señal débil dentro del ruido SGP4 y aliasing temporal de 10 minutos". **No** es "conjunción detectada con alta confianza". El caller que ignore estos campos está usando mal el sistema.

### Criterios de aceptación v0.1

1. ADR-0016 aceptado.
2. `ConjunctionAnalysis` Pydantic frozen + `analyze_pairwise_conjunction()` puro.
3. CLI: `orbital-sentinel conjunction <norad_a> <norad_b> --from --to --step`.
4. Tests verificables:
   - Mismo objeto contra sí mismo → `miss_distance` ≈ 0.
   - Dos objetos distintos en órbitas separadas → `miss_distance` realista.
   - TCA cae dentro de la ventana.
   - Provenance completo para ambos objetos.
   - Determinismo bit-exacto en mismo entorno.
   - Validación defensiva (step ≤ 0, ventana inversa, NORAD ausente).
   - Régimen de precisión declarado en cada salida.
5. 197 tests previos siguen verdes.

### Camino a versiones posteriores

Cada bump tendrá su propio ADR. **No** este ADR.

- **v0.2** (MINOR): refinamiento de TCA por bisección en el bracket `[t_{k-1}, t_{k+1}]`. `tca_resolution_minutes` pasa de ser "= step_minutes" a "tolerancia del refinamiento".
- **v0.3** (MINOR / MAJOR según API): N-to-N screening con filtro apogeo/perigeo previo.
- **v0.4** (MINOR): persistencia opcional de eventos detectados como capa Derived persistente (primera persistencia de Derived en el proyecto, requiere decisión explícita sobre retención).
- **v1.0**: Pc con modelo de covarianzas explícito. Requiere ADR de covarianzas (no aplica a SGP4 puro, necesita decisión sobre modelo asumido vs CSpOC vs propio).

## Justificación

- **Pairwise primero** porque establece los contratos críticos (modelo de datos binario, provenance doble FK, declaración de régimen de incertidumbre) sin pagar el coste arquitectónico de mass screening.
- **Sin Pc** porque computarlo sin covarianzas honestas es exactamente lo que ADR-0000 P2 prohíbe.
- **Sin persistencia** porque ADR-0006 enmienda 1 estableció el patrón on-demand; persistir eventos detectados es decisión separada con sus propios trade-offs.
- **Sin refinamiento** porque la grid discreta hace explícita su limitación. Refinar añade complejidad sin cambiar el régimen físico (1-3 km de error SGP4 domina cualquier ganancia sub-minuto).

## Consecuencias

**Positivas**
- Primer producto analítico binario funcional.
- Cimiento arquitectónico para v0.2-v1.0 (mass screening, Pc, persistencia).
- Provenance doble FK validada por construcción.
- Régimen de incertidumbre persistido en cada resultado.
- CLI cubre el caso de uso operacional natural ("¿qué pasa entre estos dos objetos en esta ventana?").

**Negativas**
- TCA resolución limitada a `step_minutes`. Documentado en `tca_resolution_minutes`.
- Sin Pc → el caller no obtiene "probabilidad" sobre la que tomar acciones. **Coherente con no-objetivos de ADR-0000** ("no proporcionará recomendaciones operacionales aplicables sin verificación independiente").
- Sin mass screening → el caller debe declarar pares.

**Neutras**
- Persistencia futura es decisión separada.
- Multi-engine en v1.0+ requeriría que `engine_version` capture motor + escalón (e.g. `sgp4+pairwise-v0.1`).

## Alternativas consideradas

### A. Mass screening desde v0.1
**Razón de rechazo:** complejidad prematura. El modelo de datos binario debe validarse en pairwise primero. Saltarse este escalón ata el diseño del modelo de datos a optimizaciones que aún no están justificadas.

### B. Incluir Pc en v0.1
**Razón de rechazo:** requiere covarianzas que SGP4 no entrega. Asumir covarianzas estándar viola ADR-0000 P2.

### C. Persistir resultados desde v0.1
**Razón de rechazo:** prematuro. v0.1 es exploratorio; persistir antes de saber qué retener contradice el principio de cierre antes de expansión.

### D. Refinamiento de TCA por bisección desde v0.1
**Razón de rechazo:** la incertidumbre física (1-3 km SGP4) domina sobre la mejora temporal sub-minuto. Refinamiento es valor marginal en v0.1; será valioso en v0.2 cuando se valide que la base es estable.

### E. Conversión de marco TEME → ECI antes de calcular distancia
**Razón de rechazo:** TEME es ortonormal; la distancia euclidiana en TEME es físicamente correcta. Conversión añade dependencia (skyfield o astropy) sin cambiar el número.

## Alineación con ADR-0000

- **Refuerza P1, P4**: determinismo y reproducibilidad mantenidos.
- **Refuerza P2**: régimen de precisión declarado en cada resultado.
- **Refuerza P3, P8**: sin red, sin coste, sin persistencia obligatoria.
- **Compatible con no-objetivos**: no se prometen recomendaciones operacionales de evitación de colisión.
- **Sin tensiones.**

## Referencias

- ADR-0000 Fase 2.
- ADR-0014 enmienda 1 (F6 precisión SGP4 como riesgo aceptado).
- Vallado, D. A. (2013), *Fundamentals of Astrodynamics and Applications*, capítulo 10 (análisis de conjunción).

---

## Historial de enmiendas

*Sin enmiendas a fecha de aceptación.*
