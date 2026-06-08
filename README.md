# Orbital Sentinel

> Plataforma open source para observar, propagar y razonar sobre la población satelital usando exclusivamente datos abiertos, con honestidad sobre incertidumbre.

**Estado del proyecto:** **Fase 1 y Fase 2 cerradas (2026-06-06).** El primer ciclo arquitectónico Raw → Normalized → Derived (on-demand + persistido) está completo, con su mecanismo analítico fundamental (conjunciones + Pc) honestamente declarado.

## Sobre este repositorio

Orbital Sentinel es un proyecto de horizonte largo (5+ años) cuyo primer artefacto no es código sino un cuerpo de decisiones arquitectónicas explícitas. Antes de escribir la primera línea, queremos saber por qué la estamos escribiendo, qué propiedades del sistema no podrá violar nunca y bajo qué condiciones el proyecto debería archivarse dignamente.

Toda esa conversación vive en [docs/adr/](docs/adr/). Si quieres entender el proyecto, ese es el único lugar donde empezar.

## Hoja de ruta a alto nivel

El proyecto se desarrolla en cinco fases, cada una funcional y demostrable:

1. **Observabilidad orbital** — ingesta de TLEs, propagación SGP4, visualización 3D.
2. **Conjunciones y proximidad** — screening masivo y probabilidad de colisión.
3. **Detección de maniobras** — saltos en elementos medios y residuos de propagación.
4. **Sistema de anomalías** — features sobre series temporales y modelos por familia orbital.
5. **Agente explicativo** — LLM que razona sobre por qué algo se detectó como anómalo.

El detalle vive en los ADRs.

## Estado actual

### Fase 1 — Observabilidad orbital · cerrada 2026-06-06

Cubierta por componentes implementados y verificados:

- **Ingesta**: `CelesTrakSource` con cache content-addressable + `IngestPipeline` (fetch → Raw → normalize → Normalized).
- **Propagación SGP4**: `Sgp4Propagator` con golden master contra librería de referencia y trazabilidad Raw → Normalized → Derived.
- **Visualización**: `plot_groundtrack` 2D estático (PNG) con caption explícito del régimen de incertidumbre. ADR-0008 Cesium queda reservado para 3D interactivo Fase 2+.
- **CLI**: `orbital-sentinel ingest`, `propagate`, `plot-groundtrack`.
- **Validación arquitectónica**: 197 tests, benchmark DuckDB+Parquet decidido (ADR-0004 enmienda 2), integridad referencial verificable (`verify_integrity()`).

Cierre formal en [ADR-0015](docs/adr/0015-phase-1-closure.md).

### Fase 2 — Conjunciones y proximidad · cerrada 2026-06-06

Cubierta por componentes implementados y verificados en 5 incrementos:

- **v0.1 — Pairwise** ([ADR-0016](docs/adr/0016-conjunction-analysis-v01.md)): análisis entre dos NORAD IDs con doble FK provenance y régimen de precisión declarado en cada resultado.
- **v0.2 — TCA refinement** ([ADR-0017](docs/adr/0017-tca-refinement-v02.md)): bisección sobre `f(t) = (r·v)`, resolución de TCA pasa de minutos a 1 segundo.
- **v0.3 — N-to-N screening** ([ADR-0018](docs/adr/0018-pairwise-screening-v03.md)): mass screening con filtro apogeo/perigeo O(1) por par + cap defensivo `max_pairs`.
- **v0.4 — Persistencia** ([ADR-0019](docs/adr/0019-conjunction-detections-persistence.md)): **primera tabla Derived persistente** en Parquet, content-addressable, integridad cross-layer verificable.
- **v1.0 — Pc con covarianza declarada** ([ADR-0020](docs/adr/0020-probability-of-collision-v1.md)): probabilidad de colisión con 7 assumption fields obligatorios. **Caso prototípico** de cumplimiento del principio P2 (honestidad sobre incertidumbre) en un componente que tradicionalmente miente.

CLI: `orbital-sentinel conjunction`, `screen [--persist] [--combined-radius-km]`, `detections [--norad]`.

