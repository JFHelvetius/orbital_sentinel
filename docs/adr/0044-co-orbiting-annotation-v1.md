# ADR-0044: Co-orbiting Annotation v1

**Estado:** Aceptado
**Fecha:** 2026-06-12
**Relacionado con:** ADR-0000 (P2), ADR-0010, ADR-0016, ADR-0019, ADR-0020, ADR-0029

## Contexto

El 2026-06-12 se ejecutó la **primera ingesta real de CelesTrak** del proyecto
(grupo `stations`, 25 objetos), rompiendo deliberadamente la disciplina previa
de validar solo sobre fixtures sintéticos (el red-team F8: "construir analítica
sobre fixtures").

El screening N-a-N sobre ese grupo, con threshold 50 km, produjo **36/36
detecciones operacionalmente triviales**. Causa real: CelesTrak distribuye TLEs
idénticos o casi idénticos para los vehículos acoplados a la ISS (Soyuz,
Progress, Dragon, Cygnus, módulos comparten el estado orbital de la estación).
Resultado: `miss_distance_km = 0.000`, `relative_velocity_km_s = 0.000`.

El sistema es **matemáticamente correcto** — esos objetos sí están a distancia
≈ 0 — pero el "finding" no es lo que un operador entiende por alerta de
conjunción. Es la tensión de **P2 (honestidad sobre incertidumbre)** aflorando
en una dirección que los fixtures sintéticos (ISS vs GEO fabricado) nunca
pudieron exponer: el sistema puede generar ruido que *parece* señal.

Esta es exactamente la clase de decisión que la disciplina del proyecto pide:
**dato real → observación → ADR justificado por evidencia**, no por especulación.

## Decisión

Añadir una **anotación declarada** de co-orbiting a `ConjunctionAnalysis`,
derivada de la velocidad relativa en el TCA, que se propaga a
`ConjunctionDetection` (persistida) y al `honesty_payload` de la evidencia.

### Anotar, no filtrar

La decisión central, alineada con P2: **NO se filtra ni se elimina ninguna
detección.** Esconder una detección geométricamente real sería tan deshonesto
como dibujar una incertidumbre de 3 km como una línea fina. En su lugar, cada
detección lleva un booleano honesto que el consumidor puede usar — o ignorar
bajo su responsabilidad, igual que el régimen de precisión declarado de ADR-0014.

### Discriminador físico

Una conjunción entre objetos **independientes** en LEO tiene velocidad relativa
en el TCA del orden de 0.5–15 km/s (órbitas que se cruzan o convergen). Objetos
**co-orbitando o acoplados** (misma órbita, misma fase) tienen velocidad
relativa ~0 (cm/s a m/s). El umbral:

```
CO_ORBITING_RELATIVE_VELOCITY_THRESHOLD_KM_S = 0.05   # 50 m/s
is_apparent_co_orbiting = relative_velocity_km_s < threshold
```

50 m/s es conservador: por debajo de eso el "encuentro" es co-movimiento, no
geometría de colisión. El umbral es un **campo declarado y overridable**
(`co_orbiting_velocity_threshold_km_s`), no una constante mágica oculta. Validado
contra el dato real (el clúster ISS dio rel_v de 0.000 a 0.00085 km/s; una
conjunción de cruce real estaría órdenes de magnitud por encima).

### Por qué NO sube engine_version

`CONJUNCTION_SCHEMA_VERSION`: 0.3.0 → **0.4.0** (campo nuevo, estructura).
`CONJUNCTION_ENGINE_VERSION`: se mantiene en **0.3.0**.
`PERSISTED_CONJUNCTION_SCHEMA_VERSION`: 0.2.0 → **0.3.0**.

La anotación es una **función pura de `relative_velocity_km_s`**, que el motor ya
computaba. No cambia ningún valor geométrico ni de Pc: `miss_distance_km`, `tca`,
`pc`, `relative_velocity_km_s` son **bit-idénticos**. Por ADR-0010, eso es un
cambio de esquema (estructura), no de motor (comportamiento numérico). En
consecuencia, **`detection_content_hash` permanece estable**: la misma geometría
produce la misma identidad de detección antes y después de esta ADR.

## Hard guarantees

1. **No se filtra ninguna detección.** Solo se anota. P2 preservado en ambas
   direcciones (ni inflar ni esconder).
2. **`detection_content_hash` estable.** engine_version no cambia; la identidad
   content-addressable de las detecciones existentes no se altera.
3. **Inmutabilidad de casos previos.** El `honesty_payload` de la evidencia es
   `dict[str, Any]` cargado verbatim del JSON; los `case.json` emitidos antes de
   esta ADR recomputan idénticos. Las nuevas claves solo aparecen en evidencia
   recién construida. Verificado: los bundles + casos `reference_cases` siguen
   verificando.
4. **Determinismo.** `is_apparent_co_orbiting` es función pura de un valor ya
   determinista y un umbral declarado.
5. **Backward-compatible.** Campos con default; construcciones existentes de
   `ConjunctionAnalysis`/`ConjunctionDetection` sin los campos siguen validando.
6. **Removible.** Borrar los dos campos + la línea del detector deja el sistema
   en estado ADR-0020 sin pérdida (la velocidad relativa, de la que derivan,
   permanece).

## Alineación con ADR-0000

Refuerza **P2** directamente: el sistema ahora distingue, de forma honesta y
declarada, entre una geometría de colisión aparente y un co-movimiento trivial,
sin ocultar datos. Es la primera decisión del proyecto **motivada por evidencia
de dato real** en lugar de por análisis de fixtures — coherente con el modelo de
evaluación de salud (eje "calidad de inferencia" contra ground truth real).

No toca P1/P3/P4/P7: sin red nueva, sin coste, sin dependencias, reproducible.

## Alternativas consideradas

| Alternativa | Por qué se descartó |
|---|---|
| Filtrar las detecciones co-orbiting del output | Viola P2: esconder una proximidad geométricamente real es deshonesto. El consumidor debe ver el dato y su contexto, no un subconjunto curado. |
| Discriminar por `element_a_tle_content_hash == element_b_tle_content_hash` | Solo captura TLEs idénticos (miss exacto 0). No captura el clúster a 0.6 km con TLEs distintos pero co-movimiento. La velocidad relativa es el discriminador físico correcto y continuo. |
| Discriminar por `content_hash_source` compartido | Inválido: todos los objetos de una misma ingesta comparten el `content_hash_source` (es el hash del fichero TLE completo), no discrimina nada. |
| Subir engine_version | Deshonesto: ningún valor numérico cambia. Cambiaría `detection_content_hash` de toda detección sin que la geometría haya cambiado. |
| Umbral hardcoded sin declararlo | Viola P2: el criterio debe ser inspeccionable y overridable, no mágico. |

## Consecuencias

- El screening sobre dato real es **interpretable**: 36 detecciones triviales
  quedan marcadas `is_apparent_co_orbiting=True` en vez de parecer 36 alertas.
- La anotación viaja por toda la cadena de evidencia (ADR-0029): un auditor que
  recibe un `case.json` ve el contexto co-orbiting junto al miss y al Pc.

### Limitación deliberada de v1

- El umbral es global, no por par ni por régimen orbital. Suficiente para el
  caso observado; reabrible si datos reales muestran necesidad de umbrales
  contextuales.
- No se expone aún un flag de CLI para overridear el umbral; se usa el default
  declarado. Reabrible.
- La anotación es observacional (`apparent`), no una clasificación de
  "acoplado" confirmada. El proyecto no afirma estados operacionales (P2).

## Métricas

- 2 campos nuevos en `ConjunctionAnalysis` y en `ConjunctionDetection`.
- 1 constante declarada + 1 parámetro nuevo en `analyze_pairwise_conjunction`.
- 2 claves nuevas en el `honesty_payload` de la evidencia de conjunción.
- 0 cambios en valores geométricos/Pc; `detection_content_hash` estable.
- 0 nuevas dependencias. 0 cambios en hashes de casos pre-existentes.
- 5 tests nuevos. Suite 1064 verde.
