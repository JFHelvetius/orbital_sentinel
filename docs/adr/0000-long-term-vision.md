# ADR-0000: Visión a largo plazo de Orbital Sentinel

**Estado:** Aceptado (enmienda 1)
**Fecha:** 2026-06-03
**Autor:** Orbital Sentinel — autor fundador
**Supersede a:** ninguno
**Relacionado con:** todos los ADR posteriores

---

## Naturaleza de este documento

Los ADR habitualmente capturan decisiones técnicas con consecuencias acotadas: qué base de datos, qué motor de propagación, qué formato de serialización. Este ADR captura algo distinto: la brújula.

Antes de elegir cualquier tecnología, este documento fija qué problema resuelve el proyecto, para quién, y bajo qué propiedades irrenunciables. Sin esa brújula, los ADR técnicos posteriores no pueden evaluarse como buenos o malos; solo como coherentes o incoherentes con un marco. Este ADR construye ese marco.

Cualquier ADR posterior debe declarar explícitamente cómo se alinea con éste. Si un ADR técnico entra en tensión con alguna de las propiedades irrenunciables aquí enumeradas, esa tensión debe declararse y justificarse, no ocultarse.

## Contexto

Los datos para entender el comportamiento de los objetos en órbita terrestre son públicos: catálogos TLE de US Space Force, OMM de Space-Track, reentradas anunciadas, lanzamientos registrados. La capacidad de **convertir esos datos en comprensión**, sin embargo, está concentrada en tres tipos de actores:

1. **Sistemas operacionales cerrados**: USSF 18 SDS, comerciales como LeoLabs o Slingshot. Calidad alta, acceso restringido, lógica opaca.
2. **Software académico**: bibliotecas potentes pero con mantenimiento intermitente, sin envoltura productizable, y en muchos casos archivadas (caso paradigmático: poliastro).
3. **Productos comerciales caros**: AGI / Ansys STK, FreeFlyer. Excelentes, lejos de un usuario individual.

Falta una cuarta categoría: una herramienta **profesional**, **abierta**, **mantenida** y **rigurosa**, ejecutable por cualquier persona técnica con un portátil moderno. Orbital Sentinel propone ocupar esa categoría.

## Misión

Hacer accesible al público técnico la capacidad de **observar, propagar y razonar sobre la población satelital** usando exclusivamente datos abiertos, con honestidad sobre incertidumbre.

Cada palabra de esa frase es deliberada:

- **Público técnico** — no público general. No simplificamos al punto de engañar.
- **Observar, propagar y razonar** — tres capacidades distintas, en orden de dificultad. Razonar es Fase 5, no Fase 1.
- **Datos abiertos** — restricción no negociable. Si una capacidad solo es posible con datos cerrados, no entra en el proyecto.
- **Honestidad sobre incertidumbre** — la propiedad de rigor que distingue este proyecto de un juguete con buen aspecto.

## Horizonte de mantenimiento como heurística de diseño

Las decisiones arquitectónicas de este proyecto deberán evaluarse asumiendo un horizonte mínimo de 5 años de mantenimiento potencial.

Esto no es un compromiso del autor con un calendario, sino una regla para evaluar trade-offs: una decisión cuyo coste agregado en una ventana de cinco años supera el de una alternativa razonable no debe adoptarse aunque sea atractiva a corto plazo. El horizonte es la lente, no la promesa.

## Visión de estado deseado

Estado del proyecto cuando esté maduro, descrito sin referencias temporales:

- Es una **herramienta de referencia** en astrodinámica práctica con datos públicos para quien no tenga acceso a sistemas operacionales cerrados.
- Mantiene un **catálogo histórico continuo** de elementos orbitales desde su fecha de inicio, consultable, reproducible y citable por hash.
- Su capacidad de **detección de maniobras** ha sido validada contra ground truth público conocido (ISS, eventos documentados).
- Su capacidad de **detección de anomalías** es defendible: cada anomalía detectada lleva su evidencia, no solo su score.
- Sigue **ejecutándose en un portátil moderno** como producto principal. Cualquier desviación de esto exige ADR explícito.

