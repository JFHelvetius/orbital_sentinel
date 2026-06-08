# ADR-0040: External Source Provenance Layer v1

**Estado:** Aceptado
**Fecha:** 2026-06-07
**Relacionado con:** ADR-0000, ADR-0006, ADR-0010, ADR-0011, ADR-0012, ADR-0013, ADR-0020, ADR-0029, ADR-0031, ADR-0037

## Contexto

La cadena verificable de ADR-0037 empieza en el nodo `raw_evidence`, cuyo `link_id` es un hash sintético sobre el conjunto de `evidence_ids` del bundle. Este nodo representa "el conjunto de evidencia que originó la cadena", pero **no documenta de qué fuente externa** (Celestrak, Space-Track, fichero offline, fixture de test) provino el TLE crudo que dio origen a cada `DerivedEvidence`.

Para un consumidor que recibe un `InvestigationCase`, el primer eslabón hacia abajo es un *"trust me bro"*: el caso es verificable hasta el bundle, pero no hay constancia de que los TLEs vinieran de donde el emisor declaró. Esto rompe la promesa de auditabilidad **público-pública**.

## Decisión

Introducir un **External Source Provenance Layer v1** que emite `ExternalSourceRegistry` objects content-addressable atados a un `EvidenceBundle`. Cada registry contiene 0..N `ExternalSourceRecord`, cada uno documentando una operación de ingesta externa (provider, URL, dataset, timestamp UTC, hash del payload bytes, content type) junto con el mapeo `evidence_id → source_record_id` que permite trazar cada evidencia derivada hasta su fuente externa.

El layer **no descarga datos**. **No valida URLs**. **No interpreta**. Sólo registra content-addressablemente lo que el fetch infrastructure declara haber traído. La integración con el fetch real (futura) es responsabilidad de una ADR específica de ingesta; v1 acepta los records como inputs explícitos y los firma.

### Modelos (Pydantic v2, frozen, `extra="forbid"`)

- `ExternalSourceRecord`: `source_record_id` (sha256), `source_provider` (literal cerrado: celestrak / space_track / norad / manual_offline_import / test_fixture), `source_url`, `source_dataset_identifier`, `fetched_at` (UTC), `source_payload_hash` (SHA-256 de bytes), `source_payload_size_bytes` (≥0), `source_content_type` (literal cerrado: tle_text / json_api / csv), `schema_version`. Hard invariant: `source_record_id` recomputa.
- `ExternalSourceRegistry`: `registry_id ≡ registry_hash`, `source_bundle_id` (atado a un bundle específico), `records`, `n_records`, `source_record_to_evidence_index` (forward), `evidence_to_source_record_index` (reverse), `registry_emit_reason` ∈ {`records_present`, `empty_registry`}, versioning, `derived_at`.
- `SourceVerificationFinding`: contrato cerrado con **15 finding_type literales**.
- `SourceVerificationReport`: `is_valid`, contadores, **9 checks individuales booleanos**, `findings`, `verification_hash`.

### Builder

`build_external_source_registry(bundle, records, evidence_to_source_record_mapping, *, clock)` — función pura. Valida:
1. Cada `evidence_id` del bundle está cubierto por al menos un `source_record_id` en el mapping.
2. Cada `source_record_id` referenciado en el mapping aparece en `records`.

Si falla cualquier check → `ExternalSourceRegistryBuilderError`. Materializa forward e reverse indexes con ordering canónico.

### Verifier

`verify_external_source_registry(registry, bundle)` — función pura, **nunca lanza**. Ejecuta 9 categorías de checks:
1. Alias `registry_id == registry_hash`.
2. `registry_hash` recomputa.
3. `n_records` coherente.
4. `source_layer_engine_version` esperado.
5. `source_bundle_id == bundle.bundle_id`.
6. Per-record: `source_record_id` recomputa, no duplicados, tamaño no negativo.
7. Forward index coherente.
8. Reverse index coherente.
9. Cobertura: todos los `evidence_id` del bundle aparecen en el reverse index.

`verification_hash = SHA-256(registry_id | is_valid | n_records_verified | n_findings | verifier_engine_version)`.

### CLI

- `orbital-sentinel external-source-registry <bundle|-> --records-file <path>` donde el records-file es `{"records": [...], "evidence_to_source_record_mapping": {...}}`.
- `orbital-sentinel verify-external-source-registry <registry|-> --bundle-file <path> [--strict]`.

## Hard guarantees

1. **Cierra el primer eslabón estructural** de la cadena: ahora la trazabilidad no termina en `raw_evidence` sino en `external_source_record`.
2. **No descarga datos.** El layer es 100% offline; sólo firma lo que se le declara.
3. **Detección de payload corrupto:** un consumidor con acceso al payload original puede recomputar `source_payload_hash` y validar bit-a-bit.
4. **Determinismo bit-a-bit.** Clock-isolated.
5. **Removible.**

## Alineación con ADR-0000

Esta capa cierra la pregunta más importante del proyecto: *"¿de dónde vinieron los TLEs originales?"*. Sin ella, la cadena verificable empieza siempre en un nodo sintético cuya correspondencia con el mundo real es un acto de fe. Con ella, cualquier afirmación orbital se puede rastrear hasta una operación de ingesta documentada, fechada y hashable.

Es la cimentación de la *"Wikipedia verificable del espacio cercano"*: las fuentes son citables independientemente.

## Alternativas consideradas

- **Embedir source records directamente en `EvidenceBundle`.** Rechazada: viola la inmutabilidad de capas previas; el bundle ya está firmado en ADR-0031.
- **Descargar y verificar online en build time.** Rechazada: viola "no network". El layer es puramente declarativo offline.
- **Permitir múltiples sources por evidence_id.** Aceptada — el mapping es `evidence_id → list[source_record_id]` para soportar futuras agregaciones cross-provider.
- **Persistir registry como Parquet.** Rechazada: viola "removible".

## Consecuencias

- Auditoría completa desde la cita externa hasta la hipótesis derivada.
- Habilita workflows de corrección upstream: si Celestrak corrige un TLE, una nueva ingesta produce un `source_record_id` nuevo, distinto del original, y los `InvestigationCase` derivados del original pueden revocarse (ADR-0039) con `superseded_by_corrected_upstream`.
- Próxima ADR de ingesta real (TBD) podrá instanciar este registry automáticamente desde el fetch infrastructure.

## Métricas

- 5 archivos nuevos en `src/orbital_sentinel/analytics/external_sources/`.
- 15 finding_type literales.
- 9 checks individuales booleanos.
- 5 source providers literales.
- 0 nuevas dependencias.
