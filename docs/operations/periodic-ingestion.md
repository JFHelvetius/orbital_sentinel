# Ingesta periódica de TLEs

**Audiencia:** operadores que vayan a ejecutar Orbital Sentinel de forma recurrente.
**Prerrequisito:** [ADR-0022](../adr/0022-scheduling-model.md) — el scheduling está deliberadamente fuera del proyecto. Este runbook **no** implementa scheduler; documenta cómo configurar el del sistema operativo para invocar el CLI.

---

## Comando único

Toda ingesta periódica es siempre la misma invocación:

```
orbital-sentinel ingest <dataset>
```

Sin flags adicionales, usa los paths por defecto:

```
data/cache/        # cache content-addressable (transitorio)
data/raw/          # capa Raw, snapshots Parquet
data/normalized/   # capa Normalized, orbital_elements
```

Si quieres ubicar los datos en otro lugar:

```
orbital-sentinel ingest stations \
    --cache-root      /var/lib/orbital-sentinel/cache \
    --raw-root        /var/lib/orbital-sentinel/raw \
    --normalized-root /var/lib/orbital-sentinel/normalized
```

**Importante**: todas las invocaciones que compartan datos deben apuntar a los mismos `--raw-root` y `--normalized-root`. La idempotencia content-addressable depende de ello.

## Idempotencia (qué pasa cuando re-invocas)

ADR-0019 garantiza que el comando es **seguro de invocar a cualquier cadencia**:

- Si CelesTrak devuelve los mismos bytes → `content_hash` igual → no se escribe nada nuevo. Re-invocaciones inocuas.
- Si CelesTrak devuelve bytes distintos (TLE actualizado) → `content_hash` nuevo → snapshot adicional en Raw, deriva en Normalized.

**No necesitas coordinar invocaciones**. Dos crons que se solapen accidentalmente no corrompen el catálogo: el filesystem rename atómico (`tmp.replace`) y el naming por content_hash hacen la concurrencia segura. Esto está verificado empíricamente por el benchmark de [ADR-0004 enmienda 2](../adr/0004-duckdb-parquet-store.md).

## Plataformas

### Linux/macOS · cron

Edita el crontab del usuario:

```
crontab -e
```

Añade una línea:

```cron
0 */6 * * *  cd /path/to/orbital-sentinel && /path/to/orbital-sentinel/.venv/bin/orbital-sentinel ingest stations >> /var/log/orbital-sentinel/ingest.log 2>&1
```

Notas:

- `cd /path/...` antes del comando para que los paths por defecto de `data/` sean estables.
- `>> ... 2>&1` redirige stdout+stderr a un log. Sin esto, cron envía el output por email al usuario y suele perderse.
- Si invocas varios datasets, una línea por dataset. Pueden solapar en tiempo sin riesgo.

### Linux · systemd timer (recomendado para production)

Más robusto que cron: mejor logging via `journalctl`, gestión de dependencias y recovery.

`/etc/systemd/system/orbital-sentinel-ingest@.service`:

```ini
[Unit]
Description=Orbital Sentinel — ingest %i
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
WorkingDirectory=/opt/orbital-sentinel
ExecStart=/opt/orbital-sentinel/.venv/bin/orbital-sentinel ingest %i
User=orbital-sentinel
Group=orbital-sentinel

[Install]
WantedBy=multi-user.target
```

`/etc/systemd/system/orbital-sentinel-ingest@.timer`:

```ini
[Unit]
Description=Orbital Sentinel — ingest %i every 6h

[Timer]
OnBootSec=10min
OnUnitActiveSec=6h
Persistent=true

[Install]
WantedBy=timers.target
```

Activar:

```
sudo systemctl enable --now orbital-sentinel-ingest@stations.timer
sudo systemctl enable --now orbital-sentinel-ingest@active.timer
```

Ver historial:

```
journalctl -u orbital-sentinel-ingest@stations.service --since "24 hours ago"
systemctl list-timers orbital-sentinel-ingest@*
```

### Windows · Task Scheduler

PowerShell elevado:

```powershell
$action = New-ScheduledTaskAction `
    -Execute "C:\opt\orbital-sentinel\.venv\Scripts\orbital-sentinel.exe" `
    -Argument "ingest stations" `
    -WorkingDirectory "C:\opt\orbital-sentinel"

$trigger = New-ScheduledTaskTrigger `
    -Once -At (Get-Date) `
    -RepetitionInterval (New-TimeSpan -Hours 6)

$settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10) `
    -RestartOnFailure $false

Register-ScheduledTask `
    -TaskName "OrbitalSentinel-ingest-stations" `
    -Description "Periodic CelesTrak ingestion: stations group" `
    -Action $action -Trigger $trigger -Settings $settings
```

Ver historial: `Get-ScheduledTaskInfo -TaskName "OrbitalSentinel-ingest-stations"`.

### GitHub Actions cron (uso limitado)

**Honestidad operacional**: los runners de GitHub Actions son efímeros. `data/` se pierde al final de cada run salvo que se commitee de vuelta al repo o se persista en S3/artifact storage. Para production data esto es generalmente **inaceptable**.

GitHub Actions cron es útil como:

- **Smoke test periódico** (que la ingesta sigue funcionando contra el CelesTrak real, sin retener datos).
- **Trigger remoto** que dispara un job en infraestructura propia (vía webhook).

No como reemplazo de un scheduler local.

## Cadencia: qué número elegir

**El proyecto no recomienda una cadencia.** Depende de qué dataset y para qué uso. Algunos datos de referencia (informativos, no normativos):

- CelesTrak refresca los catálogos GP típicamente cada pocas horas.
- US Space Force publica TLEs nuevos del catálogo público con cadencia variable por objeto (típicamente diaria para LEO, menor para GEO).
- Invocaciones por debajo de 1h al mismo dataset suelen ser desperdicio: pocas veces hay TLE nuevo en ese intervalo.
- Cadencias por encima de 24h pierden TLEs intermedios si llegan a cambiar varias veces al día.

Rango típico razonable: **entre 4h y 12h** para CelesTrak GP groups. El operador ajusta tras observar tasa de cambios real en su catálogo.

## Observabilidad: ¿está pasando algo?

El proyecto **no emite logs estructurados** ni alertas. La observabilidad es:

1. **El log del scheduler del OS** (cron mail, `journalctl`, Event Viewer).
2. **Inspección directa del catálogo**.

Para verificar que la ingesta está acumulando snapshots, una sesión Python sobre el catálogo:

```python
from datetime import datetime, timedelta, timezone
from pathlib import Path
from orbital_sentinel.catalog import TLESnapshotsRepository