Cierre formal en [ADR-0021](docs/adr/0021-phase-2-closure.md).

### Observatory Layer v1 · cerrada 2026-06-06

Primera capa observer-centric: el sistema responde preguntas operativas reales del cielo desde la línea de comandos, sin red, sin persistencia nueva, sin Cesium.

- **Pass prediction** ([ADR-0023](docs/adr/0023-pass-prediction-v01.md)): AOS / culminación / LOS / max-elevation / azimuth para un satélite sobre un observador geográfico. Bisección AOS/LOS + ajuste parabólico para culminación. 5 enmiendas integradas.
- **Solar geometry** ([ADR-0024](docs/adr/0024-solar-geometry-v01.md)): posición solar analítica Vallado §5.1, clasificación USNO de twilight, iluminación satelital por sombra cilíndrica. Cero dependencias externas.
- **Observatory scan** ([ADR-0025](docs/adr/0025-observatory-scan-v01.md)): agregación multi-satélite con pre-filtro geométrico O(1), filtro de "pase útil" combinando twilight + illumination + min-elevation, ranking declarado y detección de conflictos simultáneos.

CLI: `orbital-sentinel passes`, `scan [--require-twilight --require-illuminated]`, `best --criterion`, `conflicts`.

Cierre formal en [ADR-0026](docs/adr/0026-observatory-layer-v1-closure.md).

### Fase 3 — Detección de maniobras · v0.1 entregada 2026-06-06

Primer detector estadístico del proyecto. Z-score sobre rates de cambio (Δ/Δt) en mean motion, eccentricity e inclination contra una baseline temporal deslizante. Cada `ManeuverEvent` declara `is_apparent_not_confirmed=True`: detectamos saltos aparentes, no confirmamos maniobras (extensión del patrón ADR-0020 al dominio estadístico).

- **Catalog extension**: `OrbitalElementsRepository.find_all_by_norad_id` ordena por epoch ascendente.
- **Time-series**: `OrbitalElementSeries.from_elements()` con validación estricta (mismo NORAD, epochs monotónos, hashes únicos).
- **Detector**: `detect_maneuvers(series, *, baseline_window_days, detection_threshold_sigma, min_baseline_samples)`.
- **CLI**: `orbital-sentinel maneuvers <norad_id> [--baseline-days N] [--threshold-sigma S]`.

Razonamiento completo en [ADR-0027](docs/adr/0027-maneuver-detection-v01.md). V0.1 verifica correctitud del algoritmo sobre series sintéticas; utilidad operacional requiere ingesta histórica acumulada (lo decimos explícito).

### Fase 4 — Detección de anomalías observacionales · v0.1 entregada 2026-06-06

Primer detector observacional general. Z-score sobre el VALOR de features físicas (altitude, eccentricity, inclination, mean_motion) contra una baseline temporal del propio objeto. Distinto de ADR-0027 (que mide *rates*): aquí medimos el *valor* desviado de su historia reciente.

ADR-0028 prohíbe explícitamente lenguaje interpretativo. El detector responde exclusivamente: *"¿Qué features del objeto se desvían significativamente de su propia historia reciente?"* Sin causa, sin intención, sin clasificación, sin riesgo, sin confianza, sin probabilidad. El operador humano asigna significado.

- **Detector**: `detect_anomalies(series, *, features, baseline_window_days, threshold_sigma, min_baseline_samples)`.
- **CLI**: `orbital-sentinel anomalies <norad_id> [--baseline-days N] [--threshold-sigma S]`.

Razonamiento y prohibiciones en [ADR-0028](docs/adr/0028-anomaly-detection-v01.md).

### Derived Evidence Layer · v0.1 entregada 2026-06-06

Primera capa de consolidación read-only. Toma outputs de los tres detectores estadísticos (conjunciones, maniobras, anomalías) y los proyecta en un modelo común con `honesty_payload` preservado. La capa **no clasifica**, **no infiere causas**, **no asigna probabilidades** — solo garantiza que los campos críticos del detector upstream sobrevivan downstream.

