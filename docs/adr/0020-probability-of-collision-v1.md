# ADR-0020: Probability of collision (Pc) v1.0 con covarianza TLE-derived declarada

**Estado:** Aceptado
**Fecha:** 2026-06-06
**Autor:** Orbital Sentinel
**Supersede a:** ninguno
**Relacionado con:** ADR-0000 (P2 honestidad sobre incertidumbre), ADR-0010 (versioning), ADR-0014 (SGP4), ADR-0016/17/18/19 (pairwise v0.1-v0.4)

---

## Contexto

ADR-0000 Fase 2 incluye "probabilidad de colisión". Hasta este ADR, hemos **diferido** Pc explícitamente con razón:

- ADR-0014 enmienda 1 (mitigación de red-team F6): la precisión SGP4 está aceptada como riesgo conocido; las salidas deben **declarar su régimen de incertidumbre**.
- ADR-0016 §"Excluido v0.1": Pc requiere covarianzas que SGP4 no entrega; "asumir covarianzas estándar viola ADR-0000 P2".

Este ADR es el **más delicado** del proyecto hasta ahora porque computar Pc requiere asumir covarianzas, y asumirlas mal es exactamente lo que ADR-0000 P2 prohíbe. La solución que aquí se decide es **computar Pc bajo covarianza explícitamente declarada**, no esconder la asunción detrás del número.

## Decisión

### Filosofía: Pc bajo covarianza declarada

**Cada `ConjunctionAnalysis` v1.0 incluye 7 campos nuevos** que describen exactamente bajo qué asunciones se calculó el Pc:

1. `pc`: el valor numérico Pc.
2. `combined_hard_body_radius_km`: R, suma de radios físicos.
3. `covariance_model_name`: identifica el modelo asumido.
4. `covariance_baseline_sigma_km`: σ₀.
5. `covariance_growth_sigma_km_per_day`: α.
6. `combined_sigma_at_tca_km`: σ resultante en el TCA.
7. `pc_method`: identifica el método de Pc.

**Un caller que devuelve solo `pc` sin estos campos viola el contrato del módulo.** El número Pc en aislamiento es deshonesto; con sus 6 campos contextuales es honesto.

Test operacional para verificar P2: ¿podría un lector razonable interpretar el output como "probabilidad operacional aplicable sin verificación independiente"? Si el output incluye `covariance_model_name="tle_isotropic_spherical_v1"` y `combined_sigma_at_tca_km=1.5`, la respuesta es **no**: el lector sabe que el modelo es asumido, no medido. Honestidad operacional preservada.

### Modelo de covarianza: `tle_isotropic_spherical_v1`

Definición formal:

```
σ(Δt_minutes) = σ₀ + α · |Δt_minutes| / 1440
σ_a²(Δt_a) + σ_b²(Δt_b) = σ_combined²(TCA)
```

con:

- `σ₀ = COVARIANCE_BASELINE_SIGMA_KM = 1.0 km` (1-sigma baseline en época).
- `α = COVARIANCE_GROWTH_SIGMA_KM_PER_DAY = 1.0 km/día`.
- Forma: 3D isotropic spherical Gaussian (mismo σ en X, Y, Z; correlaciones cero).

**Esta NO es la covarianza real medida de las observaciones específicas**. Es una **asunción declarada** dentro del rango de "covariance realism" para TLE+SGP4 publicado por Vallado et al. (2008). El proyecto **no valida** la covarianza contra el error real de propagación de los objetos específicos.

Justificación de los valores:

- ADR-0014 enmienda 1 declaró error SGP4 típico "~1–3 km en época, crecimiento ~1–3 km/día". Esos son rangos 3-sigma equivalentes. Para 1-sigma: ~0.3–1 km. Tomamos el extremo conservador (1.0 km) para no subestimar incertidumbre.
- Isotropic spherical es el modelo más simple defensible. No requiere asumir orientación (RIC, TEME, ECI). Es la asunción de **ignorancia máxima** sobre la geometría de la covarianza real.

Versionado: `_v1` en el nombre. Si en el futuro se introduce un modelo más sofisticado (e.g., anisotrópico RIC), será `tle_anisotropic_ric_v1` o similar, persistido en `covariance_model_name`.

### Método Pc: Foster 1992 fast approximation

Para covarianza isotropic spherical, la fórmula reducida:

```
Pc ≈ (R² / 2σ²) · exp(-d² / 2σ²)
```

donde:

- `R = combined_hard_body_radius_km` (default 0).
- `σ = combined_sigma_at_tca_km`.
- `d = miss_distance_km` al TCA.

Esta es la **aproximación rápida** de Foster (1992), válida cuando `R << σ`. Para parámetros típicos:

- `R ~ 5 m = 0.005 km` (satélite mediano).
- `σ ~ 1.4 km` (combinando dos σ ~ 1 km por raíz de la suma de cuadrados).
- `R/σ ~ 0.004`. Bien dentro del régimen de validez.

Si `R/σ > 0.1`, la aproximación pierde precisión. El sistema **no lanza** en ese caso; el caller que pase R grande lo hace bajo su responsabilidad y debe interpretar Pc con escepticismo adicional.

Persistido como `pc_method = "foster_1992_fast_approximation"`.

### Edge cases

- **`R = 0`** (default): `Pc = 0`. Coherente: objetos puntuales no colisionan en sentido físico estricto.
- **`σ = 0`**: degenerado. Devolvemos `Pc = 1.0 if d <= R else 0.0` (caso determinista).
- **`d = 0`** (miss físico exacto): `Pc = R² / 2σ²`, máximo de la fórmula.
- **`d → ∞`**: `Pc → 0` exponencialmente.

### `combined_hard_body_radius_km`

Es un **parámetro del caller**, no del sistema. Default `0.0`. Se acepta como flag CLI `--combined-radius-km KM`.

Sin radio combinado declarado, `Pc = 0`. Esto es intencional: el caller que quiera un Pc no-nulo debe declarar la suma de radios. Sin esa declaración, devolvemos honestamente `0`.

### Versionado (ADR-0010)

| Constante | v anterior | v nueva | Tipo |
|-----------|------------|---------|------|
| `CONJUNCTION_SCHEMA_VERSION` | `0.2.0` | `0.3.0` | MINOR (7 campos nuevos con defaults sensatos) |
| `CONJUNCTION_ENGINE_VERSION` | `0.2.0` | `0.3.0` | MINOR (capacidad nueva: Pc; outputs anteriores no rompen) |
| `PERSISTED_CONJUNCTION_SCHEMA_VERSION` | `0.1.0` | `0.2.0` | MINOR (mismos 7 campos en la fila persistida) |

`SCREENING_*_VERSION`: sin cambio. `ScreeningResult.detections` es `list[ConjunctionAnalysis]`, el cambio se hereda transparentemente.

### Integración con persistencia

ConjunctionDetection v0.2.0 añade los mismos 7 campos. El hash de detección **no cambia su receta**: sigue siendo `sha256(sorted_tle_hashes | window | step | engine_version)`. Como `engine_version` ahora es `"0.3.0"`, detecciones v1.0 tendrán hashes distintos a las v0.2.0 aunque los TLE+window+step sean idénticos. Esto es **correcto**: análisis con motor distinto son artefactos distintos (ADR-0010 coexistencia).

### CLI

- `orbital-sentinel conjunction <a> <b> ... [--combined-radius-km KM]`: añade flag opcional.
- `orbital-sentinel screen ... [--combined-radius-km KM]`: añade flag opcional, se propaga a todas las detecciones del run.

Sin el flag, `combined_radius_km = 0.0` → `Pc = 0` siempre. Decisión deliberada: el caller que quiera Pc significativo declara el radio.

### Exclusiones v1.0 explícitas

- **Múltiples modelos comparativos**. Un modelo, un Pc. Si el caller quiere comparar, ejecuta dos análisis con `engine_version` distintos.
- **Covarianza input del caller**. No aceptamos `--covariance-matrix` desde CLI. La covarianza es del sistema, declarada en `tle_isotropic_spherical_v1`. Sin esto, el caller podría introducir covarianzas optimistas para inflar Pc.
- **Propagación de covarianza a través de SGP4**. Requeriría implementar derivadas de SGP4 (work de investigación). Diferido a v2.0 si se justifica.
- **Comparación contra CDM público** (US Space Force). Útil para validación pero no requerido para v1.0. ADR posterior si se justifica.
- **Time-window de Pc** (integración sobre toda la ventana, no solo el TCA). El método actual computa Pc puntual en TCA. Adecuado para encuentros cortos (régimen estándar SSA).

### Criterios de aceptación v1.0

