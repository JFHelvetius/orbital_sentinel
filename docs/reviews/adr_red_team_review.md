# Red-team review of ADR-0000 to ADR-0009

**Reviewer:** Principal Engineer externo, contratado para rechazar el diseño.
**Alcance revisado:** `docs/adr/0000-long-term-vision.md` a `docs/adr/0009-no-agent-frameworks.md`.
**Fecha:** 2026-06-03
**Metodología:** Lectura adversarial. Sin acceso al equipo. Sin asumir buena fe en las premisas. Cada propiedad declarada se interpreta como compromiso operacional y se ataca su factibilidad.

---

## Tesis del revisor

La arquitectura es internamente coherente y está mejor argumentada que la mayoría de propuestas que veo. Eso no la hace correcta. Reposa sobre **tres supuestos load-bearing** que los documentos no someten a stress test:

1. Que la reproducibilidad bit-exacta es alcanzable en este stack.
2. Que "local-first" y "reproducible-first" son una sola propiedad y no dos en tensión.
3. Que la precisión SGP4+TLE es suficiente para los casos de uso comprometidos en Fases 2–4.

Si alguno de los tres falla, varias decisiones se vuelven incorrectas simultáneamente. La arquitectura no tiene plan de contingencia para ninguno.

A continuación, los findings ordenados por severidad. Las recomendaciones de aceptación/rechazo van al final, no después de cada hallazgo, por petición del solicitante.

---

## Findings críticos

### F1 · "Trazabilidad bit a bit" es teatro de reproducibilidad

**ADRs implicados:** 0000 (P1), 0000 (P4), 0001.

La propiedad P1 promete reproducir cualquier inferencia "bit a bit". El stack no puede entregarlo en general:

- **Python + wheels**: el resolver de pip/uv puede instalar wheels distintas en arquitecturas distintas (x86_64 vs aarch64 vs musl vs glibc). El mismo `uv.lock` produce instalaciones binarias diferentes en máquinas distintas.
- **DuckDB**: compilado con vendor compilers distintos, las reducciones en `float64` pueden diferir en el último bit. El proyecto no controla esto.
- **SGP4 (lib `sgp4`)**: el port Python tiene un núcleo en C compilado por la wheel. Históricamente ha habido reportes de diferencias de último bit entre compiladores. Para conjunciones donde la diferencia geométrica importa, esto es relevante.
- **Floating-point summation**: la mayoría de pipelines numéricos usan `numpy` con BLAS, que reordena reducciones según el número de threads (`OMP_NUM_THREADS`). Reproducibilidad bit-exacta requiere fijar threads, fijar BLAS vendor, fijar la versión exacta de BLAS.
- **Ollama** (ADR-0009): cachear por `(prompt_hash, model_id, model_version)` asume que `model_version` captura los pesos. Ollama actualiza modelos in-place con el mismo nombre. El cache se puede invalidar silenciosamente.
- **LLMs en GPU**: las reducciones CUDA son no deterministas por defecto. "Reproducibilidad bit a bit" en agente no existe sin `torch.use_deterministic_algorithms(True)` + pin de CUDA + GPU idéntica.

ADR-0001 sí cualifica "bit-exacta para etapas deterministas, estadísticamente equivalente para estocásticas". Pero ADR-0000 P1 no cualifica, y P1 es la propiedad irrenunciable. Esto va a generar credibilidad negativa: alguien clonará el repo, no obtendrá los mismos bits, y publicará un issue legítimo. La defensa "ah, P1 es aspiracional" rompe el modelo de propiedades irrenunciables.

**Esto no es un fallo menor.** Es la propiedad central del proyecto declarada de forma más fuerte de lo que el stack puede sostener.

### F2 · ADR-0001 acopla dos principios ortogonales y oculta sus tensiones

**ADRs implicados:** 0001, 0009, 0008.

"Local-first" y "reproducible-first" no son una propiedad. Son dos:

- Software local-first puede ser perfectamente irreproducible (el cache local cambia, el reloj cambia, el sistema operativo se actualiza).
- Software reproducible-first puede ser perfectamente cloud-bound (un SaaS determinista existe).