"Maduro" no es una fecha. Es un estado verificable. Si la verificación falla durante un tiempo prolongado, la sección de condiciones de archivo digno aplica.

## Audiencias

### Audiencia primaria
- Investigadores en astrodinámica y space situational awareness.
- Operadores de pequeños satélites (cubesats, smallsats) sin contrato de SSA externo.
- Periodistas y analistas de política espacial que necesitan verificar afirmaciones.
- Educadores en astrodinámica e ingeniería aeroespacial.
- Hobbyistas técnicos con base científica.

### Audiencia secundaria
- Cualquier proyecto o entidad que construya productos derivados sobre la base de Orbital Sentinel. La licencia permisiva (ver ADR-0007) habilita este uso sin filtros sobre tipo de aplicación.

### No-audiencia
- Usuarios finales sin formación técnica que esperen un producto consumer-grade.
- Casos que requieran sistemas certificados con garantías formales de precisión. El régimen TLE+SGP4 no soporta ese requisito como propiedad del propio dato.

Reconocer la no-audiencia es una declaración de límites técnicos, no un juicio sobre quién está autorizado a usar el código.

## Propiedades irrenunciables

Estas propiedades son invariantes del sistema. Ningún ADR posterior puede violarlas. Si un ADR posterior necesita relajar alguna, debe superseder a este ADR-0000 explícitamente, justificando por qué la propiedad ya no aplica.

### P1. Reproducibilidad bajo entorno declarado
Cualquier inferencia, hoy o en el pasado, debe poder reproducirse a partir de cuatro coordenadas declaradas:

- **Código** identificado por commit del repositorio.
- **Configuración** identificada por hash del archivo de config usado en el run.
- **Datos crudos** identificados por `content_hash`.
- **Entorno de ejecución** declarado: lockfile, sistema operativo, arquitectura, librerías nativas relevantes.

La reproducción es **bit-exacta dentro del mismo entorno declarado** y **funcionalmente equivalente** entre entornos compatibles. **No se garantiza identidad bit a bit entre arquitecturas, compiladores o vendors distintos**: esa garantía no es físicamente alcanzable en el stack del proyecto y declararla sería deshonesto.

Esta propiedad es la diferencia entre una herramienta científica y una opinión bonita.

### P2. Honestidad sobre incertidumbre
SGP4 sobre TLEs tiene errores típicos de 1–3 km en época y crecimiento de ~1–3 km/día. Toda visualización, API y reporte del sistema debe representar esa incertidumbre, no esconderla. **Una línea fina dibujada como trayectoria es una mentira.**

### P3. Coste de operación cercano a cero
El proyecto debe poder ejecutarse, en su totalidad, en un portátil doméstico moderno sin servicios de pago. Las APIs externas de pago son siempre opcionales y nunca caminos críticos.

### P4. Validación operacional de reproducibilidad
La propiedad P1 no se sostiene por declaración; se verifica con tests de regresión que reejecutan inferencias pasadas en el entorno declarado y comparan contra outputs canónicos almacenados. Cualquier release publica el estado de esta verificación. Si la verificación falla sin causa declarada, el release no sale.

### P5. Licencia permisiva
La licencia es Apache-2.0. Permite uso comercial, derivado, y sublicensing sin filtros. Esto es deliberado: queremos que se construya sobre el proyecto, no impedirlo.

### P6. Documentación en pie de igualdad con el código
Una funcionalidad sin documentación de usuario no se considera entregada. Una decisión sin ADR no se considera tomada. Esta no es burocracia: es la condición de supervivencia del proyecto si cambia el mantenedor.

### P7. Fuentes públicas y reproducibles como primarias
Cualquier capacidad del sistema debe ser obtenible con fuentes públicas y reproducibles. Datos de pago o cerrados pueden ser **complemento opcional**, nunca **dependencia**. Criterio práctico: si un nuevo usuario no puede reproducir un resultado sin firmar contratos ni pagar suscripciones, ese resultado no pertenece al núcleo.