repo = TLESnapshotsRepository(Path("data/raw"))
total = repo.count()
print(f"Total snapshots: {total}")

cutoff = datetime.now(timezone.utc) - timedelta(days=1)
recent = [s for s in repo.iter_all() if s.fetched_at >= cutoff]
print(f"Snapshots últimas 24h: {len(recent)}")
for s in sorted(recent, key=lambda r: r.fetched_at):
    print(f"  {s.fetched_at}  {s.dataset}  {s.content_hash[:12]}...  n_bytes={s.n_bytes}")
```

O directamente con DuckDB sobre los Parquet:

```bash
duckdb -c "
  SELECT
    DATE(fetched_at) AS day,
    dataset,
    COUNT(*) AS n_snapshots,
    SUM(n_bytes) AS total_bytes
  FROM read_parquet('data/raw/**/*.parquet', hive_partitioning=false)
  GROUP BY day, dataset
  ORDER BY day DESC, dataset
"
```

**Si en 24h no hay snapshots nuevos**: revisar el log del scheduler. El comando falló, no fue invocado, o hubo permisos.

## Failure modes y comportamiento

| Fallo | Síntoma | Recovery |
|------|---------|----------|
| CelesTrak transitoriamente caído | Exit code != 0, error de transport | Siguiente invocación re-intenta. No hay reintento dentro de la invocación (todavía: ver más abajo). |
| Disk full | Exit code != 0, error escribiendo Parquet | Limpia espacio. Próxima invocación recupera. No hay corrupción (atomicidad). |
| Permisos sobre `data/` | Exit code != 0 al escribir | Corregir permisos del usuario que ejecuta el scheduler. |
| Dos invocaciones simultáneas escribiendo mismo content_hash | Cero — content_hash idéntico → mismo path → la segunda ve archivo y hace no-op | Ninguna acción. |
| TLE malformado en respuesta | `NormalizationError` después de persistir Raw | Raw queda registrado para auditoría; la siguiente cadencia probablemente normaliza correctamente cuando CelesTrak corrija. |

### Política de reintento dentro de una invocación

**Actualmente no hay reintento.** Si CelesTrak falla, el comando termina con error. La próxima invocación del cron (en 6 h o lo que sea) re-intenta naturalmente.

Para uso operacional, esto es aceptable si la cadencia es la suficientemente densa (6h cubre fallos transitorios de pocos minutos a 1 hora). Si la realidad operacional demostrara que esto es insuficiente (e.g., CelesTrak falla durante 12h+ ocasionalmente), un futuro ADR añadiría retry+backoff al `UrllibTransport`. **No se añade preventivamente** — esperamos evidencia operacional.

## Multi-dataset

Cada dataset es una invocación independiente. Pueden compartir paths sin coordinación:

**cron:**

```cron
0  */6 * * *  cd /opt/orbital-sentinel && .venv/bin/orbital-sentinel ingest stations
10 */6 * * *  cd /opt/orbital-sentinel && .venv/bin/orbital-sentinel ingest active
20 */6 * * *  cd /opt/orbital-sentinel && .venv/bin/orbital-sentinel ingest visual
```

(desfase de 10 min para no machacar CelesTrak con 3 requests simultáneos — buena vecindad).

**systemd:** un `*.timer` por dataset (el archivo de plantilla `@.timer` lo permite).

**Windows Task Scheduler:** una `ScheduledTask` por dataset.

## Lo que NO está en este runbook (pendiente de necesidad)

- **Autenticación a Space-Track u otras fuentes con credenciales.** ADR-0011 cubre el modelo; un runbook específico se escribirá si se añade alguna fuente autenticada.
- **Política de retención** de Raw/Normalized antiguos. El sistema no purga; tras suficiente tiempo el operador decide y un ADR/runbook formaliza.
- **Compactación de archivos Parquet pequeños** (si el catálogo de `conjunctions/` o `raw/` se vuelve fragmentado).
- **Stack de observabilidad** (Prometheus, Grafana, alertas). Out of scope para el proyecto; el operador integra con el suyo.
- **Recuperación ante corrupción de disco**. Backup es responsabilidad del operador. El sistema no replica.

Cada una se documentará cuando el uso operacional real lo justifique.

## Referencias

- [ADR-0022](../adr/0022-scheduling-model.md) — decisión del modelo de scheduling.
- [ADR-0019](../adr/0019-conjunction-detections-persistence.md) — idempotencia content-addressable.
- [ADR-0006](../adr/0006-data-immutability.md) — capas inmutables, sin UPDATE.
- [ADR-0004 enmienda 2](../adr/0004-duckdb-parquet-store.md) — verificación empírica de concurrencia segura.
- `man 5 crontab`, `man systemd.timer`, [Microsoft `Register-ScheduledTask`](https://learn.microsoft.com/en-us/powershell/module/scheduledtasks/register-scheduledtask).
