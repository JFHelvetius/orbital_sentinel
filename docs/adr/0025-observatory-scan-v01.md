# ADR-0025: Observatory scan v0.1 (multi-satellite aggregation)

**Estado:** Aceptado
**Fecha:** 2026-06-06
**Autor:** Orbital Sentinel
**Supersede a:** ninguno
**Relacionado con:** ADR-0000 (P2, P3, P7, P8), ADR-0002 enmienda 1, ADR-0010, ADR-0018, ADR-0020, ADR-0023, ADR-0024

---

## Contexto

ADR-0023 entrega pass prediction para **un satélite**. ADR-0024 entrega el contexto solar para clasificar un pase como observable. Falta la capa de agregación que responda las preguntas operacionales:

- *¿Cuántos pases útiles tendré esta noche?*
- *¿Qué satélites son observables desde mi ubicación en una ventana?*
- *¿Qué pases entran en conflicto (solapamiento temporal)?*
- *¿Cuál es el mejor pase por criterio (elevación máxima, duración)?*

Este ADR cierra la fase observer-centric agregando pases sobre N satélites, aplicando el filtro `useful_pass` (combinación de twilight + illumination + min_elevation) y emitiendo rankings + conflictos.

## Decisión

Crear `analytics/observatory/` con tres componentes:

### API pública

```python
def scan_observatory(
    elements_and_snapshots: Sequence[tuple[OrbitalElement, TLESnapshot]],
    *,
    observer_lat_deg: float,
    observer_lon_deg: float,
    observer_alt_m: float,
    window_start: datetime,
    window_end: datetime,
    step_minutes: float,
    min_elevation_deg: float = 10.0,
    useful_pass_filter: UsefulPassFilter | None = None,
    max_satellites: int = 5000,
    clock: Callable[[], datetime] | None = None,
) -> ObservatoryScan

def rank_passes(
    scan: ObservatoryScan,
    *,
    criterion: RankingCriterion,
    limit: int | None = None,
) -> list[RankedPass]

def detect_pass_conflicts(
    scan: ObservatoryScan,
    *,
    overlap_threshold_seconds: float = 0.0,
) -> list[PassConflict]
```

### Modelos de datos

`UsefulPassFilter` (frozen, extra="forbid") declara la combinación de criterios:

```python
require_observer_in_twilight_or_darker: bool = True
minimum_twilight_phase: TwilightPhase = TwilightPhase.CIVIL
require_satellite_illuminated: bool = True
shadow_model: str = "cylindrical_earth_shadow_v1"
useful_pass_filter_version: str = "0.1.0"
```

`SatellitePasses`:
```python
norad_cat_id: int
object_name: str | None
element_content_hash_source: str
element_tle_index: int
element_tle_content_hash: str
passes: list[Pass]                   # de ADR-0023
n_passes: int
n_useful_passes: int                 # tras aplicar UsefulPassFilter
```

`ObservatoryScan`:
```python
# Identity
observer_lat_deg, observer_lon_deg, observer_alt_m: float
window_start, window_end: AwareDatetime
step_minutes: float
min_elevation_deg: float
# Counts auditables
n_satellites_input, n_satellites_visible_window, n_satellites_skipped: int
n_passes_total, n_useful_passes_total: int
# Per-sat
satellites: list[SatellitePasses]
# Honesty + versioning
useful_pass_filter: UsefulPassFilter
frame_model, gmst_model, solar_position_model, shadow_model: str
schema_version, engine_version: str
derived_at: AwareDatetime
```

`RankingCriterion` como `StrEnum`:
- `MAX_ELEVATION`
- `DURATION`
- `EARLIEST`
- `LATEST`

`RankedPass`: tupla pasa + norad + criterion_value + rank.

`PassConflict`:
```python
norad_a, norad_b: int
overlap_start, overlap_end: AwareDatetime
overlap_seconds: float
overlap_definition: str             # "any_overlap_v1"
```

### Algoritmo

1. **Pre-filtro de visibilidad geométrica** (defensivo, análogo a ADR-0018 apogee/perigee):
   para observador a latitud φ_obs y satélite de inclinación i con altitud h:
   `|φ_obs| ≤ max(i, 180−i) + arccos(R⊕/(R⊕+h)) + margin(5°)`
   Si no se cumple, satellite se marca `skipped_geometric_unreachable` (no se propaga).
2. **Por cada satélite superviviente**: invocar `predict_passes` (ADR-0023).
3. **Aplicar `useful_pass_filter`** a cada `Pass`:
   - Si `require_observer_in_twilight_or_darker`: evaluar `solar_context_at(observer, pass.culmination_time)` y aceptar solo si `twilight_phase` ≤ `minimum_twilight_phase` (orden: day > civil > nautical > astronomical > night).
   - Si `require_satellite_illuminated`: evaluar `is_satellite_illuminated(sat_at_culmination, culmination_time)` y aceptar solo si True.
