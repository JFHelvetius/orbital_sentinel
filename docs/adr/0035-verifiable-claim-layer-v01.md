# ADR-0035: Verifiable Claim Layer v0.1

**Estado:** Aceptado
**Fecha:** 2026-06-07
**Relacionado con:** ADR-0000, ADR-0010, ADR-0020, ADR-0029, ADR-0030, ADR-0031, ADR-0032, ADR-0033, ADR-0034

## Contexto

Tras ADR-0034 el pipeline cierra el ciclo `bundle → agent-input → explain → verify-explanation`. Sin embargo, la unidad mínima auditable sigue siendo el `ExplanationArtifact` entero. Para auditoría granular se necesita atomizar el texto en *claims* (afirmaciones individuales), cada una con su propio identificador content-addressable y su lista de evidencias soportantes. Esto habilita: (a) lookup bidireccional claim ↔ evidence, (b) detección de claims huérfanas (sin evidencia) o evidencias no citadas, (c) revocación granular de claims sin invalidar el artifact entero.

## Decisión

Introducir una **Verifiable Claim Layer v0.1** que opera *después* del `ExplanationArtifact`, atomizando su `explanation_text` en `VerifiableClaim` objetos enlazados a `DerivedEvidence` via `evidence_id`. La capa es **content-addressable**, **determinista**, **read-only** sobre artifacts previos, **stdlib-only**, y se puede eliminar sin afectar capas anteriores.

### Modelos (Pydantic v2, frozen, `extra="forbid"`)

- `VerifiableClaim`: `claim_id` (sha256), `source_explanation_id`, `claim_index` (≥0), `supporting_evidence_ids` (min_length=1), `claim_text`, `schema_version`. Hard invariant: `claim_id` recomputa.
- `ClaimRegistry`: `registry_id` ≡ `registry_hash` (alias estricto), source IDs (`source_explanation_id`, `source_bundle_id`, `source_agent_input_id`, `source_model_identifier`, `source_explanation_engine_version`), `n_claims`, `claims`, `claim_to_evidence_index` (forward), `evidence_to_claim_index` (reverse), `registry_emit_reason` ∈ {`evidence_bundle`, `empty_bundle`}, versioning, `derived_at`.
- `ClaimVerificationFinding`: contrato cerrado con **19 finding_type literales** (ver `models.py`).
- `ClaimVerificationReport`: `is_valid`, contadores, **9 checks individuales booleanos**, `findings`, `verification_hash`.

### Builder (`build_claim_registry`)

Función pura. Valida:
1. `artifact.source_bundle_id == agent_input.bundle.bundle_id`.
2. `artifact.source_agent_input_id == agent_input.agent_input_id`.
3. `artifact.generation_metadata.model_identifier ∈ SUPPORTED_SOURCE_MODELS_V01`.

Si falla cualquiera de estas → `ClaimRegistryBuilderError`.

Si `bundle.evidence_payloads` está vacío → emite registry con `n_claims=0` y `registry_emit_reason="empty_bundle"`.

En caso normal: divide `explanation_text` por `\n`, mapea cada línea no vacía a `referenced_evidence_ids[i]` (1:1 en v0.1), construye cada `VerifiableClaim`, materializa forward index (keys sorted) y reverse index (keys y values sorted).

### Verifier (`verify_claim_registry`)

Función pura, **nunca lanza**. Ejecuta 11 categorías de checks:
1. Source IDs match (`explanation_id`, `bundle_id`, `agent_input_id`).
2. Model identifier soportado.
3. `n_claims` coherente.
4. Hard invariant `registry_id == registry_hash`.
5. Per-claim: `claim_id` recomputa, supporting no vacío, evidencias en bundle, índice único, id único.
6. `claim_index` secuencial 0..N-1.
7. Forward index coherente con claims.
8. Reverse index = traspuesta del forward.
9. `claim_text` bit-exacto vs línea correspondiente de `explanation_text`.
10. Cobertura `referenced_evidence_ids` ↔ unión de `supporting_evidence_ids`.
11. Global: todas las evidencias soportantes en bundle.

Cada check fallido genera un `ClaimVerificationFinding` con tipo literal.

`verification_hash = SHA-256(registry_id | is_valid | n_claims_verified | n_findings | verifier_engine_version)`.

### CLI

- `orbital-sentinel claim-registry <artifact_file|-> --agent-input-file <path>`
- `orbital-sentinel verify-claim-registry <registry_file|-> --agent-input-file <path> --explanation-artifact-file <path> [--strict]`

Exit 1 con `--strict` si `is_valid=False`.

## Hard guarantees

1. **Read-only sobre capas previas.** No muta artifact ni agent_input.
2. **Determinismo bit-a-bit.** Mismos inputs → mismo `registry_id` y mismo `verification_hash`.
3. **Clock-isolated.** El clock sólo afecta `derived_at` / `verified_at`, no las firmas.
4. **No persistence, no network, no LLM.** Templating template-driven heredado de ADR-0033.
5. **Removible.** Borrar `analytics/claims/` y los dos subcomandos del CLI no rompe nada.

## Alineación con ADR-0000

Refuerza pilares 1, 2, 3, 4, 5 (transparencia, integridad, reproducibilidad, ausencia de magia, auditoría granular). Profundiza ADR-0020 (honesty pattern) y ADR-0031 (verifiable evidence bundle): ahora cada **frase** del agente es content-addressable y revocable individualmente.

## Alternativas consideradas

- **Persistir registry como Parquet.** Rechazada: viola "removible", agrega persistencia no necesaria en v0.1.
- **Claim multi-evidence ya en v0.1.** Rechazada: complica la 1:1 trivial del template_explanation_v01. Aplazada a v0.2.
- **Verifier que lanza excepciones.** Rechazada: rompe el patrón establecido en ADR-0034 (verifier nunca lanza, siempre devuelve reporte).
- **Persistir verification_report.** Rechazada: el reporte es derivable bit-a-bit; persistirlo sería duplicación.

## Consecuencias

- Auditoría granular: cada claim individualmente verificable y revocable.
- Lookup bidireccional materializado: O(1) en ambos sentidos.
- Cierra Fase 5. Próximas capas (revocation log, audit-pack) pueden construir sobre este registry sin re-derivarlo.

## Métricas

- 5 archivos nuevos en `src/orbital_sentinel/analytics/claims/`.
- 19 finding_type literales (contrato cerrado).
- 9 checks individuales booleanos en `ClaimVerificationReport`.
- 0 nuevas dependencias.