- **Modelo**: `DerivedEvidence` (frozen, `evidence_id` content-addressable SHA-256).
- **Catálogo**: `EvidenceCatalog` inmutable con filtros por NORAD, detector y rango temporal.
- **Builders**: `build_maneuver_evidence`, `build_anomaly_evidence`, `build_conjunction_evidence`.
- **CLI**: `orbital-sentinel evidence <norad_id> [--from] [--to] [--detector]`.

El sistema responde *"¿qué evidencia existe sobre este objeto?"* sin intentar responder *"¿qué significa?"*. Razonamiento y prohibiciones en [ADR-0029](docs/adr/0029-derived-evidence-layer-v01.md).

### Explanation Context Layer · v0.1 entregada 2026-06-06

Última capa determinista y libre de IA antes del futuro Agente Explicativo. Proyecta un `EvidenceCatalog` en una vista estructurada `ExplanationContext` con `context_id` content-addressable, `source_catalog_signature` reproducible, `evidence_references` con `honesty_payload_hash` para verificación de integridad, `detector_summaries` siempre completo (los 3 detectores canónicos), `timeline` consolidado y `evidence_type_counts`. La capa **no interpreta**, **no clasifica**, **no usa IA**.

- **Modelos**: `ExplanationContext`, `ExplanationEvidenceReference`, `ExplanationDetectorSummary`, `ExplanationTimeline`, `ExplanationTimelineEntry`.
- **Helpers**: `compute_payload_hash`, `compute_source_catalog_signature`, `compute_context_id`.
- **Builder**: `build_explanation_context(catalog, *, object_id)`.
- **CLI**: `orbital-sentinel context <norad_id> [--from] [--to] [--detector]`.

Razonamiento y prohibiciones en [ADR-0030](docs/adr/0030-explanation-context-layer-v01.md).

### Verifiable Evidence Bundle Layer · v0.1 entregada 2026-06-06

Última capa pre-LLM. Empaqueta `ExplanationContext` + cada `DerivedEvidence` referenciado (payload completo) en un artefacto autocontenido y verificable offline por cualquier tercero sin acceso a la instancia origen. Cierra el bucle de honestidad iniciado en ADR-0020: las afirmaciones de integridad se vuelven **pruebas verificables**.

Invariante hard: `bundle_id == bundle_signature` (model_validator enforced). Una sola identidad content-addressable.

- **Modelos**: `EvidenceBundle`, `BundledEvidence`, `BundleVerificationReport`, `BundleIntegrityFailure`.
- **Helpers**: `compute_bundle_signature`, `compute_bundle_payload_signature`, `compute_payload_hash`, `canonical_json`.
- **API**: `build_evidence_bundle(context, catalog)`, `verify_bundle(bundle)` (nunca lanza).
- **CLI**: `orbital-sentinel bundle <norad>` y `orbital-sentinel verify-bundle <file|-> [--strict]`.

Razonamiento y prohibiciones en [ADR-0031](docs/adr/0031-verifiable-evidence-bundle-layer-v01.md).

### Agent Input Contract · v0.1 entregada 2026-06-06

Contrato de entrada genérico para todo consumidor del bundle (humano, LLM, motor de reglas). Empaqueta `EvidenceBundle` + declaración de `consumer_class` + `prompt_envelope` reproducible. `agent_input_id` content-addressable. Razonamiento en [ADR-0032](docs/adr/0032-agent-input-contract-v01.md).

### Explanation Agent · v0.1 entregada 2026-06-06

Agente template-driven (no LLM) que consume `AgentInput` y emite `ExplanationArtifact` con `explanation_text` mecánico ("Evidence says X"), `referenced_evidence_ids` y `audit_record` content-addressable. Cero interpretación. Cero ML. Razonamiento en [ADR-0033](docs/adr/0033-explanation-agent-v01.md).

### Explanation Verification Layer · v0.1 entregada 2026-06-06

Verificador del `ExplanationArtifact` contra su `AgentInput`. Función pura, nunca lanza, ejecuta 9 checks, emite `ExplanationVerificationReport` con `verification_hash` reproducible. CLI: `orbital-sentinel verify-explanation`. Razonamiento en [ADR-0034](docs/adr/0034-explanation-verification-layer-v01.md).

