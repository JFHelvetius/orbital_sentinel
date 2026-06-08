# ADR-0022: Modelo de scheduling para ingesta periódica

**Estado:** Aceptado
**Fecha:** 2026-06-06
**Autor:** Orbital Sentinel
**Supersede a:** ninguno
**Relacionado con:** ADR-0001 (Local-first, reproducible-first), ADR-0002 enmienda 1 + 2, ADR-0004 enmienda 2, ADR-0006, ADR-0011, ADR-0012, ADR-0019

---

## Contexto

ADR-0002 enumera Orchestration como plano 2 con "scheduling, reintentos, backoff" entre sus primitivas. ADR-0002 enmienda 1 dejó ese punto pendiente: *"(planeadas, no implementadas aún): scheduling, reintentos, backoff"*.

Fase 2 cerrada (ADR-0021) reveló la pregunta concreta: para soportar **ingesta periódica de CelesTrak** (prerrequisito de Fase 3 — detección de maniobras sobre time-series), ¿el proyecto:

- **Opción A**: implementa un scheduler **in-process** (APScheduler o equivalente), convirtiéndose en daemon?
- **Opción B**: **delega** scheduling al sistema operativo o entorno externo (cron, Windows Task Scheduler, systemd timers, GitHub Actions cron, k8s CronJobs)?

Esta no es decisión de feature: es **contrato operacional**. Determina si Orbital Sentinel es "tool invocada por usuario" o "service que corre solo".

## Decisión

**Opción B**: scheduling **delegado al sistema operativo o entorno externo**. Orbital Sentinel **no** implementa scheduler in-process.

El comando para ingesta periódica es `orbital-sentinel ingest <dataset>`. El usuario (o su CI) configura su scheduler favorito para invocarlo a la cadencia que desee.

## Justificación

### 1. Coherencia con local-first (ADR-0001/0012)

Un daemon Orbital Sentinel corriendo permanentemente:

- Mantiene un proceso del proyecto vivo en la máquina del usuario.
- Reserva recursos (memoria, file handles, hilos) incluso cuando no hace nada.
- Requiere mecanismo de arranque/parada (systemd unit, Windows service, etc.) que el usuario debe administrar.

Delegando a OS:

- Cero procesos del proyecto vivos entre invocaciones.
- El usuario administra solo su scheduler favorito (que ya administra para otras cosas).
- Orbital Sentinel sigue siendo "tool invocada", no "service".

No es violación estricta de local-first, pero es un **deslizamiento de contrato operacional** que el proyecto rechaza.

### 2. Idempotencia ya garantizada por construcción

El sistema está diseñado para invocación repetida sin coordinación externa:

- `tle_snapshots` content-addressable (ADR-0006 + ADR-0019): mismos bytes → mismo hash → no-op.
- `orbital_elements` particionado por `engine_version` y `content_hash_source` (ADR-0006): re-derivar no duplica.
- `pyarrow.write_table` + `tmp.replace(path)` atómicos (validado en ADR-0004 enmienda 2): cero corrupción bajo concurrencia.

Un scheduler in-process no añade nada que el sistema no resuelva ya por construcción.

### 3. Portabilidad operacional

Mecanismos de scheduling OS-level disponibles **sin esfuerzo del proyecto**:

- Linux/macOS: `cron`, `systemd timers`.
- Windows: `Task Scheduler` (PowerShell `Register-ScheduledTask`).
- CI: GitHub Actions `schedule:` cron, GitLab CI scheduled pipelines.
- Containers/Cloud: cualquier orchestrator (k8s CronJobs, ECS Scheduled Tasks).

Cada uno con failure handling, logging y observabilidad propios. El proyecto se beneficia de todos sin importar nada.

### 4. Coste real de implementar in-process

Un scheduler in-process maduro requiere:

- **Persistencia de estado**: ¿cuándo se ejecutó la última vez? ¿qué falló?
- **Modelo de concurrencia**: ¿threads, asyncio, multiprocessing?
- **Recuperación tras kill**: ¿qué pasa si el daemon muere a mitad de un run?
- **Lock**: ¿dos invocaciones de orbital-sentinel a la vez?
- **Configuración del intervalo**: ¿config file, env var, CLI flag?
- **Observabilidad**: ¿cómo el usuario sabe qué pasó hace 3 días?

Cada problema está resuelto en OS schedulers maduros desde hace décadas. Reimplementarlos no aporta valor; reduce calidad media.

### 5. La decisión no impide trabajo futuro

Si en algún futuro hipotético el proyecto decide ofrecer un daemon (por razones no anticipadas hoy), nada en este ADR lo prohíbe: requeriría un nuevo ADR que supersedee este. La reversibilidad existe.

## Lo que este ADR NO decide