### P8. Local-first
Toda funcionalidad fundamental del sistema debe poder ejecutarse localmente. Los servicios externos pueden ampliar capacidades pero no son dependencias obligatorias para la operación básica. Esta propiedad está operacionalizada en ADR-0012.

## No-objetivos explícitos

Lo que este proyecto **nunca** será, mientras ADR-0000 esté vigente:

- **No será un servicio gestionado comercial.** Si alguien quiere construirlo encima, la licencia lo permite, pero no es responsabilidad del proyecto.
- **No competirá con sistemas operacionales cerrados** en alcance, precisión o latencia.
- **No proporcionará outputs aplicables en producción sin verificación independiente.** Es una declaración técnica sobre el régimen de precisión, no un filtro sobre el caso de uso.
- **No usará datos clasificados ni de pago como fuentes primarias.** Ver P7.
- **No publicará elementos orbitales que no estén ya en catálogos públicos.** No somos un canal de descubrimiento independiente; razonamos sobre lo público.

## Disclaimer operacional

Orbital Sentinel no proporciona garantías operacionales para usos civiles, comerciales, gubernamentales o militares. Los outputs del sistema son material analítico, no recomendaciones aplicables sin verificación independiente. Cualquier uso aplicado es responsabilidad exclusiva del usuario.

Este disclaimer es técnicamente neutro: el proyecto no filtra usuarios ni casos de uso. La licencia Apache-2.0 (ADR-0007) reafirma esa neutralidad.

## Cumplimiento legal de fuentes

Los proveedores de datos públicos (Space-Track, CelesTrak y similares) establecen términos de uso como condición de acceso. El proyecto los respeta porque son la contrapartida contractual del acceso. Si un término de servicio cambia y limita una capacidad, el proyecto se adapta o documenta la limitación.

## Modelo de sostenibilidad

El proyecto debe sobrevivir sin presupuesto y sin equipo dedicado.

**Estado inicial.** Maintainer único: el autor fundador. Trabajo part-time sostenido, sin compromiso de cadencia. Aceptación de PRs externas reactiva.

**Estado intermedio.** Posibles co-maintainers si emerge contribución externa sostenida. Governance ligera y documentada: política de revisión, criterios de merge.

**Estado consolidado.** Posible afiliación a una fundación neutra (NumFOCUS, OpenSSF, OpenCollective) si y solo si la base de usuarios lo justifica. Hasta entonces, ninguna estructura legal añadida.

**Governance.** El proyecto declara públicamente quién lo mantiene en cada momento, en `MAINTAINERS.md`. La identidad de los mantenedores es información estructural, no biográfica.

Ningún modelo de monetización es objetivo. Donaciones pasivas (GitHub Sponsors) aceptables si no condicionan la dirección.

Cualquier momento en el que sostener el proyecto requiera una promesa que no se pueda cumplir es un momento para reducir alcance, no para acelerar.

## Condiciones de archivo digno

Un proyecto de horizonte largo debe declarar de antemano bajo qué condiciones se cierra. Archivar a tiempo es responsabilidad; archivar tarde es daño.

Orbital Sentinel se archivará — con notificación pública, último release estable, y documentación clara del estado final — si se cumple alguna de:

1. **Inviabilidad técnica demostrada**: si se demuestra que SGP4 sobre TLEs es insuficiente para los casos de uso centrales de las Fases 1–4, y no existe alternativa compatible con P3 y P7.
2. **Colapso de fuentes**: si las fuentes públicas de TLEs/OMM desaparecen o pasan a régimen cerrado durante más de doce meses sin alternativa equivalente.
3. **Insostenibilidad de mantenimiento**: si durante doce meses consecutivos no hay capacidad de respuesta a issues críticos ni reemplazo viable del mantenedor.
4. **Captura por intereses incompatibles con las propiedades irrenunciables**: si el control del proyecto pasa, por cualquier vía, a un actor cuyo uso del mismo viole P1–P8.

En cualquiera de esos casos, el proyecto se archiva en estado legible, con un `ARCHIVED.md` que explique por qué, y la licencia permisiva garantiza que cualquier interesado pueda continuar el código sin colaboración previa.

## Cómo evaluamos salud del proyecto