### Verifiable Claim Layer · v0.1 entregada 2026-06-07

Atomiza `ExplanationArtifact.explanation_text` en `VerifiableClaim` objects con `claim_id` content-addressable y `supporting_evidence_ids` enlazados al bundle. Materializa forward index (claim → evidence) y reverse index (evidence → claim) para lookup bidireccional O(1). Hard invariant: `registry_id == registry_hash` (alias estricto, model_validator).

- **Modelos**: `VerifiableClaim`, `ClaimRegistry`, `ClaimVerificationFinding` (19 finding_type literales), `ClaimVerificationReport` (9 checks individuales booleanos).
- **API**: `build_claim_registry(artifact, agent_input)` (pure, raises on inconsistency), `verify_claim_registry(registry, agent_input, artifact)` (pure, never raises).
- **CLI**: `orbital-sentinel claim-registry <artifact|-> --agent-input-file <path>`, `orbital-sentinel verify-claim-registry <registry|-> --agent-input-file <path> --explanation-artifact-file <path> [--strict]`.

Cierra Fase 5: cada frase del agente es individualmente auditable y revocable. Razonamiento en [ADR-0035](docs/adr/0035-verifiable-claim-layer-v01.md).

### Hypothesis Layer · v1 entregada 2026-06-07

Agrupa los `VerifiableClaim` existentes en `Hypothesis` composicionales sin generar contenido nuevo. El builder determinista `template_hypothesis_grouping_v01` agrupa claims que comparten el mismo `(object_id, evidence_type)` derivado de la evidencia subyacente. Hard invariant: `registry_id == registry_hash`. Forward index hypothesis→claims y reverse index claim→hypotheses materializados.

- **API**: `build_hypothesis_registry(claim_registry, agent_input)`, `verify_hypothesis_registry(registry, claim_registry, agent_input)` (nunca lanza).
- **CLI**: `orbital-sentinel hypothesis-registry`, `orbital-sentinel verify-hypothesis-registry`.

Razonamiento en [ADR-0036](docs/adr/0036-hypothesis-layer-v1.md).

### Evidence Chain Layer · v1 entregada 2026-06-07

Materializa la cadena verificable extremo a extremo: `raw_evidence → evidence_bundle → agent_input → explanation_artifact → claim_registry → hypothesis_registry`. Cada nodo lleva `link_type`, `link_id`, `link_signature`, `upstream_link_id` y `node_hash`. Hard invariant: `chain_id == chain_hash`. NO embebe payloads (eso es ADR-0038); registra sólo enlaces estructurales.

- **API**: `build_evidence_chain(hr, cr, artifact, agent_input)`, `verify_evidence_chain(chain, ...)` (nunca lanza).
- **CLI**: `orbital-sentinel evidence-chain`, `orbital-sentinel verify-evidence-chain`.

Razonamiento en [ADR-0037](docs/adr/0037-evidence-chain-layer-v1.md).

### Investigation Case Layer · v1 entregada 2026-06-07

Unidad portable de investigación: empaqueta los seis artefactos completos (`EvidenceChain` + `HypothesisRegistry` + `ClaimRegistry` + `ExplanationArtifact` + `AgentInput` + `EvidenceBundle`) en un único objeto autocontenido. Cualquier consumidor offline reverifica el caso completo sin acceso a la instancia origen. Hard invariant: `case_id == case_signature`. No es persistencia nueva — es un artefacto JSON derivado, mismo patrón que `EvidenceBundle`.

- **API**: `build_investigation_case(chain, *, hypothesis_registry, claim_registry, artifact, agent_input, bundle)`, `verify_investigation_case(case)` (autocontenido; sin argumentos externos).
- **CLI**: `orbital-sentinel investigation-case`, `orbital-sentinel verify-investigation-case`.

Cierra Fase 6: Orbital Sentinel pasa de *"explicaciones verificables"* a *"plataforma de investigación verificable extremo a extremo"*. Cualquier conclusión orbital puede reconstruirse desde la hipótesis hasta la evidencia original sin pérdida de trazabilidad. Razonamiento en [ADR-0038](docs/adr/0038-investigation-case-layer-v1.md).

