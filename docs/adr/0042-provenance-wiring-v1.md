# ADR-0042: Provenance Wiring v1

**Estado:** Aceptado
**Fecha:** 2026-06-07
**Relacionado con:** ADR-0000, ADR-0006, ADR-0010, ADR-0011, ADR-0012, ADR-0013, ADR-0029, ADR-0031, ADR-0038, ADR-0040

## Contexto

ADR-0040 introdujo el **External Source Provenance Layer v1** como capa declarativa: define el contrato de `ExternalSourceRecord` y `ExternalSourceRegistry`, pero **no se conectó al fetcher real**. En producción, un operador que ejecutaba `orbital-sentinel ingest` no obtenía ningún registry automáticamente; los únicos `ExternalSourceRegistry` que existían eran fixtures de tests.

Esto creaba una brecha entre la **completitud declarativa** del sistema (capa existe) y su **completitud operativa** (la promesa fundacional de ADR-0000 *"rastrear hasta el dato original"* no funcionaba sin intervención manual).

La auditoría de evaluación arquitectónica identificó este como el **único ciclo arquitectónico abierto** entre los 41 ADRs previos, con impacto directo sobre el cumplimiento de la promesa central del proyecto.

## Decisión

Cerrar el ciclo mediante **derivación pura** del registry desde los repositorios persistidos (`TLESnapshotsRepository` + `OrbitalElementsRepository`), sin modificar el fetcher, el normalizer, ni los modelos de ninguna capa previa.

### Observación clave

`TLESnapshot` (capa Raw, ADR-0006) ya almacena: `source`, `dataset`, `url`, `fetched_at`, `content_hash`, `n_bytes`. Es decir, **toda la información necesaria para construir un `ExternalSourceRecord` ya está persistida**. `OrbitalElement.content_hash_source` ya enlaza Normalized → Raw. La provenance no necesita ser *generada*: necesita ser *derivada*.

### Pieza añadida

Un único módulo nuevo: `src/orbital_sentinel/analytics/external_sources/provenance.py`, con la función pura:

```python
def derive_external_source_registry_for_bundle(
    bundle: EvidenceBundle,
    *,
    tle_snapshots_repo: TLESnapshotsRepository,
    orbital_elements_repo: OrbitalElementsRepository,
    clock: Callable[[], datetime] | None = None,
) -> ExternalSourceRegistry:
```

### Algoritmo

1. Recolecta los `object_id` distintos de `bundle.evidence_payloads`.
2. Para cada uno, consulta `OrbitalElementsRepository.find_all_by_norad_id` para recuperar el conjunto de `content_hash_source` que contribuyeron observación a ese objeto.
3. Para cada `content_hash_source` único, recupera `TLESnapshot` desde Raw y lo mapea a `ExternalSourceRecord` mediante `_map_provider` (mapeo determinístico de nombre de fuente → literal cerrado de `SourceProvider`).
4. Compone `evidence_to_source_record_mapping` mapeando cada `evidence_id` al conjunto de records que cubren su `object_id`.
5. Delega en `build_external_source_registry` para producir el artefacto content-addressable.

### CLI

Un único subcomando nuevo: `orbital-sentinel external-source-registry-from-repos <bundle|-> --raw-root <PATH> --normalized-root <PATH>`. Lee el bundle, abre los repositorios read-only, emite el registry en stdout. Sin estado, sin red, sin escritura.

### Binding cryptográfico al caso

El registry NO se embebe en `InvestigationCase`. Es un artefacto **sidecar** cuya unión cryptográfica al caso se da por `source_bundle_id == case.evidence_bundle.bundle_id`. Un auditor que recibe `case.json` + `external_sources.json`:

1. Ejecuta `verify-investigation-case <case>`.
2. Extrae el bundle del case (campo `evidence_bundle`).
3. Ejecuta `verify-external-source-registry <external_sources> --bundle-file <bundle>`.
4. Confirma que `source_bundle_id` coincide en ambos.

Esta separación preserva la **inmutabilidad de todos los hashes de ADR-0031 a ADR-0041**.

## Hard guarantees

