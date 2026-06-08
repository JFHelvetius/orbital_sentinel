# ADR-0041: Dissent Layer v1

**Estado:** Aceptado
**Fecha:** 2026-06-07
**Relacionado con:** ADR-0000, ADR-0010, ADR-0020, ADR-0035, ADR-0036, ADR-0038, ADR-0039

## Contexto

Tras ADR-0038 el sistema emite `InvestigationCase` portables y verificables. Tras ADR-0039 el emisor original puede revocar sus propios casos. Pero **ningún tercero independiente** puede registrar de manera content-addressable que *discrepa* con un caso ajeno: que la evidencia citada está incompleta, que la metodología es inválida, que existe una explicación alternativa, que el alcance está mal definido.

Sin protocolo de disensión verificable, el sistema se vuelve autoritativo: la única voz que existe es la del emisor del caso. Esto rompe la promesa de *"Wikipedia verificable del espacio"* — un Wikipedia sin "talk page" firmable no es público; es publicación.

## Decisión

Introducir un **Dissent Layer v1** que emite `DissentLedger` objects content-addressable. Cada ledger apunta a un `InvestigationCase` target específico (por `case_id` + `case_signature`) y contiene 0..N `DissentRecord`, cada uno declarando el tipo de objeción, opcionalmente la evidencia que la sustenta, opcionalmente un caso alternativo propuesto.

El layer **no juzga el mérito** de la disensión. **No valida la disensión contra el caso target**. Sólo prueba que la disensión existe, es atribuible a un caso concreto, y es verificable bit-a-bit por cualquier consumidor offline. **La verificabilidad de la disensión es separable de su validez epistémica.**

### Modelos (Pydantic v2, frozen, `extra="forbid"`)

- `DissentRecord`: `dissent_id` (sha256), `target_case_id`, `target_case_signature`, `dissent_index` (≥0), `dissent_type` (literal cerrado, 5 valores), `dissent_basis_evidence_ids` (opcional), `referenced_alternative_case_id` (opcional), `dissent_label` (template), `emitted_at`, `schema_version`. Hard invariant: `dissent_id` recomputa.
- `DissentLedger`: `ledger_id ≡ ledger_hash` (alias estricto), `target_case_id`, `target_case_signature`, `records`, `n_records`, `dissent_type_index` (forward por tipo), `ledger_emit_reason` ∈ {`records_present`, `empty_ledger`}, versioning, `derived_at`.
- `DissentVerificationFinding`: contrato cerrado con **16 finding_type literales**.
- `DissentVerificationReport`: `is_valid`, contadores, **9 checks individuales booleanos**, `findings`, `verification_hash`.

### Tipos de disensión cerrados v1

```python
DissentType = Literal[
    "factual_correction",          # requiere ≥1 basis_evidence
    "alternative_explanation",     # requiere referenced_alternative_case_id
    "missing_evidence",            # requiere ≥1 basis_evidence
    "methodological_objection",
    "scope_disagreement",
]
```

Cada tipo tiene **requisitos de campos obligatorios** validados por el verifier. Esto evita disensiones vacías sin sustento.

### Builder + helpers

- `build_dissent_record(...)` — emite un record content-addressable. Label template determinístico: `"Dissent #{idx} on case {case_id}: type={dissent_type}."`.
- `build_dissent_ledger(target_case_id, target_case_signature, records, *, clock)` — rechaza records con `target_case_id` distinto, rechaza índices no secuenciales 0..N-1.

### Verifier

`verify_dissent_ledger(ledger)` — función pura, **nunca lanza**. Ejecuta 9 categorías de checks:
1. Alias `ledger_id == ledger_hash`.
2. `ledger_hash` recomputa.
3. `n_records` coherente.
4. `dissent_layer_engine_version` esperado.
5. Per-record: `dissent_id` recomputa, no duplicados de id, no duplicados de índice, target consistente con el ledger, label coherente con template, campos obligatorios según `dissent_type`.
6. `dissent_index` secuencial 0..N-1.
7. `dissent_type_index` coherente con records (transposición sorted).

`verification_hash = SHA-256(ledger_id | is_valid | n_records_verified | n_findings | verifier_engine_version)`.

### CLI

- `orbital-sentinel dissent-record --target-case-id X --target-case-signature Y --dissent-index N --dissent-type T [--basis-evidence-id ...]* [--referenced-alternative-case-id ...]` → emite single record JSON.
- `orbital-sentinel dissent-ledger --target-case-id X --target-case-signature Y [--record-file ...]*` → ensambla ledger desde records.
- `orbital-sentinel verify-dissent-ledger <ledger|-> [--strict]`.

## Hard guarantees

1. **Cualquier tercero puede disentir** sin permiso del emisor del caso target. La disensión es asimétrica: el target no sabe (ni necesita saber) que fue disentido.
2. **`target_case_signature` congelado**. Si el caso target se modifica después de la disensión, la disensión sigue apuntando a *la versión original*, no a la nueva.
3. **Tipo cerrado + reglas obligatorias** evitan disensiones huecas: `factual_correction` y `missing_evidence` requieren evidencia; `alternative_explanation` requiere caso alternativo.
4. **No valida la disensión.** El verifier sólo prueba integridad estructural; el *mérito* lo decide el consumidor a partir de la evidencia y el caso alternativo citados.
5. **Determinismo bit-a-bit.** Clock-isolated.
6. **Removible.**

## Alineación con ADR-0000

Esta capa transforma la promesa del proyecto: pasa de *"infraestructura de explicación verificable"* a *"infraestructura de discurso verificable"*. La verdad orbital no se establece por autoridad sino por *cadenas content-addressable de afirmaciones y contra-afirmaciones*, todas auditables independientemente.

Es el equivalente, en términos verificables, del talk page de Wikipedia. Sin esto, Orbital Sentinel sería un *publicador* de conclusiones; con esto, es una *plataforma* donde cualquiera puede objetar de manera firmable y trazable.

## Alternativas consideradas

- **Forzar dissent a citar un caso alternativo siempre.** Rechazada: excluye disensiones puramente metodológicas o de alcance, que son válidas sin necesidad de proponer un caso reemplazo.
- **Embedir dissents en el caso target.** Rechazada: viola la inmutabilidad del caso (rompe `case_signature`) y permite al emisor censurar disensiones.
- **Sistema de voting / scoring sobre dissents.** Rechazada explícitamente: viola ADR-0000 (nada de scoring). La validez de una disensión es ortogonal a su popularidad.
- **Firmar con clave asimétrica.** Rechazada: añade gestión de claves; autenticación de origen es ortogonal a verificabilidad estructural.
- **Persistir ledger como Parquet.** Rechazada: viola "removible".

## Consecuencias

- Cierra el ciclo de discurso público verificable: cualquier conclusión puede ser *citada y contradicha* con la misma garantía de integridad.
- Habilita workflows reales de revisión por pares: un analista puede revisar un caso ajeno y publicar dissents firmados que el consumidor del caso original puede consultar.
- Cierra Fase 7. Orbital Sentinel deja de ser una plataforma de *emisión* y pasa a ser una plataforma de *discurso* verificable.

## Métricas

- 5 archivos nuevos en `src/orbital_sentinel/analytics/dissent/`.
- 16 finding_type literales.
- 9 checks individuales booleanos.
- 5 dissent types literales con reglas obligatorias.
- 0 nuevas dependencias.
