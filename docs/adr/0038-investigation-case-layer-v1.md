# ADR-0038: Investigation Case Layer v1

**Estado:** Aceptado
**Fecha:** 2026-06-07
**Relacionado con:** ADR-0000, ADR-0010, ADR-0020, ADR-0031, ADR-0032, ADR-0033, ADR-0035, ADR-0036, ADR-0037

## Contexto

Tras ADR-0037 el sistema posee:

* Evidencia derivada verificable (`DerivedEvidence`).
* Bundles autocontenidos (`EvidenceBundle`).
* Contratos de input para agentes (`AgentInput`).
* Explicaciones template-driven (`ExplanationArtifact`).
* Claims atómicos (`VerifiableClaim`/`ClaimRegistry`).
* Hipótesis composicionales (`HypothesisRegistry`).
* Cadenas verificables extremo a extremo (`EvidenceChain`).

Lo que aún no existe: una **unidad de trabajo portable** que un analista pueda exportar a un USB, enviar por correo, archivar y un tercero pueda recibir, abrir y reverificar sin acceso al instancia origen. La `EvidenceChain` referencia los seis artefactos por hash; el `InvestigationCase` los **empaqueta literalmente** en un único objeto autoverificable.

## Decisión

Introducir el **Investigation Case Layer v1**: un objeto `InvestigationCase` que embebe los seis payloads completos (`EvidenceChain`, `HypothesisRegistry`, `ClaimRegistry`, `ExplanationArtifact`, `AgentInput`, `EvidenceBundle`) junto con sus identificadores content-addressable y una firma global que cubre todo el caso. Sigue el mismo patrón portable que `EvidenceBundle` (ADR-0031).

NO es una base de datos. NO es persistencia externa. NO es networking. Es un artefacto derivado verificable que el caller serializa y deserializa libremente.

### Modelos (Pydantic v2, frozen, `extra="forbid"`)

- `InvestigationCase`:
  - `case_id ≡ case_signature` (alias estricto)
  - `case_label` (template determinístico) + `case_label_hash` (SHA-256 utf-8)
  - `referenced_*_id` × 6 (chain/hypothesis_registry/claim_registry/explanation/agent_input/bundle)
  - `chain`, `hypothesis_registry`, `claim_registry`, `explanation_artifact`, `agent_input`, `evidence_bundle` (payloads completos embebidos)
  - `case_emit_reason` ∈ {`full_case`, `empty_case`}
  - versioning, `derived_at`
- `CaseVerificationFinding`: contrato cerrado con **19 finding_type literales**.
- `CaseVerificationReport`: `is_valid`, contadores, **7 checks individuales booleanos**, `findings`, `verification_hash`.

### Builder (`build_investigation_case`)

Función pura. Valida coherencia cross-layer entre los 6 artefactos (8 igualdades de IDs). Si falla → `InvestigationCaseBuilderError`. Genera el label template:

```
Investigation case for object {object_id}: {n_h} hypothesis(es) from {n_c} claim(s) over {n_e} evidence record(s).
```

`case_signature = SHA-256(chain_id | hr_id | cr_id | exp_id | ai_id | bundle_id | label_hash | engine_version)`.

### Verifier (`verify_investigation_case`)

Función pura, **nunca lanza**. Ejecuta 7 categorías de checks:
1. Alias `case_id == case_signature`.
2. `case_label_hash` recomputa desde `case_label`.
3. `case_signature` recomputa.
4. IDs referenciados coinciden con IDs de los payloads embebidos.
5. La `EvidenceChain` embebida apunta a los otros 5 payloads embebidos (no swap).
6. Pipeline cross-layer coherente entre los 5 artefactos no-chain.
7. `case_layer_engine_version` esperado.

`verification_hash = SHA-256(case_id | is_valid | n_artifacts_verified | n_findings | verifier_engine_version)`.

### CLI

- `orbital-sentinel investigation-case <chain|-> --hypothesis-registry-file --claim-registry-file --explanation-artifact-file --agent-input-file --bundle-file`
- `orbital-sentinel verify-investigation-case <case|-> [--strict]`

El verifier no necesita argumentos externos: el caso es autocontenido. Esa es la propiedad clave.

## Hard guarantees

1. **Autocontenido.** Un caso emitido en máquina A puede verificarse en máquina B sin red, sin acceso a la instancia origen, sin storage compartido.
2. **No introduce persistencia nueva.** El caso se serializa como cualquier otro objeto JSON; el storage es responsabilidad del caller.
3. **Cualquier modificación de cualquier payload embebido es detectada** por los hard invariants de Pydantic + recomputo del verifier.
4. **Determinismo bit-a-bit.**
5. **Clock-isolated.**
6. **Removible.**

## Alineación con ADR-0000

El `InvestigationCase` es la materialización última de la pregunta central del proyecto. Hace **portable y reproducible** una conclusión orbital: cualquier consumidor recibe el caso, lo deserializa y ejecuta `verify-investigation-case` para confirmar que todos los enlaces siguen siendo consistentes y que ningún payload fue modificado tras la emisión.

Es la unidad mínima de intercambio entre analistas que protege la propiedad fundamental del proyecto: *cualquier conclusión puede auditarse independientemente*.

## Alternativas consideradas

- **Solo IDs sin payloads embebidos.** Rechazada: la portabilidad sería falsa (requeriría acceso a la instancia origen para cargar los payloads).
- **Múltiples cadenas en un caso.** Rechazada para v1 (un caso = una hipótesis raíz). Aplazada a v2 si se valida la necesidad.
- **Persistir caso como Parquet/SQLite.** Rechazada: viola "no introducir persistencia nueva". JSON es suficiente.
- **Firmar con clave asimétrica.** Rechazada: añadiría dependencias y gestión de claves. La firma content-addressable es suficiente para detectar manipulación; la autenticación de origen es un problema ortogonal.

## Consecuencias

- Cierra Fase 6: Orbital Sentinel pasa de "explicaciones verificables" a "plataforma de investigación verificable extremo a extremo".
- Hace posible flujos de trabajo entre analistas sin infraestructura compartida.
- Establece la base estructural para futuros formatos de revocación / contraprueba que actuarían sobre `case_id`.

## Métricas

- 5 archivos nuevos en `src/orbital_sentinel/analytics/investigations/`.
- 19 finding_type literales.
- 7 checks individuales booleanos.
- 6 artefactos embebidos por caso.
- 0 nuevas dependencias.