Acoplarlos en un ADR significa que cuando exista tensión entre los dos, no hay vocabulario para discutir el trade-off. Tensiones concretas que el ADR no aborda:

- **Cache de LLM**: local-first dice "cachea localmente". Reproducible-first dice "invalida si los pesos cambian". El ADR no resuelve qué pasa cuando Ollama actualiza un modelo con el mismo nombre.
- **Cesium tiles** (ADR-0008): "tiles abiertas con caché local". Pero los proveedores de tiles abiertas (OSM) actualizan tiles ocasionalmente. Local-first: usa la caché. Reproducible-first: detecta cambios y re-bake. Inconciliables sin política.
- **Modelo de embeddings para RAG**: si actualizamos sentence-transformers, los vectores cambian. Local-first: re-ingest local. Reproducible-first: requeriría versionar también los vectores por modelo. ADR-0009 no menciona embeddings ni vector store.

**Recomendación tácita** (porque el solicitante no quiere recomendaciones por hallazgo): el ADR-0001 debería partirse. La unión que sugiere "se reuerzan" es retórica, no técnica.

### F3 · `uv` es una apuesta a un proveedor joven con horizonte de 5 años

**ADRs implicados:** 0003, 0001.

- `uv` tiene ~2 años. Astral es startup con VC. Su roadmap puede pivotar o congelarse si cambia el modelo de negocio.
- `uv.lock` produce reproducibilidad solo en el mismo OS+arch. Para una comunidad distribuida con contribuidores en Linux/macOS/Windows, esta promesa es más débil de lo que el proyecto necesita.
- `[project.optional-dependencies]` (extras `viz`, `agent`, `dev`) no se pueden lockear por separado en `uv`. Un fix de seguridad en una dependencia de `agent` obliga a re-lock que toca también `viz`.
- No hay ADR de **plan B** para `uv`. La heurística de 5 años exige reflexión sobre qué pasa si la tool desaparece. El ADR-0003 ni la menciona.

El paralelo con DuckDB es relevante pero menos severo: DuckDB tiene foundation, papers en SIGMOD, instituciones académicas detrás. `uv` tiene una empresa privada.

### F4 · DuckDB single-writer es un cuello de botella inminente en Fase 2

**ADRs implicados:** 0004, 0002.

El modelo de planos (ADR-0002) tiene Ingestion y Analytics escribiendo a Catalog. DuckDB es single-writer a nivel de fichero. Tan pronto como:

- el ingestor descarga TLEs nuevos y los escribe en Raw/Normalized,
- el módulo de conjunciones (Fase 2) está procesando una ventana y escribiendo eventos en Derived,

los dos quieren agarrar el lock del mismo archivo `.duckdb`. Tres salidas, ninguna documentada:

1. **Serializar**: todo escribe a través de un único proceso actor. No mencionado en ADR-0002 (Orchestration). Esto introduce backpressure y latencia.
2. **Múltiples archivos DuckDB**: uno por capa o por dominio. Rompe el modelo "un solo catalog", complica queries cross-layer (necesitas `ATTACH`).
3. **Migrar a Postgres**: viola local-first (ADR-0001).

Además, `pytest-xdist` (paralelización de tests) no puede correr suite que toque DuckDB en paralelo sin un workspace por worker. Esto multiplica el tiempo de CI o fuerza serialización.

**El ADR-0004 menciona "single-writer en momentos dados (aceptable para writes orquestados)" como consecuencia negativa neutra.** No es neutra. Es un constraint operacional que define el diseño del orquestador y no se ha diseñado.

### F5 · El cálculo de almacenamiento rompe el portátil doméstico

**ADRs implicados:** 0000 (P3), 0006, 0001, 0004.

Orden de magnitud:

- Catálogo público ~30 000 objetos.
- Si Fase 1 materializa efemérides en paso de 60 s sobre 24 h: 30 000 × 1440 = ~43M filas/día.
- Sobre 5 años: ~80 mil millones de filas.
- A ~100 bytes/fila Parquet comprimido (estimación conservadora): **~8 TB**.

Un portátil doméstico tiene 1–2 TB de SSD. La promesa de "ejecutarse en portátil moderno como producto principal" (ADR-0000 visión) + capa Derived inmutable (ADR-0006) **no son compatibles** sin una política explícita de:

- No materializar efemérides; computar on-demand.
- O materializar solo ventanas activas y purgar el resto.
- O reducir resolución temporal por defecto.

Los ADRs 0004 y 0006 mencionan "retención configurable por capa" pero **no especifican política**. Esto es deuda diferida con coste físico real.

Si el plan es no materializar efemérides, hay que decirlo. El ADR-0006 actual sugiere lo contrario al hablar de tabla `ephemerides` particionada por ventana temporal.

---

## Findings importantes

### F6 · La precisión SGP4 vs. los thresholds de conjunción es físicamente inconsistente

**ADRs implicados:** 0005, Fase 2 del roadmap.

- Error SGP4 sobre TLE: ~1–3 km en época, crece ~1–3 km/día.
- Thresholds típicos de "conjunción interesante" en literatura: 1–10 km.
- Signal-to-noise ratio ≤ 3.

Phase 2 promete reproducir "al menos el 80% de los eventos de alto Pc publicados por la US Space Force CDM público". Pero el CDM público se genera con **catálogos SP de alta precisión**, no TLE+SGP4. La comparación es entre regímenes distintos. Esperar 80% de recall es voluntarismo, no análisis.

Más importante: el ADR-0005 dice "precisión suficiente para screening". No lo cuantifica. El ratio de falsos positivos esperable con threshold de 1 km y error de 1–3 km es enorme. La capacidad anunciada en Fase 2 puede ser un detector de ruido bien empaquetado.

### F7 · Ollama 7B-8B para razonamiento técnico es estructuralmente débil

**ADRs implicados:** 0009.

El agente de Fase 5 tiene que:
- Leer evidencia multi-fuente (series temporales de elementos, eventos, noticias).
- Razonar sobre causas hipotéticas.
- Distinguir entre maniobra y deriva natural.
- Calibrar confianza.

Modelos 7B–8B en CPU/GPU doméstica:
- Context window típico 8–32k tokens (limitante con RAG denso).
- Tasa de alucinación alta cuando la pregunta sale del corpus común.
- Razonamiento multi-paso degrada rápido.

La conclusión esperable: el agente local va a producir explicaciones plausibles y fluidas que **suenan** correctas y a menudo no lo son. Esto es peor que no tener agente — confianza injustificada sobre output incorrecto. Particularmente grave en un proyecto cuya P2 es "honestidad sobre incertidumbre".

ADR-0009 menciona el riesgo en consecuencias negativas ("calidad inferior") pero no lo evalúa contra P2. La opción Claude opt-in mitiga, pero el default determina la experiencia de la mayoría.

### F8 · "Sin frameworks" no significa "sin abstracciones"; la deuda solo cambia de sitio

**ADRs implicados:** 0009.

Para producir el agente directo, el proyecto necesitará:
- Cliente HTTP a Ollama/Claude.
- Vector store (Chroma, LanceDB, FAISS o sqlite-vss).
- Embedding model (sentence-transformers o equivalente).
- Estrategia de chunking del corpus.
- Retrieval evaluation harness.
- Tool calling pattern si Fase 5 escala a multi-turno.
- Structured output validation con Pydantic (mencionado).
- Prompt versioning system (mencionado).

Esto es un framework propio. La frase "implementación directa" minimiza el coste real de mantener este stack durante 5 años. LangChain pivota rápido **porque** estos problemas son difíciles, no porque sus autores sean negligentes.

La decisión puede ser correcta. La justificación ("frameworks pivotan rápido, mejor código directo") es incompleta porque no compara el coste de mantener el equivalente propio.

### F9 · Gestión de credenciales y secrets es agujero completo

**ADRs implicados:** ninguno. Es la ausencia el hallazgo.

- Space-Track requiere usuario/contraseña.
- CelesTrak ratelimita; producción seria requiere cabeceras `User-Agent` identificables.
- Claude API requiere `ANTHROPIC_API_KEY`.
- Cesium Ion (opt-in) requiere token.
- Futuras fuentes (Heavens-Above, JPL Horizons, etc.) tienen su propio régimen.

