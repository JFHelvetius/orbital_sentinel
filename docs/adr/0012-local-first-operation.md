# ADR-0012: Local-First Operation

**Estado:** Aceptado
**Fecha:** 2026-06-03
**Autor:** Orbital Sentinel
**Supersede a:** parcialmente ADR-0001 (junto con ADR-0013)
**Relacionado con:** ADR-0000 (P3, P7, P8), ADR-0011, ADR-0013

---

## Contexto

- ADR-0001 acoplaba local-first y reproducibilidad como un único principio. El red-team review (F2) demostró que son ortogonales y que su unión ocultaba tensiones reales.
- Este ADR captura **solo el principio de operación local**. La reproducibilidad se trata en ADR-0013.

## Decisión

Toda funcionalidad fundamental del sistema debe poder operar sin acceso a servicios externos. Los servicios externos amplían capacidades; nunca las habilitan.

**Esto es criterio de aceptación de PR, no aspiración.**

### Qué cuenta como "funcionalidad fundamental"

- Ingesta de fuentes públicas accesibles sin auth (CelesTrak con cache local).
- Almacenamiento y consulta del catálogo.
- Propagación SGP4.
- Detección de conjunciones, maniobras y anomalías sobre datos ya descargados.
- Visualización local (Cesium bundleado + tiles abiertos cacheados).
- Agente LLM en modo Ollama local.

### Qué se admite como ampliación opt-in (no fundamental)

- Acceso a Space-Track (requiere credencial; degrada coverage si ausente).
- Cesium Ion tiles de alta resolución (opt-in).
- Anthropic Claude como proveedor de agente (opt-in, mayor calidad).
- Cualquier integración futura con APIs autenticadas.

### Reglas operacionales

1. **Sin telemetría no autorizada.** Cualquier emisión de datos al exterior requiere flag explícito documentado en docs y en el primer arranque.
2. **Sin red en arranque.** El sistema arranca, lee config local, lee catálogo local, sirve. No contacta endpoints remotos hasta que un comando lo requiera explícitamente.
3. **Sin "best when online".** No hay path en el código que se comporte distinto solo porque haya red disponible. Las capacidades extendidas se invocan con flag explícito.
4. **Bootstrap declarado.** Las descargas iniciales necesarias (catálogos, modelos Ollama, tiles) están documentadas en una operación `orbital-sentinel bootstrap` que el usuario ejecuta de forma deliberada.
5. **Caché de fuente.** Toda fuente descargada se almacena con su `content_hash` y metadata de origen, y se puede reejecutar offline.

### Resolución de tensiones con reproducibilidad (ADR-0013)

Cuando local-first y reproducibilidad entran en tensión (cache LLM tras update de modelo, tiles abiertos actualizados, embeddings tras update de sentence-transformers), **manda ADR-0013**: la reproducibilidad nunca se sacrifica por comodidad local.

Mecánica práctica:

- Cache de respuestas LLM se invalida cuando cambia cualquier componente del key extendido `(prompt_hash, model_id, model_weights_hash, retrieved_context_hash)`. El `model_weights_hash` se calcula sobre el archivo de pesos físico, no sobre el nombre del modelo.
- Tiles abiertos cacheados conservan su versión de descarga; un recálculo con tiles nuevos genera un derivado con `tiles_version` distinto.
- Embeddings se versionan con `embedding_model_id` + `embedding_model_version` y cualquier dataset de vectores está asociado a ese par; cambiar de modelo requiere re-ingest, no in-place rewrite.

## Justificación

- Coherente con P3 (coste cero baseline), P7 (fuentes públicas), P8 (local-first irrenunciable).
- Eliminar paths "online vs offline" reduce branching y elimina una clase entera de bugs no reproducibles.
- Bootstrap explícito da al usuario control sobre la red, lo que es crítico en contextos restringidos (redes corporativas, air-gapped, embarcadas).

## Consecuencias

**Positivas**
- Privacidad por defecto.
- Funciona offline.
- Setup determinista del estado.

**Negativas**
- Algunas capacidades requieren bootstrap inicial; primera ejecución no es inmediata.
- Capacidades cloud quedan detrás de opt-in.

**Neutras**
- Cualquier despliegue cloud futuro será producto derivado, no reemplazo.

## Alternativas consideradas

### A. Cloud-first
**Razón de rechazo:** viola P3, P7, P8.

### B. Híbrido por defecto
**Razón de rechazo:** doble path → doble validación → divergencia silenciosa.

### C. Local-first sin política para tensiones con reproducibilidad
**Razón de rechazo:** es lo que falló en ADR-0001 (F2).

## Alineación con ADR-0000

- **Refuerza P3, P7, P8** explícitamente.
- **Compatible con P1, P4** vía la regla de precedencia con ADR-0013.
- **Sin tensiones.**

## Referencias

- Kleppmann, M. et al. (2019). *Local-First Software: You Own Your Data, in spite of the Cloud.*

---

## Historial de enmiendas

*Sin enmiendas a fecha de aceptación.*
