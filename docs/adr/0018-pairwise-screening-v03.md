# ADR-0018: N-to-N pairwise screening con filtro apogeo/perigeo — v0.3

**Estado:** Aceptado
**Fecha:** 2026-06-06
**Autor:** Orbital Sentinel
**Supersede a:** ninguno
**Relacionado con:** ADR-0010 (versioning), ADR-0016 (v0.1), ADR-0017 (v0.2)

---

## Contexto

ADR-0016 entregó análisis pairwise entre **un par específico**. ADR-0017 refinó el TCA. La pregunta natural siguiente: dado un **conjunto** de objetos, ¿cuáles pares tienen una conjunción detectable en una ventana?

v0.3 generaliza a **N-to-N screening**: el caller declara una lista de objetos, el sistema analiza todos los pares posibles (con filtro previo opcional) y devuelve los pares cuya miss distance está bajo un umbral.

## Decisión

### Alcance v0.3

- **API**: lista de `(OrbitalElement, TLESnapshot)` + ventana + step + threshold → `ScreeningResult`.
- **O(N²/2) pairs**. Loop serial sin paralelización.
- **Filtro apogeo/perigeo opcional (default ON)** descarta pares cuyas altitudes nunca pueden estar dentro de `threshold_km`.
- Cada par superviviente del filtro se analiza con `analyze_pairwise_conjunction` v0.2 (con refinamiento de TCA).
- **Detección** = `miss_distance_km < threshold_km`.
- **Cap `max_pairs = 5000` por defecto** previene lanzar O(10⁴⁺) accidentalmente.

### Filtro apogeo/perigeo

Para cada `OrbitalElement`, derivamos:

```
n_rad_s = mean_motion · 2π / 86400          # mean motion en rad/s
a_km    = (GM_earth / n_rad_s²)^(1/3)        # semieje mayor en km
perigee = a_km · (1 - eccentricity)         # distancia del centro de la Tierra
apogee  = a_km · (1 + eccentricity)
```

con `GM_EARTH = 398 600.4418 km³/s²`.

Dos objetos pueden conjuntar solo si sus rangos `[perigee, apogee]` solapan con un margen de `threshold_km`. Formalmente:

```
NOT (apogee_a + threshold_km < perigee_b
     OR apogee_b + threshold_km < perigee_a)
```

El filtro **no descarta** pares que sí pueden conjuntar; solo descarta pares que es **imposible** que conjunten dado el régimen de altitudes.

Coste del filtro: O(1) por par. Beneficio: descarta tipicamente >90% en catálogos mixtos LEO+MEO+GEO.

### Cap de seguridad: `max_pairs`

Por defecto **5 000**:

- N = 100 → 4 950 pairs (justo bajo el cap).
- N = 200 → 19 900 pairs (excede; requiere `--max-pairs` explícito).

El cap **se evalúa antes del filtro apogeo/perigeo**: limita la matriz N×N, no la matriz reducida. Esto previene casos donde N enorme genera memoria/tiempo no contemplados aunque muchos pares se filtren después.

Excederlo lanza `ValueError`. Caller que necesite más declara explícitamente.

### `ScreeningResult`

```python
class ScreeningResult(BaseModel):
    window_start, window_end: AwareDatetime
    step_minutes: float
    threshold_km: float
    apogee_perigee_filter_enabled: bool
    refine_tca_enabled: bool

    n_objects: int
    n_pairs_total: int           # n·(n-1)/2
    n_pairs_filtered_out: int    # filtrados por apogeo/perigeo
    n_pairs_screened: int        # analizados con pairwise
    n_detections: int            # miss < threshold

    detections: list[ConjunctionAnalysis]   # ordenadas por miss ASC

    sgp4_uncertainty_baseline_km: float     # honestidad declarada (ADR-0000 P2)
    schema_version: str                     # SCREENING_SCHEMA_VERSION
    engine_version: str                     # SCREENING_ENGINE_VERSION
    derived_at: AwareDatetime
```

Los counts permiten al caller auditar el flujo: cuántos pares totales, cuántos descartó el filtro, cuántos se analizaron, cuántos cumplieron el threshold.

### Versionado (ADR-0010)

| Constante | Valor | Justificación |
|-----------|-------|---------------|
| `SCREENING_SCHEMA_VERSION` | `0.1.0` | Primera versión del modelo `ScreeningResult`. |
| `SCREENING_ENGINE_VERSION` | `0.1.0` | Primera versión del algoritmo N-to-N. |

Las `ConjunctionAnalysis` dentro de `detections` mantienen su propio `engine_version` (actualmente `"0.2.0"` por ADR-0017). Versionado **independiente entre modelos** según ADR-0010.

### CLI

```
orbital-sentinel screen --norad-ids X,Y,Z
                        --from <iso> --to <iso> --step <min>
                        --threshold-km <km>
                        [--no-apogee-perigee-filter]
                        [--max-pairs <N>]
                        [--raw-root PATH] [--normalized-root PATH]
```

Comportamiento:
- Carga el último `OrbitalElement` de cada NORAD ID desde el catálogo Normalized.
- Si algún NORAD no existe en el catálogo, lanza `OrbitalSentinelError` antes de empezar.
- Devuelve JSON con `ScreeningResult` completo (counts + detections ordenadas por miss ASC).

### Exclusiones v0.3 explícitas

