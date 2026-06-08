# ADR-0023: Pass prediction v0.1 (observer-from-Earth)

**Estado:** Aceptado
**Fecha:** 2026-06-06
**Autor:** Orbital Sentinel
**Supersede a:** ninguno
**Relacionado con:** ADR-0000 (P2, P3, P7, P8), ADR-0002 enmienda 1, ADR-0005, ADR-0006 enmienda 1, ADR-0010, ADR-0014, ADR-0017

---

## Contexto

Tras Fase 1 (propagación + groundtrack 2D) y Fase 2 cerrada (conjunciones + Pc), el sistema sabe responder preguntas internas del catálogo pero ninguna pregunta del operador en el mundo real: *¿cuándo veo este satélite desde aquí?*, *¿a qué azimut sale, a qué elevación culmina?*, *¿cuántos pases útiles tendré esta noche?*

La capacidad ya está físicamente latente: `Sgp4Propagator` produce posición TEME, `propagation/frames.py` (extraído en Fase 1 preparatoria de este ADR) rota TEME→ECEF con GMST IAU 1982. Falta cerrar ECEF → topocéntrico ENU sobre un observador geográfico y refinar AOS / LOS / culminación con el mismo patrón de bisección que ADR-0017 estableció para el TCA de conjunciones.

## Decisión

Crear un nuevo módulo analítico `analytics/passes/` que implementa predicción de pases visibles para Fase 1 observer-centric.

### API pública

```python
def predict_passes(
    element: OrbitalElement,
    snapshot: TLESnapshot,
    *,
    observer_lat_deg: float,
    observer_lon_deg: float,
    observer_alt_m: float,
    window_start: datetime,
    window_end: datetime,
    step_minutes: float,
    min_elevation_deg: float = 0.0,
    aos_los_tolerance_seconds: float = 1.0,
    clock: Callable[[], datetime] | None = None,
) -> PassPrediction
```

### Modelo de datos

`PassPrediction` (resultado completo): identidad observador + sat, provenance binaria FK Raw→Normalized, ventana, lista de `Pass`, **5 honesty fields** (`frame_model`, `gmst_model`, `aos_los_resolution_seconds`, `culmination_method`, `sgp4_uncertainty_*`), versioning ADR-0010.

`Pass` (pase individual): `aos_time`, `culmination_time`, `los_time`, `aos_was_refined`, `los_was_refined`, `partial_aos`, `partial_los`, `duration_seconds`, `max_elevation_deg`, `aos_azimuth_deg`, `culmination_azimuth_deg`, `los_azimuth_deg`.

### Modelo físico declarado (v0.1)

1. **Tierra esférica** con `EARTH_RADIUS_KM = 6371.0`.
2. **Altitud del observador** se suma radialmente al radio terrestre.
3. **Marco TEME→ECEF**: rotación Z usando GMST IAU 1982. Sin polar motion.
4. **UT1 ≈ UTC con cota IERS**: `|DUT1| ≤ 0.9 s` ⇒ error angular GMST ≤ 6.6e-5 rad ≈ 13.5 arcsec ⇒ ≈ 0.42 km ECEF en el ecuador ⇒ < 15 % del régimen SGP4 baseline declarado en ADR-0014 (~3 km). Encodeado en `GMST_MODEL_NAME = "iau_1982_ut1_equals_utc_v1"`.
5. **Topocéntrico ENU**: azimuth desde Norte hacia Este, dominio `[0°, 360°)`.
6. **Elevación geocéntrica** (idéntica a geodésica bajo esfera).

### Rangos de entrada válidos (enmienda 3)

| Parámetro | Rango |
|-----------|-------|
| `observer_lat_deg` | `[-90.0, 90.0]` |
| `observer_lon_deg` | `[-180.0, 180.0]` |
| `observer_alt_m` | `[-11_000.0, 100_000.0]` |

Fuera de rango → `ValueError`.

### Algoritmo