Sin métricas numéricas dogmáticas atadas a calendario. Cada release publica una evaluación cualitativa sobre cuatro ejes:

1. **Cobertura de datos.** Qué fracción de la población satelital catalogada públicamente es accesible desde el sistema, y qué fuentes la sustentan. Se reporta el dato bruto, no un objetivo.
2. **Calidad de inferencia.** Errores de propagación contra vectores de referencia conocidos; recall y precisión contra ground truth de eventos públicos. Se publican distribuciones, no promedios.
3. **Reproducibilidad operativa.** Capacidad de regenerar cualquier output histórico desde los datos crudos por hash. Se verifica con tests de regresión que reejecutan inferencias antiguas.
4. **Salud de mantenimiento.** Tiempo de CI, antigüedad de issues sin triar, frecuencia de releases. Sin objetivos numéricos rígidos; lo importante es la tendencia y la honestidad sobre ella.

Si alguno de estos ejes se degrada sostenidamente sin explicación, debe disparar el ejercicio de revisión del ADR-0000.

## Cómo este ADR limita a los siguientes

Todo ADR técnico posterior debe incluir una sección **"Alineación con ADR-0000"** que conteste:

1. ¿Cuáles de las propiedades irrenunciables P1–P8 ve afectadas esta decisión?
2. ¿La decisión las refuerza, las mantiene neutras, o introduce alguna tensión?
3. Si hay tensión, ¿cuál es la mitigación o por qué la tensión es aceptable?

La plantilla de ADR (`template.md`) incluye esta sección. Una PR con un ADR que la omita no debe mergearse.

## Revisión de este ADR

Este ADR se revisa formalmente con cadencia anual. La revisión puede resultar en:

- **Confirmación sin cambios** (lo normal en períodos de continuidad).
- **Enmienda** añadida al historial al pie, sin reescribir el cuerpo.
- **Supersesión** por un ADR-0000-v2 si la visión cambia sustancialmente. Las supersesiones requieren consenso explícito de los mantenedores activos.

## Alineación con ADR-0000

Este ADR define las propiedades de referencia. No se alinea con nadie; los demás se alinean con él.

## Referencias

- Vallado, D. A. (2013). *Fundamentals of Astrodynamics and Applications*, 4th ed.
- Hoots, F. R., & Roehrich, R. L. (1980). *Spacetrack Report No. 3: Models for Propagation of NORAD Element Sets*.
- Nygard, M. (2011). *Documenting Architecture Decisions.*
- Apache Software Foundation. *Apache License, Version 2.0*.

---

## Historial de enmiendas

### 2026-06-03 — Enmienda 1
- **P1 reformulada** de "Trazabilidad bit a bit" a "Reproducibilidad bajo entorno declarado". Motivación: el red-team review (F1) demostró que la propiedad original sobrepromete lo que el stack puede sostener (Python wheels por arquitectura, reordering de BLAS, no determinismo de CUDA, model in-place updates en Ollama). La propiedad nueva es alcanzable y verificable.
- **P4 reformulada** de "Reproducibilidad" (definicional) a "Validación operacional de reproducibilidad". Motivación: con P1 ya incluyendo entorno declarado, P4 se especializa en cómo se enforza la propiedad, no en su definición. Las dos propiedades dejan de ser redundantes.
- **P8 reapunta a ADR-0012** en lugar de ADR-0001 (que queda superseded).
- **ADR-0001 superseded** por ADR-0012 (Local-First Operation) y ADR-0013 (Reproducibility Under Declared Environment). Motivación: el red-team review (F2) demostró que local-first y reproducible-first son principios ortogonales con tensiones reales; acoplarlos en un único ADR ocultaba esas tensiones.
- **ADR-0010 añadido**: Versioning Policy. Cubre `engine_version`, `schema_version`, `dataset_version`, `derived_data_version`, reglas de compatibilidad. Motivación: F10 del red-team review identificó la ausencia de esta política como deuda inminente.
- **ADR-0011 añadido**: Secrets Management. Cubre Space-Track, Anthropic, Cesium Ion, futuras credenciales. Motivación: F9 del red-team review identificó el vacío.
