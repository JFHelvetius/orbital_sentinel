# ADR-0034: Explanation Verification Layer v0.1

**Estado:** Aceptado
**Fecha:** 2026-06-06
**Relacionado con:** ADR-0000, ADR-0010, ADR-0020, ADR-0031, ADR-0032, ADR-0033

## Decisión

Capa determinista que valida estructuralmente un `ExplanationArtifact` contra su `AgentInput`. Cierra el ciclo de auditoría del pipeline completo: `bundle → agent-input → explain → verify-explanation`.

### Modelo

`ExplanationVerificationReport` (frozen, extra="forbid"): `explanation_id`, `bundle_id`, `agent_input_id`, `is_valid`, contadores agregados, 8 checks individuales booleanos, `findings: list[ExplanationVerificationFinding]`, `verification_hash`, versioning, `verified_at`.

`ExplanationVerificationFinding`: contrato cerrado con 10 `finding_type` literales (`evidence_id_not_in_bundle`, `audit_bundle_id_mismatch`, `source_bundle_id_mismatch`, etc.).

### Hard guarantees

- Nunca muta.
- Nunca lanza por integridad rota.
- Siempre retorna `ExplanationVerificationReport`.

### Checks ejecutados

1. Cada `referenced_evidence_id` existe en `bundle.evidence_payloads`.
2. `referenced_evidence_ids == audit.evidence_ids_used`.
3. `explanation_id` recomputa correctamente a partir de los campos content-addressable.
4. `audit.explanation_id == artifact.explanation_id`.
5. `audit.bundle_id == artifact.source_bundle_id`.
6. `audit.agent_input_id == artifact.source_agent_input_id`.
7. `metadata.prompt_hash == audit.prompt_hash`.
8. `artifact.source_bundle_id == agent_input.bundle.bundle_id`.
9. `artifact.source_agent_input_id == agent_input.agent_input_id`.

`verification_hash = SHA-256(explanation_id | bundle_id | agent_input_id | is_valid | referenced_evidence_count | verifier_engine_version)`.

### CLI

`orbital-sentinel verify-explanation <artifact_file|-> --agent-input-file <path> [--strict]`. Exit 1 con `--strict` si `is_valid=False`.