1. Construir grid uniforme `times = [t₀, t₀+step, …, t_end]`.
2. Propagar batch SGP4 → vector de elevaciones topocéntricas.
3. Identificar segmentos `[k_start..k_end]` donde `elev[i] ≥ min_elevation_deg`.
4. Por cada segmento:
   - **AOS**: bisección sobre `f(t)=elev(t)−min_elev` en `[times[k_start−1], times[k_start]]`. Si `k_start=0` → AOS = `window_start`, `partial_aos=True`.
   - **LOS**: bisección análoga; si `k_end=n−1` → LOS = `window_end`, `partial_los=True`.
   - **Culminación**: ajuste parabólico local sobre tres muestras alrededor de `k_max`. Fallback a discreto en bordes de grid o curvatura plana.
   - Azimuts en AOS / culminación / LOS por propagaciones puntuales adicionales.
5. **Filtro de threshold** se aplica solo sobre `elev[i]` en muestras de grid (no se re-evalúa post-refinamiento).

### Versionado inicial (ADR-0010)

| Constante | Valor v0.1 |
|----------|-----------|
| `PASS_PREDICTION_SCHEMA_VERSION` | `0.1.0` |
| `PASS_PREDICTION_ENGINE_VERSION` | `0.1.0` |
| `FRAME_MODEL_NAME` | `spherical_earth_geocentric_topocentric_v1` |
| `GMST_MODEL_NAME` | `iau_1982_ut1_equals_utc_v1` |
| `CULMINATION_METHOD_NAME` | `parabolic_local_fit_v1` |
| `SGP4_UNCERTAINTY_BASELINE_KM` | `3.0` |
| `SGP4_UNCERTAINTY_GROWTH_KM_PER_DAY` | `3.0` |

### CLI

```
orbital-sentinel passes <norad_id>
    --observer LAT,LON,ALT_M
    --from ISO_UTC --to ISO_UTC --step MINUTES
    [--min-elevation DEG]
    [--aos-los-tolerance SEC]
    [--raw-root PATH] [--normalized-root PATH]
```

Salida JSON únicamente (mismo patrón que los 6 subcomandos previos).

## Justificación

1. **Reutiliza primitivas existentes; cero nuevas dependencias.** `Sgp4Propagator`, `propagation/frames.py` (extraído por la Fase 1 preparatoria) y el patrón de bisección sobre cruce por cero (ADR-0017) ya viven en el repo.
2. **Coherente con ADR-0006 enmienda 1** (sin persistencia nueva). Los pases son on-demand puro.
3. **Replica el contrato de honestidad** establecido en ADR-0020: junto al número de elevación viajan 5 assumption fields. El caller que los ignore está usando mal el sistema.
4. **Establece el patrón para Fase 3+**: módulo bajo `analytics/X/`, ADR específico, régimen de precisión declarado, golden master, sin dependencias nuevas. Hacer pases sobre el caso más sencillo congela ese patrón antes de que la complejidad de Fase 3 lo fije por accidente.

## Lo que este ADR NO decide

- **Persistencia de pases.** v0.1 puro on-demand.
- **WGS84 elipsoidal.** v0.1 esférica.
- **Refracción atmosférica.** No modelada.
- **Iluminación / eclipse del satélite.** Movido a ADR-0024.
- **Observer Doppler / range rate.** No emitido.
- **Pase desde el satélite.** v0.1 solo "observer-from-Earth".
- **Pases sub-grid.** Un pase cuya duración total sobre `min_elevation_deg` es inferior a `step_minutes` puede no detectarse si su peak cae entre dos muestras. La detección de pases es solo tan fina como el grid declarado.
- **Multi-satélite / scan / ranking / conflictos.** Movido a ADR-0025.

## Consecuencias

### Positivas

- Primer comando del sistema que responde una pregunta operativa real.
- Reutiliza al 100 % la rotación TEME→ECEF y GMST ya validados.
- Cero dependencias nuevas.
- Verificable contra fuentes externas independientes (NASA Spot-the-Station, Heavens-Above) sin red en runtime.
- Establece el patrón "analytics submodule + ADR + golden master + 5 honesty fields" para Fase 3+.

