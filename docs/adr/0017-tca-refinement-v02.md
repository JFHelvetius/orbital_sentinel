# ADR-0017: Refinamiento de TCA por bisección — Pairwise conjunction v0.2

**Estado:** Aceptado
**Fecha:** 2026-06-06
**Autor:** Orbital Sentinel
**Supersede a:** ninguno
**Relacionado con:** ADR-0010 (versioning), ADR-0016 (conjunction v0.1)

---

## Contexto

ADR-0016 v0.1 entregó análisis pairwise con **TCA discreto**: el instante de la grid uniforme con mínima distancia. La resolución de TCA está limitada por `step_minutes`. Para `step_minutes = 5`, la TCA podría estar hasta 2.5 minutos lejos del momento real del closest approach físico.

v0.2 introduce **refinamiento por bisección** dentro del bracket `[t_{k-1}, t_{k+1}]` alrededor del mínimo discreto.

## Decisión

### Algoritmo

En el TCA exacto, la derivada de la distancia al cuadrado se anula:

```
d(d²)/dt = 2 · (r_a - r_b) · (v_a - v_b) = 0
```

Definimos:

```
f(t) := (r_a(t) - r_b(t)) · (v_a(t) - v_b(t))
```

Cerca del mínimo discreto `t_k`:

- `f(t_{k-1}) < 0` (objetos aún aproximándose).
- `f(t_{k+1}) > 0` (objetos ya alejándose).

Por tanto existe `t* ∈ [t_{k-1}, t_{k+1}]` con `f(t*) = 0`. Bisección hasta tolerancia.

### Parámetros

- `TCA_REFINEMENT_TOLERANCE_SECONDS = 1.0` (constante del módulo, no expuesta en CLI).
- ~9 iteraciones para `step_minutes = 5` (bracket de 10 min, tolerancia 1 s).
- Cada iteración: 2 llamadas a SGP4 (objetos A y B en el midpoint). Coste total < 1 ms.

### Edge cases (todos fallback al TCA discreto)

1. `min_idx == 0` o `min_idx == n_samples - 1`: mínimo en borde de la ventana; no hay bracket interno. Resultado: `tca_was_refined = False`, `tca_resolution_minutes = step_minutes`.
2. `f(t_{k-1}) * f(t_{k+1}) > 0`: f no cambia de signo en el bracket (caso degenerado, e.g. distancia casi constante por orbitas paralelas, o ruido numérico). Fallback al discreto.
3. **Mismo objeto** A vs A: distancia idénticamente 0; min_idx queda en el primer índice. Cae en el edge case 1 por construcción.

El fallback es honesto: si el refinamiento no puede aplicarse de forma fiable, devolvemos lo mejor que tenemos (discreto) y lo señalamos vía `tca_was_refined = False`.

### Cambios al modelo `ConjunctionAnalysis`

**Campo nuevo:**

```python
tca_was_refined: bool = Field(
    default=False,
    description="True si TCA refinado por bisección; False si está al borde o el bracket es degenerado.",
)
```

**Campo con semántica ajustada:**

`tca_resolution_minutes`:
- v0.1: siempre `= step_minutes`.
- v0.2: `= TCA_REFINEMENT_TOLERANCE_SECONDS / 60.0` cuando `tca_was_refined = True`; `= step_minutes` cuando `tca_was_refined = False`.

Lectura honesta: `tca_resolution_minutes` siempre dice cuánta precisión tiene el TCA reportado. El nuevo `tca_was_refined` desambigua el modo.

### Versionado (ADR-0010)

| Constante | v0.1 | v0.2 | Tipo |
|-----------|------|------|------|
| `CONJUNCTION_SCHEMA_VERSION` | `0.1.0` | `0.2.0` | MINOR (campo nuevo backward-compatible con default) |
| `CONJUNCTION_ENGINE_VERSION` | `0.1.0` | `0.2.0` | MINOR (capacidad nueva sin romper outputs anteriores) |

Compatibility per ADR-0010:
- **Reader v0.1 leyendo data v0.2**: Pydantic `extra="forbid"` actualmente rechaza campo desconocido. **Sin tensión operacional** porque `ConjunctionAnalysis` no se persiste (ADR-0016 enmienda implícita: on-demand puro). La promesa forward-compatible de ADR-0010 aplica cuando haya persistencia; se materializará entonces con un reader version-aware o `extra="ignore"`.
- **Reader v0.2 leyendo data v0.1**: `tca_was_refined` aplica default `False`. Funciona.

### API

```python
def analyze_pairwise_conjunction(
    element_a, snapshot_a,
    element_b, snapshot_b,
    *,
    window_start, window_end, step_minutes,
    refine_tca: bool = True,                      # nuevo
    refinement_tolerance_seconds: float = 1.0,    # nuevo
    clock=None,
) -> ConjunctionAnalysis:
```

`refine_tca=False` reproduce comportamiento v0.1 exacto. Útil para tests de regresión y para casos en los que el usuario quiera grids gruesas sin refinamiento.

CLI sin cambios: refinamiento siempre activo (default `True`). No exponemos `--no-refine` ni `--refinement-tolerance` para mantener la superficie de CLI estable.

### Criterios de aceptación v0.2

