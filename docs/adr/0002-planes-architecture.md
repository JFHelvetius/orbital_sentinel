# ADR-0002: Arquitectura en planos, sin microservicios

**Estado:** Aceptado
**Fecha:** 2026-06-03
**Autor:** Orbital Sentinel
**Supersede a:** ninguno
**Relacionado con:** ADR-0000 (P3, P6, P8), ADR-0001

---

## Contexto

- El sistema involucra varios concerns: ingesta, persistencia, propagación, analítica, API, visualización, agente LLM.
- Opciones de descomposición: monolito acoplado, microservicios, capas/planos modulares.
- ADR-0001 fuerza operación local; microservicios introducen red y operaciones.

## Decisión

Siete planos internos como módulos Python en un único paquete (`orbital_sentinel`):

1. **Core** — tipos, unidades, tiempos, frames, logging, config, errores.
2. **Orchestration** — scheduling, reintentos, backoff.
3. **Ingestion** — fetchers, parsers, validadores, deduplicación.
4. **Catalog** — store, esquemas, migraciones.
5. **Propagation** — motor SGP4, ventanas temporales, caché.
6. **Analytics** — conjunciones, maniobras, anomalías.
7. **Agent** — RAG, prompts, explicador (Fase 5).

Reglas:
- Las dependencias entre planos solo van **hacia abajo** (Analytics importa de Propagation, no al revés).
- Sin RPC entre planos. Comunicación por contratos de datos (Pydantic + esquemas Parquet versionados).
- Reglas de imports enforced por linter (`import-linter` o equivalente) en CI.

## Justificación

- Microservicios violarían ADR-0001 (introducen red).
- Microservicios violarían P3 (operaciones de red y observabilidad).
- Los planos preservan modularidad sin pagar el coste de red.
- Promoción futura a servicios es un refactor mecánico si surge necesidad real.
- Contratos de datos son más estables que contratos RPC (no cambian con refactors internos).

## Consecuencias

**Positivas**
- Despliegue local trivial.
- Tests unitarios e integrales sin red.
- Refactor entre planos es intra-proceso.

**Negativas**
- Escalado horizontal no inmediato (aceptable por P3).
- Requiere disciplina de imports (mitigado por lint enforced en CI).

**Neutras**
- Extracción por plano a servicio independiente posible si en años futuros se justifica.

## Alternativas consideradas

### A. Monolito acoplado (sin disciplina de planos)
**Razón de rechazo:** mantenibilidad pobre bajo la heurística de horizonte de 5 años.

### B. Microservicios desde día 1
**Razón de rechazo:** viola ADR-0001, viola P3.

### C. Plugin architecture (entry points) como base
**Razón de rechazo:** apropiado para extensiones de terceros, no como esqueleto. Considerar para `viz` o `analytics` plugins en versiones futuras.

### D. Hexagonal / Ports & Adapters puros
**Razón de rechazo:** patrón válido pero más rígido que necesario; los planos ya capturan la idea sin imponer la nomenclatura.

## Alineación con ADR-0000

- **Refuerza P3** (sin red interna).
- **Refuerza P6** (planos documentables independientemente).
- **Compatible con P8** (local-first).
- **Sin tensiones.**

## Referencias

- Parnas, D. L. (1972). *On the Criteria To Be Used in Decomposing Systems into Modules.* CACM.
- `import-linter`. Documentación.

---

## Historial de enmiendas

### 2026-06-03 — Enmienda 1
**Workflows de composición en `orchestration/`.** Este ADR plantea Orchestration como plano 2 (low-level: primitivas de scheduling, reintentos, backoff). En la práctica, también necesitamos un lugar donde residan **workflows que componen múltiples planos** (e.g. `fetch → persist Raw → normalize → persist Normalized`). Estos workflows requieren importar de planos higher-numbered (Ingestion, Catalog, …), lo que la regla "dependencias solo hacia abajo" prohíbe.

Resolución: `orchestration/` aloja dos tipos de módulos con perfiles distintos:

- **Primitivas** (planeadas, no implementadas aún): scheduling, reintentos, backoff. Son low-level y pueden ser importadas por cualquier plano higher-numbered. Siguen la regla original sin excepciones.
- **Pipelines de composición** (e.g. `orchestration/ingest_pipeline.py`): componen módulos de planos higher-numbered. Excepcionalmente se les permite importar de cualquier plano de la arquitectura.

Criterio práctico para distinguir: si un módulo de `orchestration/` declara una clase con sufijo `Pipeline` o `Workflow`, está en la categoría de composición y puede importar libremente. Si es una utility, sigue la regla de dependencias hacia abajo.

Esta enmienda **no introduce un nuevo plano**. Mantiene los siete originales y aclara la doble función de Orchestration. La regla "dependencias solo hacia abajo" sigue siendo el default; las pipelines de composición son una excepción explícita y nombrada.

### 2026-06-06 — Enmienda 2

**Reducción del alcance de "primitivas de Orchestration".** ADR-0022 decidió que Orbital Sentinel **no implementa scheduler in-process**; el sistema operativo (o entorno externo) maneja periodicidad. En consecuencia, "scheduling, reintentos, backoff" como primitivas planeadas en `orchestration/` se reducen a **"reintentos, backoff"** (utilities a nivel de invocación individual). Scheduling no es un componente del proyecto.

El plano sigue albergando:

1. **Pipelines de composición** (enmienda 1): workflows que componen módulos de planos higher-numbered.
2. **Primitivas de invocación individual** (esta enmienda 2): retry/backoff dentro de un run, sin daemon.

Esta enmienda **no introduce ni elimina planos** ni cambia la regla de imports. Solo aclara el contenido legítimo de Orchestration tras ADR-0022.