- **Smart-sieve** (filtros más sofisticados, e.g. plane-of-orbit intersection geometry). Diferido a v0.5+.
- **Pc** (probability of collision). Sigue diferido a v1.0 con ADR específico de covarianzas.
- **Persistencia de eventos detectados**. Diferida a v0.4.
- **Paralelización** (multiprocessing, threading, asyncio). Loop serial. Cuando coste lo justifique, ADR separado.
- **Carga automática de objetos por dataset** (e.g. "screening all of CelesTrak 'stations'"). El caller declara la lista; la composición desde un dataset es trabajo de orchestration futuro si se necesita.

### Criterios de aceptación v0.3

1. ADR-0018 aceptado.
2. `ScreeningResult` Pydantic frozen con todos los campos especificados.
3. `analyze_pairwise_screening()` puro, sin red, sin persistencia.
4. `_apogee_perigee_km()` y `_possible_conjunction()` helpers internos.
5. CLI: `screen` command end-to-end.
6. Tests verificables:
   - ISS vs GEO sintético → filtro descarta el par, `n_detections = 0`.
   - Mismo objeto duplicado → detección con `miss ≈ 0`.
   - Filtro deshabilitado → todos los pares analizados.
   - Lista vacía / single object → counts triviales, sin detecciones.
   - Threshold ≤ 0 → `ValueError`.
   - Window inversa → `ValueError`.
   - `max_pairs` excedido → `ValueError`.
   - Provenance doble FK preservada en cada detección.
   - Detecciones ordenadas por miss ascendente.
7. 221 tests previos siguen verdes.
8. Smoke test manual: catálogo con ISS + GEO 99999, `--threshold-km 1000` → 1 par total, 1 filtrado por apogeo/perigeo, 0 detecciones; con `--no-apogee-perigee-filter` → 1 par analizado, 0 detecciones.

## Justificación

- **Pairwise como ladrillo** ya validado en v0.1/v0.2; reusarlo es el camino más honesto. No reescribir.
- **Filtro apogeo/perigeo** es la optimización **mínima útil**: O(1) por par, descarta la mayoría en catálogos mixtos. Optimizaciones más sofisticadas (smart-sieve) tienen retorno decreciente y mayor superficie de bugs.
- **Cap explícito** es defensivo: el caller que quiere correr 50k pares debe decirlo explícitamente. Previene el "ups, no quería esto" en CLIs interactivas.
- **Counts en el resultado** son honestidad operacional: el caller ve qué se descartó vs. qué se analizó. Sin esto el resultado parece menos informativo de lo que es.

## Consecuencias

**Positivas**
- Primer producto N-to-N funcional.
- Filtro apogeo/perigeo demostrado en código (no solo planeado).
- Pattern de versionado independiente entre modelos ejercitado en producción.
- CLI cubre el caso de uso típico ("screen estos N objetos en esta ventana").

**Negativas**
- O(N²/2) sigue siendo cuello de botella para N grande. Mitigado por `max_pairs` y filtro.
- Sin Pc → caller no obtiene "probabilidad" (coherente con no-objetivos ADR-0000).

**Neutras**
- Paralelización futura es decisión separada.
- Top-K (devolver solo K detecciones más cercanas) es trabajo de v0.4 si lo justifica un caso real.

## Alternativas consideradas

### A. Sin filtro apogeo/perigeo
**Razón de rechazo:** desperdicia tiempo en pares físicamente imposibles. El filtro es O(1) y elimina la mayoría.

### B. Smart-sieve completo (intersección geométrica de planos orbitales)
**Razón de rechazo:** complejidad alta, retorno decreciente sobre apogeo/perigeo. Si se justifica, ADR posterior.

### C. Mass screening sobre catálogo completo (auto-carga)
**Razón de rechazo:** acopla screening con orchestration de catálogo (cuántos elementos cargar, cómo filtrar por dataset, etc.). Prematuro. v0.3 expone API con lista declarada; orchestration de "screen all" es composición futura.

### D. Paralelización con multiprocessing/threading
**Razón de rechazo:** coste de complejidad alto para v0.3 cuando el cap `max_pairs = 5000` mantiene el tiempo en segundos. Paralelizar cuando haya caso de uso real (>10⁴ pairs).

### E. Top-K en lugar de threshold
**Razón de rechazo:** menos honesto. Threshold dice "estoy interesado en miss < X km"; Top-K dice "dame los K más cercanos aunque ninguno sea de interés operacional". El threshold respeta la semántica del usuario.

## Alineación con ADR-0000

- **Refuerza P1, P4**: determinismo y reproducibilidad mantenidos (función pura).
- **Refuerza P2**: counts + sgp4_uncertainty_baseline_km declaran qué se hizo y cuánta confianza tiene.
- **Refuerza P3, P8**: sin red, sin persistencia, sin coste recurrente.
- **Compatible con no-objetivos**: no se prometen "recomendaciones operacionales aplicables".
- **Sin tensiones.**

## Referencias

- ADR-0016 §"Alcance v0.1".
- ADR-0017 §"Algoritmo" (refinamiento de TCA usado por screening).
- Alfano, S. (2009), *Satellite Conjunction Monte Carlo Analysis*, AAS Astrodynamics Conf.
- Vallado, D. A. (2013), *Fundamentals of Astrodynamics and Applications*, §10.3.

---

## Historial de enmiendas

*Sin enmiendas a fecha de aceptación.*
