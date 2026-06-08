# ADR-0037: Evidence Chain Layer v1

**Estado:** Aceptado
**Fecha:** 2026-06-07
**Relacionado con:** ADR-0000, ADR-0010, ADR-0020, ADR-0029, ADR-0031, ADR-0032, ADR-0033, ADR-0035, ADR-0036

## Contexto

Tras ADR-0036 existen seis capas verificables conectadas por identificadores content-addressable:

```
raw_evidence
  → evidence_bundle
    → agent_input
      → explanation_artifact
        → claim_registry
          → hypothesis_registry
```

Cada capa preserva trazabilidad hacia su upstream, pero no existe un único artefacto que **materialice estructuralmente la cadena completa**. Para auditar una hipótesis hoy hay que cargar seis archivos y validar manualmente los IDs. Eso es frágil, no portable y no detecta ataques de re-vinculación cruzada entre cadenas distintas.

## Decisión

Introducir una **Evidence Chain Layer v1** que produce un objeto verificable `EvidenceChain` que materializa los enlaces estructurales entre los seis artefactos. La cadena **no embebe payloads** (eso es rol de ADR-0038); registra sólo `link_type`, `link_id`, `link_signature` y `upstream_link_id` por nodo. Cada nodo es content-addressable y la cadena entera tiene un `chain_id ≡ chain_hash`.

### Modelos (Pydantic v2, frozen, `extra="forbid"`)

- `EvidenceChainNode`: `link_type` ∈ `CANONICAL_CHAIN_ORDER`, `link_id`, `link_signature`, `upstream_link_id`, `node_hash`. Hard invariant: `node_hash` recomputa.
- `EvidenceChain`: `chain_id ≡ chain_hash`, source IDs de las cinco capas inferiores, `raw_evidence_ids` (set canónico-ordenado), `nodes`, `n_nodes`, `chain_emit_reason` ∈ {`full_chain`, `empty_chain`}, versioning, `derived_at`.
- `ChainVerificationFinding`: contrato cerrado con **15 finding_type literales**.
- `ChainVerificationReport`: `is_valid`, contadores, **6 checks individuales booleanos**, `findings`, `verification_hash`.

### Orden canónico v1

```python
CANONICAL_CHAIN_ORDER = (
    "raw_evidence",
    "evidence_bundle",
    "agent_input",
    "explanation_artifact",
    "claim_registry",
    "hypothesis_registry",
)
```

Cualquier cadena que no respete este orden es inválida.

### Builder (`build_evidence_chain`)

Función pura. Valida que los IDs cross-layer encadenen correctamente; si no → `EvidenceChainBuilderError`. Si el bundle está vacío → cadena vacía. En caso normal: construye los seis nodos consecutivos con `upstream_link_id` apuntando al `link_id` del nodo previo. El nodo `raw_evidence` usa como `link_id` un SHA-256 sobre los `evidence_ids` ordenados (no es un artefacto persistido pero sí un identificador content-addressable del conjunto).

### Verifier (`verify_evidence_chain`)

Función pura, **nunca lanza**. Ejecuta 6 categorías de checks:
1. Alias `chain_id == chain_hash`.
2. `n_nodes` coherente.
3. `chain_layer_engine_version` esperado.
4. Recomputo de cada `node_hash`.
5. Orden canónico respetado.
6. Coherencia de cada link: `link_id` y `link_signature` coinciden con el artefacto externo correspondiente, `upstream_link_id` apunta al nodo previo. `raw_evidence_ids` se corresponden bit-a-bit con `bundle.evidence_payloads`.

`verification_hash = SHA-256(chain_id | is_valid | n_nodes_verified | n_findings | verifier_engine_version)`.

### CLI

- `orbital-sentinel evidence-chain <hypothesis_registry|-> --claim-registry-file <path> --explanation-artifact-file <path> --agent-input-file <path>`
- `orbital-sentinel verify-evidence-chain <chain|-> --hypothesis-registry-file <path> --claim-registry-file <path> --explanation-artifact-file <path> --agent-input-file <path> [--strict]`

## Hard guarantees

1. **No embebe payloads.** La cadena es liviana; los payloads viven en ADR-0038.
2. **Detecta swap entre cadenas.** Un nodo `claim_registry` con `link_id` correcto pero `link_signature` ajeno es detectado.
3. **Detecta enlaces rotos.** Si el `upstream_link_id` del nodo `agent_input` no coincide con el `link_id` del nodo `evidence_bundle`, finding emitido.
4. **Determinismo bit-a-bit.**
5. **Clock-isolated.**
6. **Removible.**

## Alineación con ADR-0000

Cumple la pregunta central del proyecto: *¿qué está ocurriendo y cómo podemos demostrarlo?* La cadena es la materialización estructural de "cómo podemos demostrarlo": cada hipótesis tiene un object explícito que enumera los seis eslabones y permite a cualquier auditor recorrer la cadena hacia atrás sin acceso a la instancia origen.

## Alternativas consideradas

- **Cadena con payloads embebidos.** Rechazada: viola separación de responsabilidades. Esa funcionalidad pertenece al `InvestigationCase` (ADR-0038).
- **Múltiples cadenas paralelas por claim.** Rechazada para v1; la cadena es a nivel de artefacto, no de claim individual. La trazabilidad fina hypothesis→claims→evidence ya vive en los registries.
- **Persistir cadena como Parquet.** Rechazada: viola "removible".

## Consecuencias

- Auditoría extremo a extremo en un único objeto verificable.
- Base estructural para el `InvestigationCase` portable (ADR-0038).
- Detección automática de manipulación cross-layer.

## Métricas

- 5 archivos nuevos en `src/orbital_sentinel/analytics/evidence_chains/`.
- 15 finding_type literales.
- 6 checks individuales booleanos.
- 0 nuevas dependencias.