ADRs 0000-0009 no mencionan:
- Dónde viven los secrets (env vars, archivo, OS keyring).
- Cómo CI los inyecta sin filtrarlos (tests de regresión necesitan TLE reales).
- Política para contribuidores sin Space-Track account.
- Rotación, expiración, política de fugas.

Este vacío se descubrirá en la primera semana de Fase 1 y forzará un ADR retroactivo. Mejor escribirlo ahora.

### F10 · `engine_version`, `model_version`, `detector_version` sin política son deuda

**ADRs implicados:** 0006.

ADR-0006 introduce versiones por columna como pilar de la auditabilidad. Pero no define:

- ¿SemVer? ¿CalVer? ¿Monotonic int?
- ¿Un fix de bug en upstream `sgp4` incrementa `engine_version`? Si sí, ¿automático o manual?
- ¿Cuántas versiones se mantienen consultables antes de deprecar?
- ¿Quién y cuándo bumpea?
- ¿Hay tabla de equivalencias entre versión y commit del repositorio?

Sin política, en 18 meses tendrás versiones del estilo `"v1"`, `"v1.1-fix"`, `"experiment-2"`, `"prod"`. La auditabilidad prometida se degrada.

### F11 · `import-linter` como única defensa de la regla más importante

**ADRs implicados:** 0002.

La regla "imports solo hacia abajo entre planos" es el invariant central de la arquitectura modular. La única defensa propuesta es `import-linter` en CI.

- `import-linter` es lento en repos grandes y suele desactivarse en pre-commit.
- Su configuración requiere mantenimiento (cada plano nuevo, cada renombrado).
- Si una PR rompe la regla y el lint falla, el incentivo del autor es relajar la regla, no arreglar el código.

Sin un mecanismo más fuerte (revisión humana específica, herramienta más activa como `tach` con bloqueo en pre-commit, o tests de arquitectura ejecutables), la regla se erosiona.

---

## Findings menores

### F12 · ADR-0005 incluye un benchmark no validado como anchor

`"<60s para 30k objetos en 24h con paso 60s"`. El cálculo `30000 × 1440 × ~1µs = 43s` lo hace plausible, pero "marca a validar" en un ADR aceptado se convierte en compromiso de facto. Si el primer benchmark da 90s, vas a tener que justificar la deriva. Mejor sacar el número.

### F13 · Cesium con 30k entidades + tubos de incertidumbre en navegador de portátil no está validado

ADR-0008 promete tubos para representar incertidumbre. A 30k objetos con geometría compleja, WebGL en una iGPU típica de portátil **probablemente** será lento o crasheará. El ADR no menciona fallback (filtrado, LOD, clustering). El criterio P2 (honestidad sobre incertidumbre) puede romperse cuando se reemplace silenciosamente por puntos.

### F14 · "Sin UPDATE" es purista; el mundo real exige soft-delete

**ADR-0006.** Va a haber bugs de parseo que produzcan filas Normalized incorrectas. La política "epoch posterior con corrección" no es suficiente: las filas viejas siguen siendo seleccionables y polucionan agregaciones. Soft-delete vía columna `tombstone` o `valid_to` sería la práctica habitual. El ADR la evitó por elegancia. El precio es complejidad en queries downstream.

### F15 · La heurística de 5 años es inverificable y se usará retroactivamente

**ADR-0000.** "Las decisiones deben evaluarse asumiendo horizonte mínimo de 5 años de mantenimiento potencial" no es un criterio operacional. Es un argumento retórico. En la práctica se invocará para justificar lo que ya se quería hacer ("esto es por el horizonte"). No tiene falsador.

### F16 · IERS / DUT1 / leap seconds como dependencia remota oculta

**ADR-0002, Core/time.** Conversiones precisas TAI/UTC/UT1 requieren datos IERS Bulletin A, que se actualizan semanalmente. `astropy` los descarga automáticamente. Esto es una dependencia de red oculta dentro del módulo Core, contradiciendo local-first sin que ADR-0001 lo aborde. Mitigación trivial (vendar el bundle IERS) pero hay que decidirlo.

### F17 · ITAR / EAR sin mención

