# ADR-0009: Sin frameworks de agentes; Ollama por defecto, Claude opcional

**Estado:** Aceptado
**Fecha:** 2026-06-03
**Autor:** Orbital Sentinel
**Supersede a:** ninguno
**Relacionado con:** ADR-0000 (P1, P3, P4, P8), ADR-0001

---

## Contexto

- Fase 5 requiere un agente LLM que explique por qué una anomalía es anómala.
- Existen frameworks de agentes (LangChain, LlamaIndex, AutoGen, CrewAI) con API churn alto.
- Proveedores LLM: Ollama (local), Anthropic Claude, OpenAI, Mistral La Plateforme, etc.
- ADR-0001 fuerza local-first; ADR-0000 P3 fuerza baseline coste cero.

## Decisión

- **Sin framework de agentes pesado.** Implementación directa: prompts versionados en `agent/prompts/`, cliente HTTP simple, RAG explícito sobre el catálogo histórico, eventos detectados y opcionalmente noticias filtradas.
- **Ollama** (local, modelo configurable) como proveedor por defecto. Default sugerido: Llama 3 8B o Mistral 7B, ambos ajustables vía configuración.
- **Anthropic Claude** vía SDK oficial con prompt caching como opt-in explícito.
- **Sin cliente OpenAI** en baseline. Puede añadirse como extra futuro si hay demanda.
- **Respuestas cacheadas** por `(prompt_hash, model_id, model_version, retrieved_context_hash)` para reproducibilidad parcial.
- **Salida estructurada** validada con Pydantic (causa hipotética, evidencia, confianza, refutaciones plausibles).

## Justificación

- Frameworks de agentes tienen API churn altísimo; acoplarse va contra la heurística de horizonte de 5 años.
- Código directo es auditable y diff-friendly. Cada release puede listar los cambios exactos de prompt.
- Ollama satisface ADR-0001 y P3 sin compromiso.
- Claude SDK es estable, tiene prompt caching nativo, y es compatible con opt-in sin tocar arquitectura.
- LLM nondeterminism es intrínseco; lo mitigamos vía seeds y temperaturas declaradas + cache de respuestas + validación estructurada de salida.

## Consecuencias

**Positivas**
- Auditabilidad: cada explicación lleva el prompt exacto que la produjo.
- Coste baseline cero.
- Sin lock-in de framework.
- Cambios de proveedor LLM son cambios localizados a un módulo, no reescrituras.

**Negativas**
- Más código a mantener (RAG, retrieval, structured output validation).
- Calidad de explicación local-only puede ser inferior a Claude para razonamiento complejo (mitigable vía opt-in).

**Neutras**
- Estructura del módulo `agent/` queda como ejemplo de cómo añadir proveedores: implementar interfaz `LLMProvider`, declarar `model_id`/`model_version`, exponer configuración.

## Alternativas consideradas

### A. LangChain
**Razón de rechazo:** velocidad de pivot incompatible con horizonte multi-año. Burden de mantenimiento alto en proyecto sin equipo dedicado.

### B. LlamaIndex
**Razón de rechazo:** similar a LangChain.

### C. AutoGen / CrewAI
**Razón de rechazo:** framework lock-in; overkill para una tarea explicativa puntual.

### D. Default Claude
**Razón de rechazo:** viola baseline coste cero (P3) y local-first (ADR-0001).

### E. Default OpenAI
**Razón de rechazo:** ídem; además modelo cerrado sin alternativa local equivalente con la misma API.

### F. Solo Ollama, sin opción cloud
**Razón de rechazo:** descarta gratuitamente ganancia de calidad en explicación compleja. La opción opt-in cuesta poco mantener.

## Alineación con ADR-0000

- **Refuerza P3, P8** (default local y gratis).
- **Refuerza P1, P4** (prompts versionados, respuestas cacheadas por hash).
- **Compatible con P6** (prompts son documentación auditable).
- **Sin tensiones.**

## Referencias

- Ollama. *Project documentation.*
- Anthropic. *Claude API documentation, prompt caching.*
- Lewis, P. et al. (2020). *Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks.*

---

## Historial de enmiendas

### 2026-06-03 — Enmienda 1
**LLMs no son fuente de verdad.** El red-team review (F7) señaló que modelos LLM locales (7–8B) pueden producir explicaciones plausibles pero incorrectas, especialmente en razonamiento técnico multi-paso, lo que entraría en tensión con la propiedad P2 (honestidad sobre incertidumbre) de ADR-0000.

Decisión aclaratoria: **los modelos LLM nunca constituyen fuente de verdad en Orbital Sentinel.** El agente de Fase 5 interpreta y narra resultados generados por componentes deterministas y trazables (propagación, detección de maniobras, detección de anomalías); no produce inferencias originales sobre estado físico.

Consecuencias operacionales:

1. Toda explicación generada por el agente debe estar **fundamentada en evidencia recuperada** desde el catálogo, los eventos detectados, o documentos referenciables. Sin evidencia recuperable, no hay explicación.
2. La estructura de salida del agente incluye campos `evidence_refs` que apuntan a los datos deterministas usados; sin refs no se emite la respuesta.
3. Cualquier afirmación del agente que no pueda mapearse a una `evidence_ref` se etiqueta como `unsupported` y se suprime de la salida pública.
4. El sistema de evaluación de Fase 5 audita el ratio supported/unsupported como métrica de calidad.

Esta aclaración no cambia la decisión sobre proveedores LLM ni la arquitectura del agente; ancla su rol como traductor, no como razonador autónomo.
