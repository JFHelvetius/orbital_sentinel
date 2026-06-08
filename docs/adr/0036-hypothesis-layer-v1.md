# ADR-0036: Hypothesis Layer v1

**Estado:** Aceptado
**Fecha:** 2026-06-07
**Relacionado con:** ADR-0000, ADR-0010, ADR-0020, ADR-0031, ADR-0032, ADR-0033, ADR-0034, ADR-0035

## Contexto

Tras ADR-0035 todas las afirmaciones del sistema son verificables individualmente. Sin embargo, una explicación coherente está compuesta normalmente por múltiples claims relacionados (varios eventos del mismo objeto, varios indicios del mismo tipo de fenómeno). La unidad mínima auditable hoy es el `VerifiableClaim`; falta una estructura explícita que **agrupe múltiples claims existentes** en una hipótesis composicional, sin generar contenido nuevo.

## Decisión

Introducir una **Hypothesis Layer v1** que opera *después* del `ClaimRegistry`, agrupando deterministamente los claims existentes en `Hypothesis` objects. La capa es **read-only sobre claims**, **content-addressable**, **determinista bit-a-bit**, **stdlib-only**, completamente removible.

### Modelos (Pydantic v2, frozen, `extra="forbid"`)

- `Hypothesis`: `hypothesis_id` (sha256), `source_claim_registry_id`, `hypothesis_index` (≥0), `grouping_key` (clave determinística), `supporting_claim_ids` (min_length=1), `hypothesis_label`, `schema_version`. Hard invariant: `hypothesis_id` recomputa.
- `HypothesisRegistry`: `registry_id ≡ registry_hash` (alias estricto), source IDs (`source_claim_registry_id`, `source_bundle_id`, `source_agent_input_id`, `source_explanation_id`, `source_model_identifier`, `source_claim_layer_engine_version`), `n_hypotheses`, `hypotheses`, `hypothesis_to_claim_index` (forward), `claim_to_hypothesis_index` (reverse), `registry_emit_reason` ∈ {`claim_registry_populated`, `empty_claim_registry`}, versioning, `derived_at`.
- `HypothesisVerificationFinding`: contrato cerrado con **19 finding_type literales**.
- `HypothesisVerificationReport`: `is_valid`, contadores, **8 checks individuales booleanos**, `findings`, `verification_hash`.

### Modelo de agrupación v1

`template_hypothesis_grouping_v01`: agrupa los claims que comparten el mismo par `(object_id, evidence_type)` derivado de la `BundledEvidence` referenciada por el primer `supporting_evidence_id` de cada claim. No usa NLP, ML ni inferencia: es una operación determinista sobre metadata estructural ya presente.

Etiqueta template determinística:

```
Object {object_id} exhibits {evidence_type} evidence ({n} claim/claims).
```

### Builder (`build_hypothesis_registry`)

Función pura. Valida:
1. `claim_registry.source_bundle_id == agent_input.bundle.bundle_id`.
2. `claim_registry.source_agent_input_id == agent_input.agent_input_id`.

Si falla cualquiera → `HypothesisRegistryBuilderError`.

Si `claim_registry.claims` está vacío → emite registry con `n_hypotheses=0` y `registry_emit_reason="empty_claim_registry"`.

En caso normal: agrupa claims por `(object_id, evidence_type)`, construye `Hypothesis` por grupo (orden estable por primera aparición), materializa forward index (keys sorted) y reverse index (keys y values sorted).

### Verifier (`verify_hypothesis_registry`)

Función pura, **nunca lanza**. Ejecuta 8 categorías de checks:
1. Source IDs match (claim_registry, bundle, agent_input).
2. Model identifier soportado.
3. `n_hypotheses` coherente.
4. Hard invariant `registry_id == registry_hash`.
5. Per-hypothesis: `hypothesis_id` recomputa, supporting no vacío, claims existen en registry, índice único, id único, label coherente con template, grouping_key coherente con evidencia real.
6. `hypothesis_index` secuencial 0..N-1.
7. Forward/reverse indices coherentes y claves consistentes.
8. Cobertura: todos los claims existentes están referenciados por alguna hipótesis.

`verification_hash = SHA-256(registry_id | is_valid | n_hypotheses_verified | n_findings | verifier_engine_version)`.

### CLI

- `orbital-sentinel hypothesis-registry <claim_registry|-> --agent-input-file <path>`
- `orbital-sentinel verify-hypothesis-registry <registry|-> --claim-registry-file <path> --agent-input-file <path> [--strict]`

## Hard guarantees

1. **Read-only sobre capas previas.** No muta nada.
2. **Determinismo bit-a-bit.** Mismos inputs → mismo `registry_id` y `verification_hash`.
3. **Clock-isolated.** El clock sólo afecta `derived_at` / `verified_at`.
4. **No persistence, no network, no LLM, no inferencia.** Agrupación basada únicamente en metadata estructural.
5. **Removible.** Borrar `analytics/hypotheses/` y los dos subcomandos del CLI no rompe nada.

## Alineación con ADR-0000

Refuerza pilares 1-5 (transparencia, integridad, reproducibilidad, ausencia de magia, auditoría granular). Una hipótesis es una **composición declarada**, no una conclusión inferida: la unidad de análisis crece sin perder la trazabilidad atómica.

## Alternativas consideradas

- **Agrupación por NLP sobre `claim_text`.** Rechazada: viola la prohibición de inferencia.
- **Permitir hipótesis cross-objeto.** Rechazada para v1 (complica grouping_key). Aplazada a v2.
- **Persistir registry como Parquet.** Rechazada: viola "removible".

## Consecuencias

- Unidad de análisis composicional sin abandonar el paradigma verificable.
- Lookup bidireccional hypothesis↔claim materializado.
- Permite construir capas superiores (Evidence Chain Layer en ADR-0037) que tratan la hipótesis como punto de entrada de auditoría.

## Métricas

- 5 archivos nuevos en `src/orbital_sentinel/analytics/hypotheses/`.
- 19 finding_type literales (contrato cerrado).
- 8 checks individuales booleanos.
- 0 nuevas dependencias.