1. ADR-0020 aceptado.
2. Módulo nuevo `analytics/conjunctions/probability.py` con `sigma_tle_isotropic`, `combined_sigma_at_tca`, `pc_foster_fast`.
3. `ConjunctionAnalysis` v0.3.0 con 7 campos nuevos.
4. `ConjunctionDetection` v0.2.0 con los mismos 7 campos.
5. CLI: `--combined-radius-km` en `conjunction` y `screen`.
6. Tests:
   - `sigma_tle_isotropic(0) = 1.0`.
   - `sigma_tle_isotropic(1 día) = 2.0`.
   - `pc_foster_fast` monotonía: cae con `d`, crece con `R`, decrece con `σ`.
   - `pc_foster_fast(d=0, σ=1, R=0.01) ≈ 0.0001/2 = 5e-5`.
   - `Pc = 0` cuando `R = 0` (default).
   - `Pc ∈ [0, 1]` en todos los casos no degenerados.
   - `covariance_model_name` y `pc_method` persistidos en cada resultado.
   - Round-trip de detección preserva Pc fields.
   - CLI smoke: `conjunction --combined-radius-km 0.01` produce Pc > 0.
7. 267 tests previos siguen verdes (los que asertan `CONJUNCTION_*_VERSION == "0.2.0"` se actualizan a `"0.3.0"`).

## Justificación

- **Covarianza declarada en cada resultado** es la única forma de respetar P2. El número Pc en aislamiento es deshonesto; con su contexto es honesto.
- **Isotropic spherical** es la asunción de **mínima información**: no inventa una geometría de covarianza que no tenemos.
- **Foster fast approximation** es el método más usado en literatura para covarianza isotropic; bien validado.
- **`combined_radius_km` default 0** fuerza al caller a declarar explícitamente cuando quiere Pc no-nulo. Sin esta declaración, devolvemos honestamente "no podemos calcular Pc físicamente significativo".

## Consecuencias

**Positivas**
- Fase 2 cierra según ADR-0000.
- Pattern establecido para futuros productos analíticos con asunciones: persistir TODAS las assumption fields, no solo el número.
- Primer ejercicio real de P2 en un componente que tradicionalmente miente.

**Negativas**
- Caller debe entender el modelo de covarianza para interpretar Pc. Mitigado por documentación + assumption fields.
- Pc por defecto = 0 puede sorprender. Mitigado por mensaje del CLI cuando R=0.

**Neutras**
- Modelo de covarianza simple. Se puede sofisticar con más ADRs.

## Alternativas consideradas

### A. No calcular Pc nunca
**Razón de rechazo:** sería ignorar Fase 2 de ADR-0000. El compromiso es Pc honesto, no no-Pc.

### B. Múltiples modelos de covarianza comparativos
**Razón de rechazo:** scope creep. Un modelo es suficiente para v1.0. Si llega un caso operacional que justifique, ADR posterior.

### C. Covariance input del caller
**Razón de rechazo:** invita a callers a introducir covarianzas optimistas. El sistema **debe** controlar el modelo.

### D. Pc solo cuando R sea explícitamente declarado, error si no
**Razón de rechazo:** rompe API. Default a 0 es más amigable y honesto.

### E. Método Pc exacto (Alfano integral, no Foster approximation)
**Razón de rechazo:** para nuestros valores típicos (R/σ < 0.01), Foster y exacto coinciden a 5-6 dígitos. Coste extra no justificado.

## Alineación con ADR-0000

- **Refuerza P1, P4**: determinismo total (función pura sobre inputs declarados).
- **Refuerza P2**: cada resultado lleva 7 campos que documentan la asunción. Honestidad explícita por construcción.
- **Compatible con no-objetivos**: no se proporcionan "recomendaciones operacionales aplicables sin verificación independiente". Pc bajo covarianza asumida no es operacional.
- **Sin tensiones.**

## Referencias

- Foster, J. L. (1992). *A Parametric Analysis of Orbital Debris Collision Probability and Maneuver Rate for Space Vehicles*. NASA JSC-25898.
- Vallado, D. A., Crawford, P. (2008). *SGP4 Orbit Determination*. AAS/AIAA Astrodynamics Specialist Conf.
- Alfano, S. (2009). *Satellite Conjunction Monte Carlo Analysis*. AAS Astrodynamics Conf.
- ADR-0014 enmienda 1 (régimen de precisión SGP4 declarado).
- ADR-0019 (persistencia de detecciones).

---

## Historial de enmiendas

*Sin enmiendas a fecha de aceptación.*