### Negativas

- Nueva superficie pública (CLI subcommand) que mantener.
- Refactor preparatorio movió `gmst_iau_1982`, `teme_to_ecef` y `GMST_MODEL_NAME` a `propagation/frames.py`. Cambio mecánico, cero impacto semántico, alias preservado en `orchestration/groundtrack.py`.

### Neutras

- v0.1 esférica es deliberadamente honesta: el bias vs WGS84 está dominado por la incertidumbre SGP4 (~3 km).

## Alternativas consideradas

### A. WGS84 + nutación + polar motion completos
Rechazo: complejidad cuya reducción de error queda sepultada bajo la incertidumbre SGP4. ADR-0000 P3 + YAGNI.

### B. Skyfield como dependencia
Rechazo: viola P3 y "stdlib + dependencias declaradas en ADR". Sus modelos de mayor precisión quedan anulados por la incertidumbre SGP4 ya declarada.

### C. Implementarlo en `orchestration/` directamente
Rechazo: `analytics/` es la plana correcta (ADR-0002). `groundtrack.py` está en `orchestration/` porque produce PNG; pases produce JSON.

### D. Persistir pases como tabla Derived
Rechazo: YAGNI. On-demand cumple.

## Alineación con ADR-0000

- **Refuerza P2**: 5 assumption fields obligatorios.
- **Refuerza P3**: stdlib only, cero dependencias.
- **Refuerza P7**: no introduce fuente nueva.
- **Refuerza P8**: cero red, cero servicios externos.
- **Compatible con P1/P4**: provenance FK + versioning + determinismo total.
- **Sin tensiones.**

## Referencias

- Vallado, D. (2008). *Revisiting Spacetrack Report #3.* §3.5 (TEME), §3.7 (GMST).
- Montenbruck & Gill (2000). *Satellite Orbits.* §5.3, §6.1.
- ADR-0017 (patrón de bisección sobre cruce por cero).
- ADR-0020 (patrón de honesty fields).

---

## Historial de enmiendas

### Enmienda 1 — Renombrado `tca` → `culmination`
TCA proviene del dominio de conjunciones (mínima distancia entre dos objetos). En pases la magnitud relevante es la máxima elevación sobre el horizonte, que en general no coincide con el mínimo range. Renombrado de `tca_time → culmination_time`, `tca_azimuth_deg → culmination_azimuth_deg`, `tca_method → culmination_method`, `TCA_METHOD_NAME → CULMINATION_METHOD_NAME`. Patrón de bisección/parábola idéntico.

### Enmienda 2 — Test GEO desde 88°N
La hipótesis original "70°N no ve GEO" era geométricamente incorrecta (a φ=70°, cos γ = 0.342 > R⊕/r_GEO = 0.1513, GEO visible). El límite geométrico real es φ ≥ arccos(R⊕/r_GEO) ≈ 81.3°. Test corregido a observador a 88°N.

### Enmienda 3 — Validación de rangos del observador
Rangos válidos declarados explícitamente: lat ∈ [-90, 90], lon ∈ [-180, 180], alt_m ∈ [-11_000, 100_000]. Validación temprana en `predict_passes` y en el parser CLI.

### Enmienda 4 — Cuantificación formal UT1 ≈ UTC
La cota IERS `|DUT1| ≤ 0.9 s` se traduce en un error angular máximo de 13.5 arcsec, < 15 % del régimen SGP4. El identificador `GMST_MODEL_NAME = "iau_1982_ut1_equals_utc_v1"` encodea la asunción machine-readable.

### Enmienda 5 — Pases rasantes y sub-grid
Política declarada en §"Lo que este ADR NO decide": un pase cuya duración sobre threshold es inferior a `step_minutes` puede no detectarse. El filtro de threshold se aplica solo en muestras de grid (no se re-evalúa post-refinamiento), por lo que la parábola puede interpolar un máximo marginalmente sub-threshold y el pase se reporta honestamente.
