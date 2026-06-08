# ADR-0033: Explanation Agent v0.1

**Estado:** Aceptado
**Fecha:** 2026-06-06
**Relacionado con:** ADR-0000, ADR-0010, ADR-0020, ADR-0031, ADR-0032

## Decisión

Primer agente explicativo del proyecto. Toma un `AgentInput` verificado y produce un `ExplanationArtifact` por **concatenación determinista de plantillas factuales** sobre la evidencia embebida.

### Restricción central

El agente:

- **NO** detecta, clasifica, puntúa, especula, infiere causas, completa huecos, genera hipótesis.
- **NO** crea evidencia nueva; **NO** modifica evidencia.
- Solo **explica evidencia existente** siguiendo el patrón "Evidence says X", nunca "X probably means Y".

`model_identifier = "template_explanation_v01"`. Cero LLM, cero ML, cero IA.

### Modelos

`ExplanationArtifact` (frozen, extra="forbid"): `explanation_id`, `source_agent_input_id`, `source_bundle_id`, `referenced_evidence_ids`, `explanation_text`, `generation_metadata`, `audit_record`, `schema_version`, `explanation_engine_version`, `generated_at`.

`ExplanationGenerationMetadata`: `model_identifier`, `generation_method`, `prompt_hash`, `n_evidence_processed`.

`ExplanationAuditRecord`: `explanation_id`, `agent_input_id`, `bundle_id`, `evidence_ids_used`, `generation_timestamp`, `prompt_hash`, `model_identifier`.

### Hard invariants

- `referenced_evidence_ids == audit_record.evidence_ids_used`.
- `audit_record.explanation_id == artifact.explanation_id`.
- `explanation_id = SHA-256(source_agent_input_id | source_bundle_id | prompt_hash | explanation_engine_version)`.
- `prompt_hash = SHA-256(all_templates_canonical() | engine_version)`.

### Determinismo

La explicación es **plenamente determinista en v0.1**. Mismo `AgentInput` + mismo clock → mismo `ExplanationArtifact` bit-exacto (excluyendo `generated_at`). El campo `model_identifier` permite distinguir versiones futuras que pudieran introducir no determinismo, exigiendo nuevo ADR.

### Plantillas

Una plantilla por `evidence_type`. Cada plantilla extrae solo campos ya presentes en el `honesty_payload` del `DerivedEvidence`. Incluye explícitamente `is_apparent_not_confirmed=True` en cada línea.

### CLI

`orbital-sentinel explain <agent_input_file|->`.