4. **Cap defensivo**: `max_satellites` rechaza scans con N > cap.
5. **Determinismo**: orden estable de `satellites` por NORAD ascendente; pases por `aos_time`.

### Sin persistencia

`ObservatoryScan` es on-demand puro (mismo régimen que `PassPrediction`). ADR-0006 enmienda 1 preservado.

### CLI

Tres nuevos subcomandos:

```
orbital-sentinel scan
    --observer LAT,LON,ALT_M
    --norad-ids ID1,ID2,...
    --from ISO_UTC --to ISO_UTC --step MINUTES
    [--min-elevation DEG]
    [--require-twilight {civil|nautical|astronomical|night}]
    [--require-illuminated]
    [--max-satellites N]
    [--raw-root PATH] [--normalized-root PATH]

orbital-sentinel best
    [demás flags compartidos con scan]
    --criterion {max_elevation|duration|earliest|latest}
    [--limit N]

orbital-sentinel conflicts
    [demás flags compartidos con scan]
    [--overlap-threshold-seconds N]
```

Salida JSON únicamente. Mismo patrón que los 7 subcomandos previos.

### Versionado

| Constante | v0.1 |
|----------|------|
| `OBSERVATORY_SCAN_SCHEMA_VERSION` | `0.1.0` |
| `OBSERVATORY_SCAN_ENGINE_VERSION` | `0.1.0` |
| `USEFUL_PASS_FILTER_VERSION` | `0.1.0` |
| `MAX_SATELLITES_DEFAULT` | `5000` |
| `OVERLAP_DEFINITION_NAME` | `any_overlap_v1` |

## Justificación

1. **Cierra la fase observer-centric** completa. Después de este ADR el operador puede pedir "¿qué veo esta noche desde aquí?" y obtener respuesta operativa.
2. **Cero matemática nueva**: pura agregación + composición de `predict_passes` + `solar_context_at` + `is_satellite_illuminated`.
3. **Patrón ADR-0018 reusado** (apogee/perigee filter): pre-filtro O(1) por satélite reduce el bottleneck SGP4.
4. **ADR-0020 honesty preservado**: cada `ObservatoryScan` declara `useful_pass_filter`, todos los modelos físicos heredados, y versioning ADR-0010.

## Lo que este ADR NO decide

- **Persistencia de scans.** On-demand.
- **Doppler / range-rate por pase.** Pendiente futuro ADR.
- **Multi-observador / observer ranking.** Asimétrico; sin caso de uso inmediato.
- **Conflictos triples o más.** v0.1 solo pares.
- **Definición de conflicto = solapamiento parcial mínimo.** v0.1 `any_overlap_v1`; otras definiciones (`min_50_percent_v1`) en futuras enmiendas.
- **Compactación / catálogo histórico.** Out of scope.

## Consecuencias

### Positivas

- Última pieza de Observatory Layer v1.
- Cero dependencias nuevas.
- Pre-filtro hace operacional escanear cientos a miles de NORAD IDs.

### Negativas

- Tres nuevos subcomandos CLI que mantener (`scan`, `best`, `conflicts`).
- N×M complejidad en propagación (N sats × M grid points). Mitigado por pre-filtro + `max_satellites`.

### Neutras

- El criterio "útil" es opinionado. Patrón ADR-0020: el caller declara el filtro, el sistema lo aplica y lo reporta literal.

## Alternativas consideradas

### A. Persistir scans como tabla Derived
Rechazo: YAGNI. On-demand cumple. ADR específico cuando emerja necesidad.

### B. Multi-observador (varios sitios de observación a la vez)
Rechazo: asimétrico vs caso típico. ADR futuro si se justifica.

### C. Sin pre-filtro de visibilidad
Rechazo: escanear 10k sats sin pre-filtro = bottleneck SGP4 dominante.

### D. Definición compleja de conflicto (overlap percentage)
Rechazo: v0.1 simplest-thing-that-works. Enmienda futura si la realidad operacional lo justifica.

## Alineación con ADR-0000

- **Refuerza P2**: cada `ObservatoryScan` declara filtro + 4 modelos físicos heredados.
- **Refuerza P3**: stdlib only.
- **Refuerza P7/P8**: sin red, sin servicios externos.
- **Sin tensiones.**

## Referencias

- ADR-0018 (patrón de pre-filtro geométrico O(1)).
- ADR-0023 (`predict_passes`).
- ADR-0024 (`solar_context_at`, `is_satellite_illuminated`).

---

## Historial de enmiendas

*Sin enmiendas a fecha de aceptación.*