1. ADR-0017 aceptado.
2. `_refine_tca_bisection()` interno; no expuesto.
3. `tca_was_refined: bool` añadido al modelo.
4. Tests verificables:
   - **Refinamiento ON por default**: ISS vs GEO sintético sobre 1 h con step=5 min → `tca_was_refined = True`, `tca_resolution_minutes < 0.02` (1 s = 1/60 min).
   - **Refinamiento opt-out**: `refine_tca=False` → comportamiento v0.1 bit-exacto.
   - **Edge cases**: mismo objeto, n_samples=1, min en borde → `tca_was_refined = False`.
   - **Refined miss ≤ discrete miss** para el mismo caso: el TCA refinado encuentra distancia menor o igual.
   - **Refined TCA dentro del bracket** `[t_{k-1}, t_{k+1}]`.
   - **`engine_version == "0.2.0"`** y `schema_version == "0.2.0"`.
5. 213 tests previos siguen verdes (los de v0.1 con `refine_tca=False` donde sea necesario; ningún test rompe sin opt-out porque mismo-objeto y degenerados no refinan).
6. Smoke test manual: refinamiento real produce TCA distinto del discreto.

### Lo que NO cambia respecto a v0.1

- Mass screening: sigue diferido a v0.3+.
- Pc: sigue diferido a v1.0 con ADR específico de covarianzas.
- Persistencia: sigue diferida a v0.4.
- Provenance doble FK: idéntico.
- `sgp4_uncertainty_baseline_km`, `sgp4_uncertainty_growth_km_per_day`: idénticos (la incertidumbre física SGP4 sigue siendo el límite real; el refinamiento solo elimina la incertidumbre de aliasing temporal).
- API CLI: idéntica.

## Justificación

- **Bisección sobre `f(t) = (r·v)`** es el método más directo para encontrar mínimo de distancia analíticamente. No requiere asumir suavidad cuadrática local (lo cual fitting parabólico sí), funciona en cualquier régimen físico.
- **Tolerancia 1 s** porque la incertidumbre SGP4 baseline (~1-3 km en TEME) es de orden 0.5 s × velocidad relativa típica (~7 km/s) → la resolución temporal útil está alrededor del segundo. Refinar más fino es ruido.
- **Refinamiento always-on con opt-out** porque el coste es <1 ms, el beneficio es real (sub-minuto vs step_minutes), y desactivarlo solo tiene sentido para tests o usos exóticos.
- **Fallback explícito al discreto** en lugar de error o NaN: honestidad. Si el bracket es degenerado, el discreto sigue siendo nuestro mejor estimado.

## Consecuencias

**Positivas**
- TCA resolución pasa de `step_minutes` a ~1 segundo en casos refinables.
- Patrón de versionado MINOR + backward-compatible ejercitado en código real (no solo declarado en ADR-0010).
- `tca_was_refined` da al caller información explícita del modo (caller sigue sin perder honesty si lo ignora).

**Negativas**
- Pequeño aumento de coste computacional (<1 ms por análisis). Trivial.
- Semántica de `tca_resolution_minutes` ahora depende de `tca_was_refined`. Mitigado por la documentación explícita del campo.

**Neutras**
- Cambio en `CONJUNCTION_SCHEMA_VERSION` y `CONJUNCTION_ENGINE_VERSION` a `0.2.0` en cada output.

## Alternativas consideradas

### A. Fitting parabólico en `[d²_{k-1}, d²_k, d²_{k+1}]`
**Razón de rechazo:** asume suavidad cuadrática local; es válido para órbitas suaves pero falla en casos con geometría rápida. Bisección es más general. El coste extra de bisección (2-3 ms vs μs) es trivial.

### B. Newton's method sobre f(t)
**Razón de rechazo:** requiere derivada de f que requiere aceleración relativa. SGP4 no entrega aceleración natural; habría que diferenciar numéricamente. Más complejidad sin mejora real.

### C. Tolerancia más fina (0.1 s o menor)
**Razón de rechazo:** la incertidumbre física SGP4 ya es de orden ~0.5 s. Refinar a 0.1 s es trabajo desperdiciado en ruido.

### D. Tolerancia configurable por CLI
**Razón de rechazo:** scope creep. La superficie de CLI debe mantenerse mínima. Si llega un caso de uso real con tolerancias distintas, se promueve a flag entonces.

### E. Refinamiento opt-in en vez de opt-out
**Razón de rechazo:** v0.2 entrega valor solo si está activo por default. Hacerlo opt-in significa que la mayoría de usuarios siguen en v0.1 efectivamente. El opt-out cubre la necesidad de reproducibilidad de v0.1.

## Alineación con ADR-0000

- **Refuerza P1, P4**: determinismo y reproducibilidad mantenidos (refinamiento es función pura).
- **Refuerza P2**: `tca_was_refined` + `tca_resolution_minutes` siguen dando al caller la información honesta sobre la precisión del TCA reportado.
- **Refuerza P3, P8**: sin red, sin persistencia, sin coste adicional significativo.
- **Sin tensiones.**

## Referencias

- ADR-0016 §"Alcance v0.1".
- ADR-0010 §"Reglas de bump".
- Vallado, D. A. (2013), *Fundamentals of Astrodynamics and Applications*, §10.3 (refinamiento de TCA).

---

## Historial de enmiendas

*Sin enmiendas a fecha de aceptación.*