### Revocation Layer · v1 entregada 2026-06-07

Permite marcar artefactos previamente emitidos (`evidence_bundle`, `agent_input`, `explanation_artifact`, `claim_registry`, `hypothesis_registry`, `evidence_chain`, `investigation_case`) como **revocados** preservando trazabilidad content-addressable. `RevocationRecord` lleva razón cerrada (`superseded_by_corrected_upstream`, `retracted_by_emitter`, `integrity_violation_discovered`, `schema_obsolete`, `voluntary_withdrawal`) + `target_artifact_signature` congelado para detectar mutaciones posteriores. Hard invariant: `ledger_id == ledger_hash`.

- **API**: `build_revocation_record(...)`, `build_revocation_ledger(records)`, `is_artifact_revoked(ledger, artifact_id)`, `verify_revocation_ledger(ledger)` (nunca lanza).
- **CLI**: `orbital-sentinel revoke-artifact`, `orbital-sentinel verify-revocation-ledger`.

Razonamiento en [ADR-0039](docs/adr/0039-revocation-layer-v1.md).

### External Source Provenance Layer · v1 entregada 2026-06-07

Cierra el primer eslabón estructural hacia abajo: documenta de qué fuente externa (Celestrak, Space-Track, fichero offline, fixture) provienen los TLEs raw que originaron cada `DerivedEvidence`. `ExternalSourceRecord` lleva `source_provider`, `source_url`, `source_dataset_identifier`, `fetched_at` UTC, `source_payload_hash` (SHA-256 de bytes), `source_payload_size_bytes`, `source_content_type`. `ExternalSourceRegistry` materializa forward/reverse indexes evidence↔source. Hard invariant: `registry_id == registry_hash`.

- **API**: `build_external_source_record(...)`, `build_external_source_registry(bundle, records, mapping)`, `verify_external_source_registry(registry, bundle)` (nunca lanza).
- **CLI**: `orbital-sentinel external-source-registry`, `orbital-sentinel verify-external-source-registry`.

Razonamiento en [ADR-0040](docs/adr/0040-external-source-provenance-layer-v1.md).

### Dissent Layer · v1 entregada 2026-06-07

Protocolo content-addressable para que terceros independientes registren disensión sobre un `InvestigationCase`. Cinco tipos cerrados (`factual_correction`, `alternative_explanation`, `missing_evidence`, `methodological_objection`, `scope_disagreement`) con reglas obligatorias por tipo. `DissentLedger` apunta a un caso target específico via `target_case_id` + `target_case_signature` (versión congelada). El layer NO juzga el mérito; sólo prueba integridad estructural de la disensión. Hard invariant: `ledger_id == ledger_hash`.

- **API**: `build_dissent_record(...)`, `build_dissent_ledger(target_case_id, signature, records)`, `verify_dissent_ledger(ledger)` (nunca lanza).
- **CLI**: `orbital-sentinel dissent-record`, `orbital-sentinel dissent-ledger`, `orbital-sentinel verify-dissent-ledger`.

Cierra Fase 7: Orbital Sentinel pasa de *"plataforma de investigación verificable"* a *"plataforma de discurso verificable"*. La verdad orbital no se establece por autoridad sino por cadenas content-addressable de afirmaciones y contra-afirmaciones, todas auditables independientemente. Razonamiento en [ADR-0041](docs/adr/0041-dissent-layer-v1.md).

### Provenance Wiring · v1 entregada 2026-06-07

Cierra el último ciclo arquitectónico abierto: la promesa fundacional *"rastrear hasta el dato original"* ahora funciona end-to-end automáticamente sin intervención manual. Función pura `derive_external_source_registry_for_bundle(bundle, *, tle_snapshots_repo, orbital_elements_repo)` que lee Raw + Normalized y emite el `ExternalSourceRegistry` correspondiente. CERO modificaciones a fetcher, normalizer o modelos previos: la información ya estaba persistida en `TLESnapshot`, sólo necesitaba ser derivada.

