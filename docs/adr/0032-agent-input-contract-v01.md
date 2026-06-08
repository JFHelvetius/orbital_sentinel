# ADR-0032: Agent Input Contract v0.1

**Estado:** Aceptado
**Fecha:** 2026-06-06
**Relacionado con:** ADR-0000, ADR-0010, ADR-0020, ADR-0029, ADR-0030, ADR-0031

## Decisión

Frontera estructural determinista → no determinista. Un `AgentInput` es un `EvidenceBundle` que pasó `verify_bundle` y declara su `ConsumerClass` destinataria.

### Modelos

`AgentInput` (frozen, extra="forbid"): `agent_input_id`, `bundle`, `verification_report`, `declared_consumer_class`, `contract_schema_version`, `contract_engine_version`, `contract_acceptance_at`.

`ConsumerClass = Literal["explanation_agent_v01", "report_exporter_v01", "external_third_party_v01", "api_endpoint_v01", "audit_consumer_v01"]`.

### Hard invariant

`verification_report.is_valid == True` y `verification_report.bundle_id == bundle.bundle_id` — enforced por model_validator.

### Identidad

`agent_input_id = SHA-256(bundle_id | declared_consumer_class | contract_engine_version)`.

### Builder

`build_agent_input(bundle, *, declared_consumer_class, clock)`. Ejecuta `verify_bundle`. Si `is_valid=False` → lanza `AgentInputRejectedError` con `verification_report` adjunto.

### CLI

`orbital-sentinel agent-input <bundle_file|-> --consumer-class <name>`. Exit 1 con report en stderr si bundle rechazado.

## Restricciones absolutas

Sin LLM, ML, AI, NLP, embeddings, clasificación, scoring, probabilidades, threat levels, recomendaciones, persistencia, dependencias nuevas, RNG, wall clock en lógica semántica. Detectores, EvidenceCatalog, ExplanationContext, EvidenceBundle, BundleVerification intactos.
