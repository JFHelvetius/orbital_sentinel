# ADR-0024: Solar geometry primitives v0.1

**Estado:** Aceptado
**Fecha:** 2026-06-06
**Autor:** Orbital Sentinel
**Supersede a:** ninguno
**Relacionado con:** ADR-0000 (P2, P3, P7, P8), ADR-0002 enmienda 1, ADR-0014, ADR-0020, ADR-0023

---

## Contexto

ADR-0023 cerró pass prediction *geométrica*: un pase se reporta si el satélite cruza un umbral de elevación sobre el observador. Para que el sistema responda preguntas operacionales realistas ("¿pases útiles esta noche?", "¿es observable visualmente?") falta una primitiva física: la posición del Sol.

Dos preguntas no resueltas por ADR-0023:

1. ¿Está el observador en oscuridad suficiente (twilight o noche) para observar el pase?
2. ¿Está el satélite iluminado por el Sol o está dentro de la sombra terrestre (eclipse)?

Sin esas dos primitivas, el sistema reporta pases geométricos pero no pases observables. Este ADR introduce el módulo `analytics/solar/` que cierra esa brecha **sin nuevas dependencias** y bajo el patrón de honestidad de ADR-0020.

## Decisión

Crear el módulo `analytics/solar/` con tres primitivas puras:

### API pública

```python
def sun_position_eci(when: datetime) -> tuple[float, float, float]
    """Posición del Sol en ECI ~J2000 [km] (analytical low-precision)."""

def solar_context_at(
    observer_lat_deg: float,
    observer_lon_deg: float,
    observer_alt_m: float,
    when: datetime,
) -> SolarContext
    """Contexto solar completo (sun elevation, twilight) en un instante."""

def is_satellite_illuminated(
    sat_position_eci_km: tuple[float, float, float],
    when: datetime,
) -> bool
    """True si el satélite está fuera de la sombra cilíndrica terrestre."""
```

### Modelo de datos

`SolarContext` (frozen, extra="forbid"):

```python
when: AwareDatetime
observer_lat_deg, observer_lon_deg, observer_alt_m: float
sun_elevation_deg: float          # geocéntrica/topocéntrica idénticas bajo esfera
sun_azimuth_deg: float            # [0, 360)
twilight_phase: TwilightPhase     # "day" | "civil" | "nautical" | "astronomical" | "night"
# Honesty (ADR-0020 pattern)
solar_position_model: str         # "vallado_2008_low_precision_v1"
atmospheric_refraction_assumed_zero: bool  # True en v0.1
valid_date_range_iso: str         # "1950-01-01/2050-12-31"
shadow_model: str                 # "cylindrical_earth_shadow_v1" (informativo)
# Versioning (ADR-0010)
schema_version: str               # "0.1.0"
engine_version: str               # "0.1.0"
derived_at: AwareDatetime
```

`TwilightPhase` como `StrEnum` con valores literales declarados.

### Modelo físico declarado

1. **Posición solar**: fórmula analítica low-precision Vallado §5.1 (precision ~0.01° angular, ~600 km en 1 UA). Cero dependencias externas.
2. **Marco**: ECI ~J2000 (el resultado de Vallado low-precision). La diferencia con TEME a la precisión declarada es sub-arcsec, despreciable.
3. **Twilight thresholds**: convención USNO/IAU estándar:
   - `sun_el ≥ 0°` → `"day"`
   - `-6° ≤ sun_el < 0°` → `"civil"`
   - `-12° ≤ sun_el < -6°` → `"nautical"`
   - `-18° ≤ sun_el < -12°` → `"astronomical"`
   - `sun_el < -18°` → `"night"`
4. **Sin refracción atmosférica** en v0.1 (declarado).
5. **Sombra cilíndrica**: satélite iluminado si `sat·sun_hat > 0` (lado solar) OR `|sat_⊥| > R⊕` (proyección perpendicular fuera del cilindro de sombra).
6. **Rango temporal válido**: `1950-01-01` a `2050-12-31`. Fuera de rango → `ValueError`. La fórmula low-precision acumula error secular post-2050.

