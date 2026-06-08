# ADR-0014: Integración de SGP4 como motor de la capa Derived

**Estado:** Aceptado
**Fecha:** 2026-06-03
**Autor:** Orbital Sentinel
**Supersede a:** ninguno
**Relacionado con:** ADR-0005 (SGP4 único motor), ADR-0006 (capas), ADR-0010 (versioning), ADR-0013 (reproducibilidad)

---

## Contexto

- ADR-0005 estableció SGP4 como único propagador de v1 y mencionó una interfaz `Propagator` para no bloquear extensión futura.
- ADR-0006 enmienda 1 estableció que las efemérides **no se materializan por defecto**.
- Hasta este ADR, la capa Derived no tenía implementación. Este ADR define la primera versión: el wrapper SGP4 operacional sobre la capa Normalized.
- El red-team review (F6) aceptó la precisión SGP4 como riesgo conocido; este ADR no la relitiga.

## Decisión

### Librería

Usamos `sgp4` (https://pypi.org/project/sgp4/) — port directo del Fortran de Vallado a Python por Brandon Rhodes. Pinned en `pyproject.toml` con `>=2.20,<3`. La versión exacta vive en `uv.lock` y forma parte del **entorno declarado** (ADR-0013).

### Plano arquitectónico

La propagación vive en el plano 5 `propagation/` (ADR-0002). Importa de Catalog (4), Ingestion (3) y Core (1). **No importa** de Analytics, Agent ni Orchestration.

### Interfaz

Protocol mínimo `Propagator`:

```python
class Propagator(Protocol):
    name: str
    engine_version: str
    def propagate(
        self, element, snapshot, times,
    ) -> list[Ephemeris]: ...
```

Solo `Sgp4Propagator` implementa este Protocol en v1. La interfaz se mantiene para que futuras adiciones (OMM/SP, propagadores numéricos) no requieran refactor de Analytics.

### Modelo de datos: ``Ephemeris``

Cada instancia representa el vector de estado (posición + velocidad) de un objeto en un instante UTC concreto. Campos:

- **Provenance** (FK a Normalized y, transitivamente, a Raw):
  `orbital_element_content_hash_source`, `orbital_element_tle_index`,
  `tle_content_hash`.
- **Identity denormalizada** (para queries hot-path):
  `norad_cat_id`. Esta denormalización es la única excepción a la regla de
  "no contaminación entre capas" de `docs/architecture/layers.md`. Se
  justifica explícitamente: el patrón de query operacional siempre filtra
  por NORAD ID.
- **Evaluation context**: `evaluation_time` (UTC tz-aware), `minutes_from_epoch` (signed offset).
- **State vector TEME**: 6 escalares (km, km/s).
- **Quality**: `sgp4_error_code` (0 OK; 1–7 condiciones anómalas).
- **Versioning**: `schema_version`, `engine_version`, `derived_at`.

Tuplas Python (`position_teme_km`, `velocity_teme_km_s`) se exponen como `@property` de conveniencia.

### Estrategia on-demand

`propagate(element, snapshot, times) → list[Ephemeris]` **no persiste nada**. Devuelve los objetos en memoria; el caller decide qué hacer con ellos. Esto operacionaliza ADR-0006 enmienda 1.

Si en el futuro se introduce caché de ventana corta, será un módulo aparte (e.g. `propagation/cache.py`) con TTL declarado y **fuera del régimen de inmutabilidad** de Derived. No es trabajo de v1.

### Reglas de implementación

1. **Coherencia física TLE↔SGP4.** El wrapper extrae las dos líneas TLE originales desde `snapshot.raw_text` en la posición `element.tle_index`. Pasa las líneas a `Satrec.twoline2rv()`. **Nunca** usa `Satrec.sgp4init()` con campos parseados: cualquier futuro cambio del parser podría introducir desviaciones numéricas; trabajar con las líneas originales lo evita por construcción.

2. **Verificación defensiva pre-propagación.** Antes de instanciar `Satrec`:
   - Comprueba `element.content_hash_source == snapshot.content_hash` (consistencia).
   - Reconstruye `sha256(line1 + "\n" + line2)` y comprueba que coincide con `element.tle_content_hash` (defensa contra corrupción cross-layer).
   - Si `Satrec.error != 0` tras `twoline2rv`, lanza `PropagationError` (TLE estructuralmente no propagable).

3. **Marco de referencia: TEME nativo de SGP4.** Sin conversiones de frame en v1. Cualquier transformación a ECI, ECEF, ITRF, etc., será trabajo de un módulo `propagation/frames.py` futuro con su propio ADR.

4. **Tiempos: `sgp4.api.jday`.** El wrapper convierte `datetime` UTC tz-aware a Julian Date usando la utilidad de la librería. **No implementa conversiones de tiempo a mano**.

5. **Códigos de error de SGP4 preservados, no filtrados.** `Ephemeris.sgp4_error_code` siempre lleva el código exacto que devolvió `sat.sgp4()`. Códigos != 0 **no** lanzan; se delega al caller la política de qué hacer con esos resultados. Coherente con ADR-0000 P2 (honestidad sobre incertidumbre).

### Versionado (ADR-0010)

- `SGP4_PROPAGATOR_VERSION = "0.1.0"`: SemVer del wrapper local. Captura **solo** este módulo.
- `EPHEMERIS_SCHEMA_VERSION = "0.1.0"`: SemVer del esquema de la fila Ephemeris.
- Versión de la librería `sgp4`: parte del entorno declarado (ADR-0013), pinned en `uv.lock`.

Reglas de bump del wrapper:

- **PATCH**: fix sin cambio de outputs (e.g. mejor mensaje de error).
- **MINOR**: nueva capacidad opcional (e.g. conversión de frame en una rama).
- **MAJOR**: cambio de salida observable (e.g. cambio de unidades, cambio de identidad de filas, cambio de cuándo se lanza vs preserva un error).

### Trazabilidad Raw → Normalized → Derived

Cadena de FKs lógicas:

```
tle_snapshots.content_hash
  ↑                                 (Raw)
  │
orbital_elements.content_hash_source
  ↑                                 (Normalized)
  │
ephemeris.orbital_element_content_hash_source
```

Adicionalmente, `ephemeris.tle_content_hash` permite identificar el TLE individual sin pasar por el snapshot fuente (útil para dedup cross-snapshot futuro). `ephemeris.orbital_element_tle_index` permite navegar al bloque exacto del snapshot.

`verify_integrity()` (ADR-0006 / `catalog/integrity.py`) **no se extiende a Derived en v1** porque las efemérides no se materializan. Cuando se introduzca caché o persistencia, ese ADR futuro definirá los invariantes adicionales.

### Estrategia de tests

Cubierta en `tests/unit/test_propagator_sgp4.py` y `tests/unit/test_ephemeris_model.py`:

- **Golden master contra la librería sgp4 directamente.** Construimos `Satrec` con el mismo TLE canónico ISS Vallado 2008, llamamos `sat.sgp4(jd, fr)` y comparamos bit-exacto contra nuestro wrapper. Es la prueba de no-regresión más fuerte: garantiza que nuestro wrapper no introduce desviaciones respecto a la implementación de referencia.
- **Sanidad física.** Para ISS, `|r|` ∈ [6600, 7100] km, `|v|` ∈ [7.4, 7.9] km/s. Detecta errores groseros de unidades o de frame.
- **Determinismo.** Misma entrada → misma salida bit-idéntica (ADR-0013).
- **Trazabilidad.** Cada `Ephemeris` carga `content_hash_source`, `tle_index`, `tle_content_hash`, `norad_cat_id` coherentes con su origen.
- **Versionado.** `engine_version` y `schema_version` materializados en cada output.
- **Validación defensiva**: rechaza element/snapshot inconsistentes, índices fuera de rango, hash mismatch, datetimes naive.
- **Multi-TLE**: dos elementos del mismo snapshot se propagan independientemente sin contaminación de estado.
- **Tiempos signed**: `minutes_from_epoch` negativo para pasado, positivo para futuro.

Casos canónicos públicos usados: el TLE ISS Vallado 2008-09-20 (`tests/fixtures/tle/iss_vallado_2008.txt`). Es el mismo TLE referenciado en Vallado et al. (2006) *Revisiting Spacetrack Report #3*, sección 6.1.

### Criterios de aceptación (Derived v1 cerrada)

Derived v1 se considera cerrada cuando:

1. **ADR-0014** aceptado.
2. **`Propagator` Protocol** definido en `propagation/propagator.py`.
3. **`Sgp4Propagator`** implementa el Protocol con la semántica de este ADR.
4. **`Ephemeris`** Pydantic frozen con todos los campos especificados.
5. **`PropagationError`** definido en `core/errors.py` con causas documentadas.
6. **Golden master test pasa**: wrapper produce los mismos números que `sgp4` directamente para el TLE canónico ISS.
7. **Sanidad física pasa**: ranges de `|r|` y `|v|` para LEO.
8. **Determinismo verificable**: tests demuestran salida bit-idéntica en repeticiones.
9. **Trazabilidad verificable**: tests demuestran que cada Ephemeris navega de vuelta a su Raw vía las FKs.
10. **Las 130 pruebas previas siguen verdes**.

### No incluido en Derived v1 (explícito)

- Persistencia de Ephemeris a Parquet.
- Caché de ventana corta para queries repetidas.
- Detección de conjunciones, maniobras, anomalías.
- Conversión a frames distintos de TEME.
- Vectorización masiva (la API actual es escalar por instante).
- Visualización (Cesium, Dash).
- Cualquier agente LLM.
- Automatización (scheduling, retries, backoff).

Estas son extensiones legítimas para fases posteriores con sus propios ADRs.

## Justificación

- **Coherencia física**. Usar `Satrec.twoline2rv()` sobre las líneas TLE originales es la única forma de garantizar que el wrapper no introduzca desviaciones respecto a la librería de referencia. `sgp4init()` con campos parseados sería tentador pero introduce dependencias entre la fidelidad del parser y la precisión numérica.
- **Honestidad**. Preservar `sgp4_error_code` en lugar de filtrar respeta P2: el caller ve exactamente lo que SGP4 reportó.
- **On-demand**. Materializar efemérides es 8 TB en horizonte de 5 años (red-team F5). On-demand resuelve el problema arquitectónicamente y libera al storage de un coste físico imposible.
- **Defensa en profundidad**. La verificación `sha256(line1+\n+line2) == tle_content_hash` cuesta microsegundos y detecta una clase entera de bugs (corrupción cross-layer, inserciones ad-hoc) que de otra forma se manifestarían como errores numéricos sutiles.

## Consecuencias

**Positivas**
- Primer producto Derived funcional y trazable.
- Cierra el ciclo Raw → Normalized → Derived con determinismo y trazabilidad.
- La interfaz `Propagator` queda lista para multi-engine sin refactor de Analytics.
- Sin coste recurrente, sin red, sin persistencia.

**Negativas**
- Latencia: cada llamada hace `twoline2rv()` de nuevo (no se cachea `Satrec`). Aceptable para v1; optimización trivial cuando se justifique con un caso de uso real.
- API escalar por instante (loop interno): no optimizada para 30 000 objetos × N tiempos. Si se necesita, vectorizar con `sgp4.api.SatrecArray` será trabajo de v2.

**Neutras**
- TEME como única salida. Convertir a otros frames requiere módulo separado (con su propio ADR).

## Alternativas consideradas

### A. `Satrec.sgp4init()` con campos parseados
**Razón de rechazo:** acopla la precisión SGP4 a la fidelidad de nuestro parser. Cambios futuros en el parser podrían introducir desviaciones numéricas silenciosas.

### B. `skyfield` como capa intermedia
**Razón de rechazo:** wrapper sobre la misma librería de fondo. Añade dependencia sin ganar nada físico. Cuando necesitemos manipulación de tiempos avanzada (UT1, leap seconds), evaluar.

### C. Implementación SGP4 propia
**Razón de rechazo:** bus factor inaceptable, validación contra Vallado costosa, sin ganancia.

### D. Persistir Ephemeris en Parquet por defecto
**Razón de rechazo:** viola ADR-0006 enmienda 1 y la cota física de 8 TB del red-team F5.

### E. Filtrar / lanzar en `sgp4_error_code != 0`
**Razón de rechazo:** ocultaría información que el caller necesita para decidir. Coherente con ADR-0000 P2.

## Alineación con ADR-0000

- **Refuerza P1, P4**: determinismo, reproducibilidad bajo entorno declarado.
- **Refuerza P2**: códigos de error de SGP4 no se ocultan; el caller ve la incertidumbre cruda.
- **Refuerza P3, P8**: sin red, sin coste, sin persistencia obligatoria.
- **Refuerza P6**: contratos documentados en este ADR y en los docstrings.
- **Sin tensiones.**

## Referencias

- Vallado, D. A. et al. (2006). *Revisiting Spacetrack Report #3.* AIAA/AAS Astrodynamics Specialist Conference.
- Hoots, F. R., & Roehrich, R. L. (1980). *Spacetrack Report No. 3.*
- Brandon Rhodes. *python-sgp4* documentation.

---

## Historial de enmiendas

*Sin enmiendas a fecha de aceptación.*
