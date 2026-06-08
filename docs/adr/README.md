# Architecture Decision Records

Este directorio contiene los ADR (Architecture Decision Records) de Orbital Sentinel.

## Qué es un ADR

Un ADR es un documento corto que captura una decisión arquitectónica significativa, su contexto, las alternativas consideradas y sus consecuencias. La práctica está descrita en [Documenting Architecture Decisions](https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions) de Michael Nygard.

En este proyecto los ADRs son el contrato entre el pasado y el futuro: explican por qué algo es como es y bajo qué condiciones cambiar.

## Política de ADRs en Orbital Sentinel

- **Inmutabilidad por defecto.** Un ADR aceptado no se edita en su contenido fundamental; se supersede con uno nuevo que lo reemplace o se enmienda con notas explícitas datadas al final.
- **Numeración monótona y zero-padded** a cuatro dígitos: `0000`, `0001`, etc. El número no se reutiliza nunca, ni siquiera si el ADR se anula.
- **Estados permitidos:** `Propuesto`, `Aceptado`, `Superseded por ADR-XXXX`, `Anulado`.
- **Idioma:** español. Slugs en inglés para evergreen.
- **Toda PR que introduce una decisión arquitectónica nueva debe incluir el ADR correspondiente.** Sin ADR, sin merge.
- **Todo ADR técnico debe declarar cómo se alinea con [ADR-0000](0000-long-term-vision.md).** Esa es la verificación de coherencia con la visión.

## Plantilla

Ver [template.md](template.md) para el formato.

## Índice