### Identificadores machine-readable

| Constante | Valor v0.1 |
|----------|-----------|
| `SOLAR_GEOMETRY_SCHEMA_VERSION` | `0.1.0` |
| `SOLAR_GEOMETRY_ENGINE_VERSION` | `0.1.0` |
| `SOLAR_POSITION_MODEL_NAME` | `vallado_2008_low_precision_v1` |
| `SHADOW_MODEL_NAME` | `cylindrical_earth_shadow_v1` |
| `VALID_DATE_RANGE_ISO` | `1950-01-01/2050-12-31` |

### No CLI propio

ADR-0024 no añade subcomandos CLI. Su valor es como primitiva consumida por ADR-0025 (filtro `useful_pass`) y por consumidores futuros. Una posible consulta puntual `orbital-sentinel sun` se difiere a ADR específico si se justifica.

## Justificación

1. **Cierra la brecha "geométrico vs útil"** sin introducir Skyfield o dependencias externas.
2. **Patrón ADR-0020**: cada output declara su modelo, su asunción de refracción, su rango válido. El número de elevación solar nunca viaja solo.
3. **Cero coste recurrente** (P3): stdlib + math; las primitivas son evaluadas on-demand.
4. **Reutiliza geometría existente**: `observer_to_ecef`, `ecef_to_enu`, `enu_to_elevation_azimuth` de ADR-0023. Cero duplicación.

## Lo que este ADR NO decide

- **Posición lunar.** Sin caso de uso. ADR posterior si emerge.
- **Posición planetaria.** Idem.
- **Modelo de sombra cónica** (umbra/penumbra). v0.1 cilíndrico; error de entrada/salida de eclipse ~10s. Acotado, declarado.
- **Refracción atmosférica.** Defer; no afecta las preguntas operacionales primarias.
- **Persistencia de contexto solar.** On-demand.
- **CLI subcomando independiente.** Defer.

## Consecuencias

### Positivas

- Habilita ADR-0025 (useful pass filter) sin ulteriores ADRs intermedios.
- Cero dependencias nuevas.
- Verificable contra valores USNO publicados sin red.

### Negativas

- Una nueva superficie pública (3 funciones + 1 modelo + 5 constantes) que mantener.

### Neutras

- v0.1 explícitamente low-precision. El error angular ~0.01° está despreciablemente por debajo del régimen SGP4 (~0.17° a 1000 km de range), pero el identificador `solar_position_model` permitirá distinguir cuando un v0.2 de mayor precisión se introduzca.

## Alternativas consideradas

### A. Skyfield + JPL DE421
Rechazo: dependencia + ephemerides ~10 MB. Precisión sobrante al régimen declarado.

### B. astropy
Rechazo: dependencia masiva. P3 lo prohíbe sin justificación extraordinaria.

### C. Modelo sombra cónica desde v0.1
Rechazo: complejidad sin valor visible bajo régimen SGP4. Enmienda futura cuando se justifique.

### D. Posición lunar incluida desde v0.1
Rechazo: YAGNI. ADR específico cuando emerja necesidad.

## Alineación con ADR-0000

- **Refuerza P2**: 4 honesty fields (`solar_position_model`, `atmospheric_refraction_assumed_zero`, `valid_date_range_iso`, `shadow_model`).
- **Refuerza P3**: stdlib only.
- **Refuerza P7/P8**: sin red, sin servicios externos.
- **Sin tensiones.**

## Referencias

- Vallado, D. (2008). *Fundamentals of Astrodynamics and Applications.* §5.1 "Low precision sun ephemeris".
- Montenbruck & Gill (2000). *Satellite Orbits.* §3.4 (sun ephemeris), §3.5 (shadow models).
- USNO Astronomical Almanac (twilight definitions).

---

## Historial de enmiendas

*Sin enmiendas a fecha de aceptación.*