- **API**: `derive_external_source_registry_for_bundle(bundle, ...)` (pura, read-only).
- **CLI**: `orbital-sentinel external-source-registry-from-repos <bundle|-> --raw-root --normalized-root`.
- **Binding al caso**: el registry es sidecar; se cryptográficamente ligado al `InvestigationCase` por `source_bundle_id == case.evidence_bundle.bundle_id`. Inmutabilidad de hashes ADR-0031..0041 preservada bit-a-bit.

ADR-0040 pasa de capa declarativa con uso manual a capa integrada operativa. Razonamiento en [ADR-0042](docs/adr/0042-provenance-wiring-v1.md).

### Frozen Reproducibility Vectors · v1.0.0 entregada 2026-06-07

Implementación empírica de ADR-0013 (enmiendas 1 y 2). Conjunto de vectores frozen content-addressable que valida que para inputs canónicos congelados, los hashes producidos por la implementación actual coinciden bit-a-bit con valores externamente declarados.

Cubre las 11 capas content-addressable de ADR-0029 a ADR-0042 con 16 hashes frozen. Cualquier cambio que altere silenciosamente la canonicalización de cualquier capa hace fallar la verificación inmediatamente con un diagnóstico de drift.

**Disponible como package de producción** (enmienda 2): el contrato se distribuye con el wheel, accesible vía CLI sin acceso al árbol fuente.

- **Package de producción**: [`src/orbital_sentinel/reproducibility/`](src/orbital_sentinel/reproducibility/) (vectors + builder + verifier + `verify_installation()` API).
- **CLI end-user**: `orbital-sentinel self-verify [--strict]` — salida JSON con `is_valid`, `n_mismatches`, `mismatches[]`, `adrs_covered[]`, `contract_version`. Exit 0 canónico / 1 con `--strict` si drift.
- **Suite dev**: [`tests/reproducibility/test_frozen_vectors.py`](tests/reproducibility/test_frozen_vectors.py) (39 tests) + [`tests/integration/test_cli_self_verify.py`](tests/integration/test_cli_self_verify.py) (9 tests).
- **Contrato**: enmiendas 1 y 2 de [ADR-0013](docs/adr/0013-reproducibility-declared-environment.md).

### Verificación post-instalación (Phase 8)

Cualquier consumidor que recibe un `InvestigationCase` verifica primero su instalación, luego el caso:

```
$ pip install orbital-sentinel
$ orbital-sentinel self-verify --strict
{"contract_version": "1.0.0", "is_valid": true, "n_hashes_verified": 16, ...}

$ orbital-sentinel verify-investigation-case received_case.json --strict
{"is_valid": true, "verification_hash": "...", ...}
```

Sin clonar repositorio. Sin pytest. Sin contexto previo del usuario. Acceso al contrato cryptográfico para todos los roles del sistema (productor, revisor independiente, disidente).

### Walkthrough end-to-end

Para ver el ciclo completo Raw → Normalized → Derived (on-demand + persistido) en seis pasos:

```powershell
.venv\Scripts\python.exe -m demo.v0_walkthrough
```

Sin red, sin estado externo. Descripción en [docs/walkthrough.md](docs/walkthrough.md).

### Ingesta periódica · scheduling delegado al sistema operativo

Orbital Sentinel **no implementa scheduler propio**. La ingesta periódica se invoca por `cron`, Windows Task Scheduler, systemd timer, GitHub Actions cron, o cualquier otro mecanismo del entorno. Razonamiento completo en [ADR-0022](docs/adr/0022-scheduling-model.md).

El comando es siempre el mismo:

```
orbital-sentinel ingest <dataset>
```

La idempotencia content-addressable (ADR-0019) hace seguro invocarlo a cualquier cadencia sin coordinación adicional.

Guía operacional concreta: [docs/operations/periodic-ingestion.md](docs/operations/periodic-ingestion.md).

## Licencia

Distribuido bajo [Apache License 2.0](LICENSE). Uso comercial permitido. Cláusula de patentes incluida.

## Lengua

La documentación inicial se escribe en español. Una traducción al inglés está prevista como prerrequisito de la primera release pública (ver ADR pendiente sobre internacionalización).
