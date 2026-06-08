# ADR-0039: Revocation Layer v1

**Estado:** Aceptado
**Fecha:** 2026-06-07
**Relacionado con:** ADR-0000, ADR-0010, ADR-0020, ADR-0031, ADR-0035, ADR-0036, ADR-0037, ADR-0038

## Contexto

Tras ADR-0038 cualquier conclusión orbital puede empaquetarse en un `InvestigationCase` portable y verificable. Pero si, después de emitido un caso, se descubre que el TLE upstream estaba corrupto, que la metodología fue inválida, o que el emisor desea retirar la afirmación, **no existe protocolo content-addressable para marcarlo formalmente como revocado**.

Sin revocación, un caso queda eternamente vigente y los consumidores no pueden distinguir un caso vivo de uno obsoleto sin reverificar manualmente todo el upstream. Eso rompe la promesa de auditabilidad extremo a extremo del proyecto.

## Decisión

Introducir un **Revocation Layer v1** que emite `RevocationLedger` objects content-addressable. Cada ledger contiene 0..N `RevocationRecord`, cada uno apuntando a un artefacto de las capas previas (`evidence_bundle`, `agent_input`, `explanation_artifact`, `claim_registry`, `hypothesis_registry`, `evidence_chain`, `investigation_case`) y declarando la razón de revocación.

La revocación **no muta** el artefacto target. **No requiere acceso** a su payload. Sólo registra una afirmación firmada content-addressable que cualquier consumidor offline puede consultar antes de aceptar el artefacto como vigente.

### Modelos (Pydantic v2, frozen, `extra="forbid"`)

- `RevocationRecord`: `revocation_id` (sha256), `target_artifact_type` (literal cerrado, 7 valores), `target_artifact_id`, `target_artifact_signature` (la firma del target al momento de revocar — detecta mutación posterior), `revocation_reason` (literal cerrado, 5 valores), `superseding_artifact_id` (opcional), `supporting_evidence_ids` (opcional), `revocation_label` (template), `emitted_at`, `schema_version`. Hard invariant: `revocation_id` recomputa.
- `RevocationLedger`: `ledger_id ≡ ledger_hash` (alias estricto), `records`, `n_records`, `target_to_revocation_index` (forward), `ledger_emit_reason` ∈ {`records_present`, `empty_ledger`}, versioning, `derived_at`. Hard invariant enforced por model_validator.
- `RevocationVerificationFinding`: contrato cerrado con **14 finding_type literales**.
- `RevocationVerificationReport`: `is_valid`, contadores, **7 checks individuales booleanos**, `findings`, `verification_hash`.

### Razones de revocación cerradas v1

```python
RevocationReason = Literal[
    "superseded_by_corrected_upstream",   # requiere superseding_artifact_id
    "retracted_by_emitter",
    "integrity_violation_discovered",     # requiere ≥1 supporting_evidence_id
    "schema_obsolete",
    "voluntary_withdrawal",
]
```

### Builder + helpers

- `build_revocation_record(...)` — emite un record content-addressable.
- `build_revocation_ledger(records, *, clock)` — rechaza duplicados por target.
- `is_artifact_revoked(ledger, *, artifact_id)` — utilidad pura O(N) para que un consumidor consulte si un artefacto está revocado por un ledger dado.

### Verifier

`verify_revocation_ledger(ledger)` — función pura, **nunca lanza**. Ejecuta 7 categorías de checks:
1. Alias `ledger_id == ledger_hash`.
2. `ledger_hash` recomputa.
3. `n_records` coherente.
4. `revocation_layer_engine_version` esperado.
5. Per-record: `revocation_id` recomputa, no duplicados de id, no duplicados de target, label coherente con template, campos obligatorios presentes según `revocation_reason`.
6. `target_to_revocation_index` coherente con records.
7. Engine version consistent.

`verification_hash = SHA-256(ledger_id | is_valid | n_records_verified | n_findings | verifier_engine_version)`.

### CLI

- `orbital-sentinel revoke-artifact --target-artifact-type X --target-artifact-id Y --target-artifact-signature Z --reason R [--superseding-artifact-id ...] [--supporting-evidence-id ...]*` → emite ledger con un record.
- `orbital-sentinel verify-revocation-ledger <ledger|-> [--strict]`.

## Hard guarantees

1. **Read-only sobre el target.** No muta nada upstream.
2. **`target_artifact_signature` congelado.** Si alguien recolecta un caso y luego lo modifica, su nueva firma no coincide con la del record — el consumidor lo detecta.
3. **Determinismo bit-a-bit.** Clock-isolated.
4. **No persistence, no network, no LLM.** El ledger se serializa como cualquier otro objeto JSON; el storage es responsabilidad del caller.
5. **Removible.**

## Alineación con ADR-0000

Una infraestructura pública verificable requiere protocolo de retractación honesta. Sin revocación, el sistema acumula afirmaciones obsoletas que se vuelven indistinguibles de las vigentes, erosionando la confianza. Esta capa hace de la **retractación misma** un artefacto auditable.

## Alternativas consideradas

- **Re-emitir el caso revocado con flag `revoked=True`.** Rechazada: viola la inmutabilidad de los artefactos content-addressable (rompe la firma) y no permite que terceros revoquen casos ajenos.
- **Ledger con múltiples revocaciones del mismo target.** Rechazada en v1 — una revocación por target por ledger. Para corregir, emitir un nuevo ledger.
- **Firmar revocaciones con clave asimétrica.** Rechazada: añade gestión de claves. Autenticación de origen es ortogonal; el ledger content-addressable basta para integridad.

## Consecuencias

- Permite revocación honesta extremo a extremo.
- Prerequisito para ADR-0041 (dissent puede *referenciar* casos revocados sin ambigüedad).
- Habilita workflows de corrección upstream sin perder histórico.

## Métricas

- 5 archivos nuevos en `src/orbital_sentinel/analytics/revocations/`.
- 14 finding_type literales.
- 7 checks individuales booleanos.
- 0 nuevas dependencias.
