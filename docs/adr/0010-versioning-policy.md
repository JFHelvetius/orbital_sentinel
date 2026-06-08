# ADR-0010: Versioning Policy

**Estado:** Aceptado
**Fecha:** 2026-06-03
**Autor:** Orbital Sentinel
**Supersede a:** ninguno
**Relacionado con:** ADR-0000 (P1, P4, P6), ADR-0006, ADR-0013

---

## Contexto

- ADR-0006 introdujo columnas de versión (`engine_version`, `model_version`, `detector_version`) como mecanismo de auditabilidad sin definir cómo se gestionan.
- El red-team review (F10) identificó la ausencia de política como deuda inminente: sin reglas claras, las versiones derivan a strings ad-hoc en meses.
- Versiones distintas viven simultáneamente en la misma tabla por diseño (ADR-0006). El esquema de versionado debe ser ordenable, único y derivable del código.

## Decisión

### Dominios de versionado

El sistema declara cuatro dominios de versionado, cada uno con su columna y semántica:

| Dominio              | Columna                 | Qué identifica                                                                         |
|----------------------|-------------------------|-----------------------------------------------------------------------------------------|
| Motor de cómputo     | `engine_version`        | Versión del propagador, detector o modelo que produjo una fila Derived.                |
| Esquema de datos     | `schema_version`        | Versión del esquema Parquet de la tabla.                                               |
| Dataset crudo        | `dataset_version`       | Versión del snapshot de una fuente de Raw (e.g. dump diario de CelesTrak).             |
| Producto derivado    | `derived_data_version`  | Versión de un dataset Derived publicado como release (e.g. catálogo de conjunciones).  |

### Formato

Todas las versiones usan **SemVer 2.0** (`MAJOR.MINOR.PATCH`) con sufijo opcional de pre-release (`-rc1`, `-beta`, etc.).

- **MAJOR**: cambio incompatible. Datos producidos con versión MAJOR distinta no se mezclan en agregaciones sin conversión explícita.
- **MINOR**: cambio backward-compatible que añade información (e.g. nueva columna nullable, ampliación de rango admisible).
- **PATCH**: corrección de bug que no altera el contrato de salida.

### Reglas de bump

- Cada commit que altere el comportamiento de un componente versionado debe bumpear la versión correspondiente en el mismo PR. CI rechaza PRs que cambien lógica versionada sin bump.
- **No hay bump automático.** Las versiones se incrementan en el `pyproject.toml` del componente o en su manifest específico, vía PR, con justificación en el commit message.
- **Bug fix en dependencia externa** (e.g. nueva release de `sgp4`): bumpea `engine_version` PATCH si los outputs cambian, MINOR si añade capacidades, MAJOR si rompe.
- **Cambio de esquema Parquet**: bumpea `schema_version`. PATCH no aplica (cualquier cambio de esquema es al menos MINOR).
- **Snapshot nuevo de una fuente**: bumpea `dataset_version` MINOR cuando el contenido cambia normalmente; MAJOR si la fuente cambia su formato.

### Reglas de compatibilidad

- **Lectura forward-compatible**: el sistema debe poder leer cualquier MINOR superior dentro del mismo MAJOR, ignorando campos desconocidos.
- **Lectura backward-compatible**: el sistema debe poder leer cualquier MINOR anterior dentro del mismo MAJOR. Campos faltantes son `NULL`.
- **Entre MAJOR distintas**: requiere migración explícita registrada en `catalog/migrations/`. Sin migración, las filas no se mezclan en agregaciones.
- **Deprecación**: una versión se marca `deprecated` en docs cuando una sucesora estable lleva ≥6 meses publicada. Las versiones deprecadas siguen siendo leíbles indefinidamente; solo pierden recomendación.

### Trazabilidad

- Cada componente versionable expone una constante `__version__` derivada de su `pyproject.toml` o manifest.
- Cada fila Derived que escribe ese componente persiste el valor exacto en su columna correspondiente.
- Tests de regresión verifican que outputs producidos por versión V son leíbles por todas las versiones ≥V dentro del mismo MAJOR.

## Justificación

- SemVer es el estándar más reconocido; comunica intención al usuario sin requerir lectura de docs.
- Versionado por columna (no por sufijo de tabla) preserva la propiedad de ADR-0006 de coexistencia.
- Bump manual con enforcement de CI alinea responsabilidad con autoría del cambio.
- Reglas de compatibilidad explícitas permiten políticas de migración programáticas.

## Consecuencias

**Positivas**
- Auditabilidad efectiva, no solo nominal.
- Migraciones programáticas posibles.
- Comparación entre versiones es un `SELECT` por columna.

**Negativas**
- CI necesita check de "version bumped" por componente.
- Coste cognitivo de decidir MAJOR/MINOR/PATCH en cada PR.

**Neutras**
- Las versiones MAJOR no se reciclan dentro del mismo dominio: una vez emitida `v2.0.0`, no vuelve a aparecer.

## Alternativas consideradas

### A. Versionado por hash de commit
**Razón de rechazo:** no ordenable semánticamente; ilegible en queries.

### B. CalVer (`YYYY.MM.DD`)
**Razón de rechazo:** no comunica compatibilidad; requiere convención adicional.

### C. Monotonic int
**Razón de rechazo:** plano. Forzaría que todo cambio sea breaking.

### D. Sin política, ad-hoc por componente
**Razón de rechazo:** lo que el red-team review F10 ya rechazó.

## Alineación con ADR-0000

- **Refuerza P1, P4** (operacionaliza la trazabilidad declarada).
- **Refuerza P6** (versionado documentado y enforceable).
- **Sin tensiones.**

## Referencias

- Preston-Werner, T. *Semantic Versioning 2.0.0.* https://semver.org

---

## Historial de enmiendas

*Sin enmiendas a fecha de aceptación.*
