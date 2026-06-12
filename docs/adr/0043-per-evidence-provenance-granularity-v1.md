# ADR-0043: Per-Evidence Provenance Granularity v1

**Estado:** Aceptado
**Fecha:** 2026-06-11
**Relacionado con:** ADR-0000, ADR-0006, ADR-0010, ADR-0028, ADR-0029, ADR-0031, ADR-0040, ADR-0042

## Contexto

ADR-0042 (Provenance Wiring v1) cerró el último ciclo arquitectónico abierto:
la derivación automática del `ExternalSourceRegistry` desde el catalog
persistido. Pero declaró explícitamente **una limitación deliberada** en su
sección *"Limitación deliberada de v1: granularidad por objeto"*:

> El mapping `evidence_id → source_record_ids` asocia cada evidencia a **todos**
> los snapshots que contienen al menos un orbital element del mismo `object_id`.
> [...] honesto pero conservador (no identifica cuál TLE específico generó cuál
> evidencia). El refinamiento a granularidad por-evidencia requiere instrumentar
> los detectores para que registren explícitamente qué `OrbitalElement`
> consumieron; eso queda fuera del scope de v1 y puede abordarse en una futura
> ADR si se valida la necesidad.

Esta ADR aborda ese refinamiento. La necesidad está validada: la promesa
fundacional de ADR-0000 — *"reconstruir la cadena completa que conecta una
afirmación con la evidencia original"* — se cumple de forma **conservadora** hoy.
Una evidencia de maniobra derivada de 2 TLEs concretos aparece, en el registry
por-objeto, vinculada a los N TLEs del objeto. La cadena es honesta pero
imprecisa: un auditor no puede saber, desde el registry, qué dos TLEs exactos
sustentan ese finding.

## Observación clave: los hashes consumidos ya existen en los detectores

El refinamiento **no requiere recomputar nada nuevo**. Cada detector ya conoce
el `content_hash_source` exacto de los TLEs que consumió:

| Detector | Hashes fuente disponibles |
|---|---|
| `maneuver_detection_v01` | `ManeuverEvent.content_hash_source_before` + `content_hash_source_after` (doble FK Raw→Normalized ya presente) |
| `conjunction_detection_v01` | `ConjunctionDetection.element_a_content_hash_source` / `element_b_content_hash_source` (por lado) |
| `anomaly_detection_v01` | `el.content_hash_source` del punto observado — **disponible en el detector pero no propagado al evento** |

Maniobra y conjunción ya portan la información. Anomalía no la propagaba: ese
es el único punto que requiere *instrumentación* en el sentido de ADR-0042.

## Decisión

Registrar, por cada `DerivedEvidence`, el conjunto exacto de
`content_hash_source` que la evidencia consumió, y consumir esa granularidad
en `derive_external_source_registry_for_bundle` con **fallback** a la
expansión por-objeto cuando no esté disponible.

### Dónde se almacena: `honesty_payload`, no un campo tipado nuevo

La provenance consumida se escribe bajo la clave uniforme
`honesty_payload["consumed_source_hashes"]` (lista ordenada y deduplicada de
hex strings), **no** como campo nuevo de `DerivedEvidence`.

Esta es la decisión arquitectónica central de la ADR, y es deliberada:

`honesty_payload` es `dict[str, Any]` de forma libre (ADR-0029). Se carga
**verbatim** desde el JSON persistido. Por tanto, un `case.json` emitido antes
de esta ADR recomputará su `bundle_payload_signature` **bit-a-bit idéntico**
bajo el código nuevo: su `honesty_payload` no cambia, porque no lo definimos
con campos tipados.

Un campo tipado nuevo en `DerivedEvidence` (la alternativa rechazada abajo)
**rompería** esa propiedad: `model_dump(mode="json")` emitiría la nueva clave
con su default, y `verify_bundle` — que recomputa `compute_bundle_payload_signature`
desde los payloads cargados — produciría una firma distinta de la almacenada.
Cualquier bundle previamente emitido fallaría la verificación bajo el código
nuevo. Eso violaría la garantía de inmutabilidad de ADR-0006/ADR-0031.

### Instrumentación del detector de anomalías

`AnomalyEvent` gana un campo requerido `content_hash_source: str` (el
`content_hash_source` del `OrbitalElement` en el índice observado). El detector
`detect_anomalies` lo puebla desde `el.content_hash_source`, ya disponible en
el bucle. `ANOMALY_DETECTION_SCHEMA_VERSION` y `ANOMALY_DETECTION_ENGINE_VERSION`
suben 0.1.0 → 0.2.0 (ADR-0010).

`AnomalyEvent` **no** es un artefacto hasheado de ningún caso: nunca se embebe
en un bundle. Solo alimenta al builder. El bump no afecta el hash de ningún
caso existente.

### Refinamiento de la derivación del registry

`derive_external_source_registry_for_bundle` cambia de:

> para cada evidencia → expandir a todos los hashes del objeto

a:

> para cada evidencia → leer `honesty_payload["consumed_source_hashes"]`;
> si está presente y no vacía, usarla; si no, **fallback** a la expansión
> por-objeto (comportamiento ADR-0042 idéntico).