**ADR-0000.** Software de seguimiento orbital con detección de maniobras es área que algunas jurisdicciones (US EAR ECCN 9D004, posiblemente ITAR para análisis fino) podrían escrutinar. El proyecto declaradamente tecnológicamente neutro está bien, pero un disclaimer "el cumplimiento regulatorio en cada jurisdicción es responsabilidad del usuario" reduce exposición. El silencio es opción defensible pero conviene ser deliberado al respecto.

### F18 · CLA / DCO no decidido

**ADR-0007.** Apache 2.0 permite contribuciones bajo la misma licencia, pero sin CLA o DCO formal, no hay registro firmado de la cesión de derechos. Para 5 años, decidirlo ahora es más barato que retroceder. Una línea en el ADR ("DCO sign-off requerido en cada PR" o "sin CLA por ahora") cubre el caso.

### F19 · Embeddings y vector store ausentes de ADR-0009

Si Fase 5 hace RAG sobre el catálogo histórico, hay vector store implícito. No está nombrado, no tiene ADR, no tiene política de versionado. El primer commit de Fase 5 introducirá una dependencia sustancial sin discusión arquitectónica.

---

## Lo que el diseño hace bien (para que la crítica no se confunda con hostilidad)

Estos puntos son fuertes y no merecen retoques:

- **Separación Raw inmutable** como invariante científico. Correcta y bien justificada.
- **Apache 2.0** con cláusula de patentes. Es la elección correcta dadas las propiedades declaradas.
- **Plane architecture sobre microservicios**. Decisión sólida para el caso de uso.
- **No frameworks de agente** como dirección general (con la salvedad de F8: ojo al coste oculto).
- **Honestidad sobre incertidumbre (P2)** como propiedad explícita. Poco común en el dominio y valiosa.
- **Template de ADR con sección obligatoria "Alineación con ADR-0000"**. Buen mecanismo de gobernanza, simple y enforceable.
- **Condiciones de archivo digno** declaradas por adelantado. Demuestra madurez del autor y previene zombie projects.
- **Disclaimer operacional neutro** + sin filtros sobre tipos de uso. Coherente y legalmente defensible.

---

## Recomendación

Si yo fuera responsable de aprobar este diseño para construirlo, no daría merge tal cual. Lo aceptaría con **tres preconditions duras**:

1. **Bajar P1 de "bit a bit" a una afirmación falsable y alcanzable.** Mover "bit-exactness" a un objetivo aspiracional dentro de una sección "Reproducibility goals", y declarar P1 como "reproducibilidad bajo entorno declarado". Esto requiere supersedir ADR-0000 con un v1.1 o enmienda formal.

2. **Escribir ADR-0010 "Política de versionado de algoritmos y datos"** antes de cualquier código que use `engine_version`, `model_version` o `detector_version`. Sin política, la auditabilidad se degrada en meses.

3. **Validar empíricamente F4 y F5 (single-writer concurrency, storage scale) durante Fase 1**, antes de cerrar el diseño de Fase 2. Una semana de prototipo benchmark vale más que asumir. Si F4 o F5 dan negativo, ADR-0004 y ADR-0006 necesitan revisión.

Adicionalmente, **dos preconditions blandas** que no bloquean merge pero conviene resolver pronto:

4. Decidir secrets management y escribirlo (ADR-0011).
5. Decidir DCO vs CLA (enmienda a ADR-0007).

Si los autores se niegan a (1), mi recomendación es **NO MERGE**. La propiedad central del proyecto declarada en términos que el stack no puede sostener es un problema de credibilidad que arrastra todo lo demás.

Si los autores aceptan (1) pero no (2) y (3), mi recomendación es **MERGE CONDICIONAL** con la nota de que F4, F5 y F10 deben re-evaluarse en revisión de fin de Fase 1.

Si los autores aceptan (1)(2)(3), mi recomendación es **MERGE**. El diseño restante es sólido.

---

## Nota final

La calidad media de este conjunto de ADRs está por encima de lo habitual. Los problemas señalados no son indicios de descuido; son las costuras que solo aparecen cuando alguien ataca el diseño desde fuera. La presencia de F1-F19 no descalifica el trabajo: la ausencia de un proceso para encontrarlos lo haría.