1. **Cero modificaciones a hashes existentes.** `bundle_id`, `agent_input_id`, `explanation_id`, `claim_registry.registry_id`, `hypothesis_registry.registry_id`, `chain_id`, `case_id` se preservan bit-a-bit.
2. **Read-only sobre los repositorios.** El módulo no escribe en disco. No muta nada.
3. **Determinismo bit-a-bit.** Mismos repos + mismo bundle → mismo `registry_id`, independientemente del orden de inserción histórico.
4. **Clock-isolated.** El clock sólo afecta `derived_at`.
5. **No persistencia nueva.** El layout en disco de Raw y Normalized queda intacto.
6. **No networking.** Sólo lookup local.
7. **No nuevas dependencias.** Usa exclusivamente módulos existentes.
8. **Removible.** Borrar `provenance.py` + el subcomando del CLI deja el sistema en estado v1-declarativo de ADR-0040 sin pérdida de información.

## Alineación con ADR-0000

Cierra la última distancia entre la promesa fundacional *"Si alguien afirma 'Este satélite realizó una maniobra', Orbital Sentinel debe permitir reconstruir la cadena completa que conecta esa afirmación con la evidencia original"* y su cumplimiento operativo real.

Antes de ADR-0042: la cadena verificable terminaba en un hash sintético (`raw_evidence_ids`) sin documentación de la fuente externa, salvo que el operador construyera records manualmente.

Después de ADR-0042: cualquier bundle producido desde el catalog persistido permite derivar automáticamente el registry que documenta de qué fuente externa (Celestrak en producción actual) vino cada TLE crudo.

## Alternativas consideradas

| Alternativa | Por qué se descartó |
|---|---|
| Modificar el fetcher para emitir records junto con el snapshot | Innecesario: la información ya está en `TLESnapshot`. Sería duplicar datos persistidos. |
| Añadir campo `source_record_id` a `OrbitalElement` | Cambio invasivo del modelo Normalized. Rompe Parquet existente. La info se deriva del `content_hash_source` ya presente. |
| Embedir `ExternalSourceRegistry` en `InvestigationCase` v2 | Cambia el hash del caso. Rompe inmutabilidad de ADR-0038. Forzaría bump de versión sin necesidad. |
| Persistir registry como Parquet | Viola "no persistencia nueva". El registry es derivable bit-a-bit en cualquier momento. |
| Esperar a futuro ADR específico de ingesta multi-fuente | Pospone el cumplimiento de la promesa fundacional indefinidamente. |

## Consecuencias

- La promesa fundacional de ADR-0000 funciona **end-to-end automáticamente** en producción real.
- Cualquier `EvidenceBundle` producido desde el catalog tiene un registry de provenance derivable sin intervención.
- ADR-0040 pasa de "capa declarativa con uso manual" a "capa integrada operativa".
- Habilita workflows reales de re-ingestión con detección de cambios: si Celestrak emite un TLE corregido, el nuevo `content_hash` produce un `source_record_id` distinto, y los registries de los bundles anteriores siguen apuntando al record original (puede revocarse con ADR-0039 `superseded_by_corrected_upstream`).

### Limitación deliberada de v1: granularidad por objeto

El mapping `evidence_id → source_record_ids` asocia cada evidencia a **todos** los snapshots que contienen al menos un orbital element del mismo `object_id`. Es decir: si una evidencia de maniobra se deriva del análisis de 25 TLEs de un objeto, los 25 `content_hash_source` aparecen como sources de esa única evidencia.

Esto es honesto (refleja "estos son los inputs que contribuyeron") pero conservador (no identifica cuál TLE específico generó cuál evidencia). El refinamiento a granularidad por-evidencia requiere instrumentar los detectores para que registren explícitamente qué `OrbitalElement` consumieron; eso queda fuera del scope de v1 y puede abordarse en una futura ADR si se valida la necesidad.

## Métricas

- 1 archivo nuevo en `src/orbital_sentinel/analytics/external_sources/`.
- 1 subcomando nuevo en `cli.py`.
- 0 modificaciones a modelos Pydantic existentes.
- 0 modificaciones a fetcher / normalizer / catalog.
- 0 nuevas dependencias.
- 0 cambios en hashes pre-existentes (verificado).
- 12 unit tests + 9 integration tests añadidos.
