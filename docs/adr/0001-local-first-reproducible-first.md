# ADR-0001: Local-first, reproducible-first

**Estado:** **Superseded** por ADR-0012 (Local-First Operation) y ADR-0013 (Reproducibility Under Declared Environment), 2026-06-03
**Fecha:** 2026-06-03 (aceptado) → 2026-06-03 (superseded)
**Autor:** Orbital Sentinel
**Supersede a:** ninguno
**Supersedido por:** ADR-0012, ADR-0013
**Relacionado con:** ADR-0000 (P1, P3, P4, P7, P8)

---

> ## Nota de supersesión (2026-06-03)
>
> Este ADR acoplaba dos principios — local-first y reproducible-first — como si fueran uno. El red-team review (F2) demostró que son ortogonales y que su unión ocultaba tensiones reales (cache LLM tras update de modelo, tiles abiertos actualizados, embeddings tras update de modelo).
>
> Para resolver esas tensiones con vocabulario explícito, este ADR se supersede por dos ADRs independientes:
>
> - **ADR-0012 — Local-First Operation**: gobierna qué partes del sistema pueden depender de la red.
> - **ADR-0013 — Reproducibility Under Declared Environment**: gobierna qué propiedades de reproducibilidad se garantizan y cómo se verifican.
>
> Cuando los dos principios entran en tensión, manda ADR-0013.
>
> El contenido original se conserva debajo como contexto histórico. **No debe consultarse para tomar decisiones nuevas.**

---

## Contexto

- Todas las decisiones posteriores (storage, propagación, agentes, visualización, simulación, pruebas) involucran el mismo trade-off recurrente: delegar en un servicio externo o adoptar la última dependencia, contra la garantía de funcionar sin red y de reproducir resultados pasados.
- Sin un principio explícito, cada decisión técnica resolvería ese trade-off de forma inconsistente.
- ADR-0000 P3, P4, P7 y P8 ya señalan la dirección, pero no la operacionalizan.

## Decisión

Dos principios acoplados gobiernan toda la arquitectura. No son aspiracionales: son criterios de aceptación de PR.

1. **Local-first.** Toda funcionalidad fundamental del sistema debe poder operar sin acceso a servicios externos. Los servicios externos amplían capacidades; nunca las habilitan.
2. **Reproducible-first.** Cualquier inferencia debe poder reproducirse partiendo de sus entradas, la versión exacta del algoritmo y los parámetros. La reproducción es bit-exacta para etapas deterministas y estadísticamente equivalente — bajo seeds y versiones declaradas — para etapas estocásticas.

## Implicaciones operacionales por plano

**Core / Configuración**
- Configuración por archivo local; no se leen endpoints remotos al arrancar.
- Sin telemetría que el usuario no pueda desactivar antes del primer uso.

**Ingestion**
- Toda fuente se cachea localmente en primera descarga.
- Reejecuciones leen de caché por defecto; la red solo se contacta con flag explícito.
- Cada artefacto descargado se almacena con su `content_hash` (SHA-256) y metadata de origen.

**Catalog (storage)**
- Motor embebido (DuckDB, ADR-0004), no networked.
- Parquet como formato canónico en disco, portable a cualquier herramienta.

**Propagation**
- SGP4 (ADR-0005) es determinista por construcción.
- Cada fila de efemérides lleva `engine_version`.

**Analytics**
- Etapas estocásticas (ML, sampling, anomalías) registran `seed`, `library_version`, `model_artifact_hash`.
- Artefactos de modelo pequeños se versionan en repo; grandes se referencian por hash con script de descarga reproducible.

**Agent (Fase 5)**
- Ollama local es el default (ADR-0009).
- Respuestas LLM se cachean por `(prompt_hash, model_id, model_version, retrieved_context_hash)`.
- Proveedores cloud son opt-in, nunca default, nunca camino crítico.

**Visualization**
- Cesium embebido (ADR-0008); sin llamadas a Cesium Ion ni Bing Maps en baseline.
- Map tiles de fuentes abiertas con caché local.

**Tests**
- Fixtures de TLEs reales congelados en `tests/fixtures/`.
- Cero red en unit/integration tests; mocks de HTTP para tests de ingesta.
- CI ejecuta en runner sin secrets ni acceso a servicios de pago para validar reproducibilidad pública.

**CI / Build**
- `uv.lock` commiteado (ADR-0003); instalaciones reproducibles bit a bit sobre un mismo sistema operativo.
- Imagen OCI de referencia publicada por release; cualquier reproducción del estado puede partir de ella.

## Justificación

- Refuerza directamente P3, P4, P7, P8 de ADR-0000.
- Convierte un trade-off recurrente en una regla, reduciendo carga cognitiva en futuras decisiones.
- Local-first elimina una clase entera de bugs no reproducibles ("el servicio externo respondió diferente").
- Reproducible-first es prerrequisito para que el proyecto sea citable en literatura académica.

## Consecuencias

**Positivas**
- Privacidad por defecto.
- Funciona offline.
- Outputs auditables.
- Coste baseline cero.
- Test suite no es flaky por red.

**Negativas**
- Más almacenamiento local requerido (mitigado por compresión Parquet y políticas de retención).
- Capacidades dependientes de modelos cloud quedan detrás de un opt-in explícito.
- Setup inicial puede requerir descarga bootstrap (catálogos, modelos Ollama).

**Neutras**
- Cualquier despliegue cloud futuro será producto derivado, no reemplazo.
- Los datos cacheados localmente pueden crecer; el usuario decide políticas de purga.

## Alternativas consideradas

### A. Cloud-first
Servicios SaaS para storage, cómputo y modelos.
**Razón de rechazo:** viola P3, P7, P8 de ADR-0000. Incompatible con la audiencia primaria.

### B. Híbrido por defecto
Sistema funciona "mejor" con red, "degradado" sin red.
**Razón de rechazo:** crea dos caminos de código permanentes. Cada cambio cuesta dos validaciones. Local-first como propiedad elimina esa dualidad: cloud es ampliación, no camino alternativo.

### C. Best-effort reproducibilidad
Reproducir cuando sea barato; aceptar deriva cuando sea caro.
**Razón de rechazo:** la reproducibilidad parcial no es citable. Un paper que dependa de "más o menos" no es ciencia.

### D. Local-first sin reproducible-first
Local pero sin garantías de reproducción.
**Razón de rechazo:** un proyecto local pero irreproducible es solo lento, no útil. Las propiedades se necesitan juntas.

## Alineación con ADR-0000

- **Refuerza P1** (trazabilidad): reproducible-first la operacionaliza.
- **Refuerza P3** (coste cero): local-first la garantiza en baseline.
- **Refuerza P4** (reproducibilidad): es su declaración explícita.
- **Refuerza P7** (datos abiertos): elimina dependencia de fuentes contractuales en el núcleo.
- **Refuerza P8** (local-first): es su declaración explícita y operacional.
- **Neutral respecto a P2, P5, P6.**
- **Sin tensiones** con ninguna propiedad irrenunciable.

## Referencias

- Kleppmann, M. et al. (2019). *Local-First Software: You Own Your Data, in spite of the Cloud.* Onward! 2019.
- ACM. *Artifact Review and Badging — Current Version (v1.1).*
- Software Heritage. *Principles on archive and reproducibility of software.*

---

## Historial de enmiendas

*Sin enmiendas a fecha de aceptación.*