- **Cadencia recomendada** de ingesta. Decisión del operador (típicamente 6–12 h para CelesTrak GP catalog).
- **Política de reintentos** dentro de una invocación individual. ADR posterior puede añadir retry/backoff al `UrllibTransport` si la realidad operacional lo exige.
- **Runbook concreto** ("cómo configurar mi cron"). Trabajo separado en `docs/operations/`, post-aceptación si se justifica.
- **Multi-fuente** (Space-Track, Heavens-Above, etc.). Independiente del scheduling.
- **Política de retención** de Raw / Normalized / detecciones. ADR independiente cuando llegue Fase 3+.
- **Observabilidad/logging interno**. Las herramientas OS de scheduling ya producen logs; el proyecto puede consultarse via queries sobre `fetched_at`.

## Consecuencias

### Positivas

- **Cero proceso del proyecto vivo** entre invocaciones. Local-first preservado.
- **Cero dependencias nuevas**.
- **Portabilidad** a cualquier entorno con scheduling primitivo (incluye CI/CD as scheduling).
- Idempotencia + atomicidad ya garantizadas hacen la integración trivial.
- Aclara el ámbito real de "Orchestration primitives" en ADR-0002 (ver enmienda 2).

### Negativas

- Usuario debe configurar su scheduler favorito (no es config interna del proyecto). Mitigado: documentación operacional posterior puede dar snippets típicos.
- Sin "ver estado del scheduling" desde dentro de Orbital Sentinel. Mitigado: queries sobre `tle_snapshots.fetched_at` muestran historial real de ingestas.

### Neutras

- ADR-0002 enmienda 2 (paralela a esta aceptación) reduce el alcance declarado de Orchestration primitives.

## Alternativas consideradas

### A. In-process scheduler con APScheduler (mencionado en ADR-0002 original como ejemplo)
**Razón de rechazo:** dependencia nueva, daemon implícito, complejidad de configuración. Reinventa cron mal.

### B. In-process scheduler con stdlib (`sched`, `threading.Timer`)
**Razón de rechazo:** sin dep nueva pero sigue requiriendo proceso vivo. Mismas complejidades de estado, lock y recovery que A.

### C. Pluggable scheduler (interfaz abstracta que soporta in-process y externo)
**Razón de rechazo:** interfaz prematura, YAGNI estricto. Si en el futuro se justifica modo daemon, ADR específico decide.

### D. CI-as-scheduler único (e.g., solo GitHub Actions cron es supported)
**Razón de rechazo:** acopla el modelo operacional a una plataforma específica. OS-level scheduling es genérico y cubre CI, daemon-less local, y orchestrators cloud por igual.

## Alineación con ADR-0000

- **Refuerza P3** (coste cero baseline): cero proceso vivo cuando no hay trabajo activo.
- **Refuerza P4, P1** (reproducibilidad / trazabilidad): cada invocación es self-contained con sus content_hashes; el orden temporal lo registra el sistema operativo, no estado interno del proyecto.
- **Refuerza P8** (local-first): no introduce service-like behavior.
- **Compatible con P7**: el usuario invoca scheduling sobre fuentes públicas sin acoplamiento del proyecto a una plataforma.
- **Sin tensiones.**

## Implicaciones operacionales (informativo, NO parte del contrato del ADR)

Tras aceptar este ADR, configurar ingesta periódica es trabajo del operador. Patrones típicos:

**Linux/macOS (cron):**

```cron
0 */6 * * *  cd /path/to/orbital-sentinel && .venv/bin/orbital-sentinel ingest stations
```

**Windows (Task Scheduler):**

```powershell
Register-ScheduledTask -TaskName "orbital-sentinel ingest stations" `
    -Trigger (New-ScheduledTaskTrigger -Daily -At 03:00) `
    -Action (New-ScheduledTaskAction `
        -Execute "C:\Path\To\orbital-sentinel\.venv\Scripts\orbital-sentinel.exe" `
        -Argument "ingest stations")
```

**GitHub Actions (CI as periodic ingestion):**

```yaml
on:
  schedule:
    - cron: "0 */6 * * *"
```

Estos snippets son **informativos**. El runbook operacional concreto vive en [`docs/operations/periodic-ingestion.md`](../operations/periodic-ingestion.md).

## Referencias

- ADR-0001 (Local-first, reproducible-first).
- ADR-0002 (planos) + enmienda 1 (workflows de composición) + enmienda 2 (reducción de alcance de primitivas, aceptada con este ADR).
- ADR-0004 enmienda 2 (benchmark concurrencia: cero corrupción confirmada).
- ADR-0006 (capas inmutables, sin UPDATE).
- ADR-0019 (content-addressable persistence).
- POSIX cron(8). Microsoft `Register-ScheduledTask` cmdlet.

---

## Historial de enmiendas

*Sin enmiendas a fecha de aceptación.*