El conjunto de `ExternalSourceRecord` del registry pasa a ser la unión de los
hashes consumidos (preciso) en lugar de la unión de todos los hashes de todos
los objetos del bundle (conservador). Para bundles pre-0043 (sin la clave), el
resultado es **bit-a-bit idéntico** al de ADR-0042.

## Hard guarantees

1. **Cero modificaciones a `DerivedEvidence` como esquema tipado.** No hay campo
   nuevo. `compute_evidence_id` no cambia: `evidence_id` es estable.
2. **Inmutabilidad de bundles/casos previos.** Un `case.json` emitido antes de
   esta ADR recomputa `bundle_payload_signature`, `bundle_id` y `case_id`
   idénticos. `verify_bundle` y `verify-investigation-case` pasan sin cambios.
3. **Determinismo bit-a-bit.** `consumed_source_hashes` se escribe ordenada y
   deduplicada. Misma evidencia → mismo payload → mismo hash.
4. **Backward-compatible en la derivación.** Bundles sin la clave usan el path
   por-objeto de ADR-0042, bit-idéntico.
5. **No persistencia nueva.** El registry sigue siendo sidecar derivable
   (ADR-0042). El layout de Raw/Normalized queda intacto.
6. **No networking. No nuevas dependencias.**
7. **Removible.** Revertir builders + detector + provenance deja el sistema en
   estado ADR-0042 por-objeto sin pérdida de información (los hashes se
   rederivan del catalog).

## Consecuencia honesta: bundles nuevos cambian de hash

Un bundle construido **de nuevo** (no recargado) que contenga evidencia de
conjunción o anomalía tendrá `bundle_id` distinto al que habría tenido bajo
ADR-0042, porque su `honesty_payload` ahora incluye `consumed_source_hashes`
(y, para anomalía, el evento upstream lleva un campo más). Esto es **evolución
de esquema legítima**, no una violación: los artefactos previamente emitidos no
se tocan; solo las nuevas emisiones reflejan la granularidad refinada. Los
`reference_cases/` ya persistidos conservan sus hashes y siguen verificando.

Para evidencia de **maniobra**, el `honesty_payload` ya contenía
`content_hash_source_before/after`; añadir `consumed_source_hashes` (derivada de
esos dos) es la única diferencia.

## Alineación con ADR-0000

Refuerza directamente la promesa fundacional. Antes de esta ADR, la cadena
verificable terminaba en "los TLEs del objeto"; después, termina en "los TLEs
exactos que sustentan este finding". Un auditor que recibe `case.json` +
`external_sources.json` puede ahora confirmar, para cada evidencia individual,
qué descarga externa concreta la sustenta — sin perder la honestidad de
ADR-0028 (la evidencia sigue siendo *apparent, not confirmed*).

Preserva P1 (trazabilidad) llevándola de granularidad de objeto a granularidad
de evidencia, sin comprometer P4 (reproducibilidad bajo entorno declarado) ni
la inmutabilidad de ADR-0006.

## Alternativas consideradas

| Alternativa | Por qué se descartó |
|---|---|
| Campo tipado `consumed_source_hashes` en `DerivedEvidence` | Rompe la inmutabilidad: `verify_bundle` recomputa `bundle_payload_signature` desde los payloads; el campo nuevo (con su default) cambia el `model_dump` de toda evidencia previamente emitida, haciendo fallar la verificación de bundles existentes bajo el código nuevo. |
| Instrumentar maniobra/conjunción para "qué TLE generó qué" además del par | Innecesario: el par (before/after) y el lado (a/b) **son** ya la granularidad por-evidencia exacta para esos detectores. |
| Persistir el registry refinado como Parquet | Viola "no persistencia nueva" de ADR-0042. El registry es derivable bit-a-bit. |
| Capturar también la ventana baseline completa de anomalía | El finding de anomalía se sustenta en el **punto observado**; la baseline es contexto estadístico, ya declarado en `honesty_payload` (mean/stddev/n_samples). Incluir N hashes de baseline diluiría la precisión sin ganancia de auditabilidad. Reabrible si se valida la necesidad. |

## Consecuencias

- La promesa de ADR-0000 opera a granularidad de evidencia individual.
- ADR-0042 pasa de "provenance por-objeto (conservadora)" a "por-evidencia
  (precisa)" sin romper nada de lo emitido bajo el régimen anterior.
- Habilita auditoría fina: "¿qué descarga sustenta *esta* maniobra?" tiene
  respuesta exacta, no un conjunto sobre-aproximado.

### Limitación deliberada de v1

La granularidad de anomalía es por **punto observado**, no por ventana baseline.
Es la unidad correcta de sustento del finding. Refinar a "qué TLEs de baseline
contribuyeron al σ" queda fuera de scope; reabrible vía ADR futura.

## Métricas

- 0 campos tipados nuevos en `DerivedEvidence`.
- 1 campo nuevo en `AnomalyEvent` (`content_hash_source`), no hasheado en casos.
- 3 builders actualizados para emitir `consumed_source_hashes`.
- 1 función refinada (`derive_external_source_registry_for_bundle`).
- 0 cambios en hashes de bundles/casos pre-existentes (verificado).
- 0 nuevas dependencias.