| ID | Título | Estado | Fecha |
|----|--------|--------|-------|
| [0000](0000-long-term-vision.md) | Visión a largo plazo de Orbital Sentinel | Aceptado (enmienda 1) | 2026-06-03 |
| [0001](0001-local-first-reproducible-first.md) | Local-first, reproducible-first | **Superseded** por ADR-0012, ADR-0013 | 2026-06-03 |
| [0002](0002-planes-architecture.md) | Arquitectura en planos, sin microservicios | Aceptado (enmiendas 1, 2) | 2026-06-03 |
| [0003](0003-src-layout-uv.md) | Layout `src/`, monorepo Python, gestor `uv` | Aceptado | 2026-06-03 |
| [0004](0004-duckdb-parquet-store.md) | DuckDB + Parquet como store primario | Aceptado (enmiendas 1, 2) | 2026-06-03 |
| [0005](0005-sgp4-only-propagation.md) | SGP4 como único motor de propagación en v1 | Aceptado (enmienda 1) | 2026-06-03 |
| [0006](0006-data-immutability.md) | Inmutabilidad de datos, capas raw/normalized/derived | Aceptado (enmienda 1) | 2026-06-03 |
| [0007](0007-apache-license.md) | Licencia Apache-2.0 | Aceptado | 2026-06-03 |
| [0008](0008-cesium-uncertainty.md) | Visualización con Cesium y honestidad sobre incertidumbre | Aceptado | 2026-06-03 |
| [0009](0009-no-agent-frameworks.md) | Sin frameworks de agentes; Ollama por defecto, Claude opcional | Aceptado (enmienda 1) | 2026-06-03 |
| [0010](0010-versioning-policy.md) | Versioning Policy | Aceptado | 2026-06-03 |
| [0011](0011-secrets-management.md) | Secrets Management | Aceptado | 2026-06-03 |
| [0012](0012-local-first-operation.md) | Local-First Operation | Aceptado | 2026-06-03 |
| [0013](0013-reproducibility-declared-environment.md) | Reproducibility Under Declared Environment | Aceptado (enmiendas 1, 2) | 2026-06-03 |
| [0014](0014-sgp4-integration.md) | Integración de SGP4 como motor de la capa Derived | Aceptado | 2026-06-03 |
| [0015](0015-phase-1-closure.md) | Cierre formal de Fase 1 | Aceptado | 2026-06-06 |
| [0016](0016-conjunction-analysis-v01.md) | Análisis de conjunción pairwise v0.1 | Aceptado | 2026-06-06 |
| [0017](0017-tca-refinement-v02.md) | Refinamiento de TCA por bisección — pairwise v0.2 | Aceptado | 2026-06-06 |
| [0018](0018-pairwise-screening-v03.md) | N-to-N pairwise screening con filtro apogeo/perigeo — v0.3 | Aceptado | 2026-06-06 |
| [0019](0019-conjunction-detections-persistence.md) | Persistencia de detecciones de conjunción — pairwise v0.4 | Aceptado | 2026-06-06 |
| [0020](0020-probability-of-collision-v1.md) | Probability of collision (Pc) v1.0 con covarianza declarada | Aceptado | 2026-06-06 |
| [0021](0021-phase-2-closure.md) | Cierre formal de Fase 2 | Aceptado | 2026-06-06 |
| [0022](0022-scheduling-model.md) | Modelo de scheduling para ingesta periódica | Aceptado | 2026-06-06 |
| [0023](0023-pass-prediction-v01.md) | Pass prediction v0.1 (observer-from-Earth) | Aceptado (enmiendas 1-5) | 2026-06-06 |
| [0024](0024-solar-geometry-v01.md) | Solar geometry primitives v0.1 | Aceptado | 2026-06-06 |
| [0025](0025-observatory-scan-v01.md) | Observatory scan v0.1 (multi-satellite aggregation) | Aceptado | 2026-06-06 |
| [0026](0026-observatory-layer-v1-closure.md) | Cierre formal de Observatory Layer v1 | Aceptado | 2026-06-06 |
| [0027](0027-maneuver-detection-v01.md) | Maneuver detection v0.1 + catalog historical query | Aceptado | 2026-06-06 |
| [0028](0028-anomaly-detection-v01.md) | Anomaly detection v0.1 (observacional) | Aceptado | 2026-06-06 |
| [0029](0029-derived-evidence-layer-v01.md) | Derived Evidence Layer v0.1 | Aceptado | 2026-06-06 |
| [0030](0030-explanation-context-layer-v01.md) | Explanation Context Layer v0.1 | Aceptado | 2026-06-06 |
| [0031](0031-verifiable-evidence-bundle-layer-v01.md) | Verifiable Evidence Bundle Layer v0.1 | Aceptado | 2026-06-06 |
| [0032](0032-agent-input-contract-v01.md) | Agent Input Contract v0.1 | Aceptado | 2026-06-06 |
| [0033](0033-explanation-agent-v01.md) | Explanation Agent v0.1 | Aceptado | 2026-06-06 |
| [0034](0034-explanation-verification-layer-v01.md) | Explanation Verification Layer v0.1 | Aceptado | 2026-06-06 |
| [0035](0035-verifiable-claim-layer-v01.md) | Verifiable Claim Layer v0.1 | Aceptado | 2026-06-07 |
| [0036](0036-hypothesis-layer-v1.md) | Hypothesis Layer v1 | Aceptado | 2026-06-07 |
| [0037](0037-evidence-chain-layer-v1.md) | Evidence Chain Layer v1 | Aceptado | 2026-06-07 |
| [0038](0038-investigation-case-layer-v1.md) | Investigation Case Layer v1 | Aceptado | 2026-06-07 |
| [0039](0039-revocation-layer-v1.md) | Revocation Layer v1 | Aceptado | 2026-06-07 |
| [0040](0040-external-source-provenance-layer-v1.md) | External Source Provenance Layer v1 | Aceptado | 2026-06-07 |
| [0041](0041-dissent-layer-v1.md) | Dissent Layer v1 | Aceptado | 2026-06-07 |
| [0042](0042-provenance-wiring-v1.md) | Provenance Wiring v1 | Aceptado | 2026-06-07 |

ADR-0012 y ADR-0013 (sucesores de ADR-0001) son las decisiones más influyentes: gobiernan qué partes del sistema pueden depender de la red y qué propiedades de reproducibilidad se garantizan. Las decisiones posteriores son aplicaciones suyas a planos concretos. Cuando los dos principios entran en tensión, manda ADR-0013.
