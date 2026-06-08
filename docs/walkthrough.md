# Walkthrough end-to-end — release v0

Carta de presentación operacional del proyecto post-Fase 2. Muestra el ciclo arquitectónico completo Raw → Normalized → Derived (on-demand + persistido) ejecutándose sin red, sin estado externo, sin configuración.

## Ejecutar

```powershell
.venv\Scripts\python.exe -m demo.v0_walkthrough
```

El script:

- **No toca la red**: usa `FakeTransport` sobre el fixture canónico de tests.
- **No persiste en el repo**: trabaja sobre un `tempfile.TemporaryDirectory` que se borra al salir.
- **No requiere configuración**: parámetros embebidos.

## Qué demuestra (6 pasos)

1. **Ingesta CelesTrak → Raw → Normalized** ([ADR-0011](adr/0011-secrets-management.md) sin credenciales + [ADR-0019](adr/0019-conjunction-detections-persistence.md) content-addressable).
2. **Propagación SGP4 → Ephemeris** in-memory ([ADR-0006](adr/0006-data-immutability.md) enmienda 1 + [ADR-0014](adr/0014-sgp4-integration.md)).
3. **Groundtrack 2D estático → PNG** ([ADR-0008](adr/0008-cesium-uncertainty.md) reserva Cesium para 3D futuro).
4. **Pairwise conjunction con Pc + 7 assumption fields** ([ADR-0020](adr/0020-probability-of-collision-v1.md)). Demuestra P2 en práctica.
5. **Screening N-to-N con `--persist`**, primera Derived persistida ([ADR-0019](adr/0019-conjunction-detections-persistence.md)).
6. **Listing de detecciones**, idempotencia content-addressable verificable.

## Output esperado (extracto real)

```
======================================================================
  Step 4 -- Pairwise conjunction -- ISS vs synthetic GEO 99999 con Pc
======================================================================
  miss_distance_km          : 35883.977
  relative_velocity_km_s    : 6.207
  tca                       : 2008-09-20T13:36:20.136719Z
  tca_was_refined           : True
  tca_resolution_minutes    : 0.016667

  --- Pc + assumption fields (ADR-0020) ---
  pc                        : 1.698e-21
  combined_hard_body_radius : 0.0100 km
  combined_sigma_at_tca_km  : 5581.433
  covariance_model_name     : tle_isotropic_spherical_v1
  covariance_baseline_sigma : 1.000
  covariance_growth_per_day : 1.000
  pc_method                 : foster_1992_fast_approximation
  engine_version            : 0.3.0
```

```
======================================================================
  Step 6 -- detections --norad 25544
======================================================================
  Primera deteccion persistida:
    detection_content_hash : 0c66a85babf6ceed4a9d2554...
    norad_a / norad_b      : 25544 / 99999
    miss_distance_km       : 35883.977
    pc                     : 1.698e-21

  Triple versionado por fila (ADR-0010 en produccion):
    persistence_schema_version : 0.2.0
    analysis_schema_version    : 0.3.0
    analysis_engine_version    : 0.3.0
```

## Qué mirar como lector

### En Step 4 (Pc honesto)

- **`combined_sigma_at_tca_km = 5581 km`** es **enorme**. Es coherente con el TLE sintético NORAD 99999 que tiene epoch en 2024 (analizamos en 2008): el sistema acumula 8 millones de minutos de crecimiento de incertidumbre y **lo muestra**.
- **`pc = 1.698e-21`** es matemáticamente correcto pero operacionalmente sin sentido. Un lector competente lo identifica inmediatamente al ver el σ enorme.
- **Las 7 assumption fields** (`combined_hard_body_radius`, `combined_sigma_at_tca_km`, `covariance_model_name`, `covariance_baseline_sigma`, `covariance_growth_per_day`, `pc_method`, más `engine_version`) hacen explícita toda la incertidumbre del cálculo.

**Esto es P2 funcionando en producción**: el sistema no esconde la incertidumbre; la materializa en campos del modelo.

### En Step 6 (triple versionado)

Una sola fila persistida lleva **tres SemVer independientes**:

- `persistence_schema_version = 0.2.0` — versión del esquema persistido.
- `analysis_schema_version = 0.3.0` — versión del esquema del análisis original.
- `analysis_engine_version = 0.3.0` — versión del motor pairwise que produjo el análisis.

Cuando alguna de estas tres versiones bumpe en el futuro, las filas viejas mantienen las suyas. Coexisten sin migración forzada. ADR-0010 ejercitado en producción, no solo declarado.

### En Step 5 (idempotencia)

Segundo run con `--persist` reporta `n_persisted = 0`. Sin tocar nada manual, sin chequeo del caller. Es content-addressable por construcción: mismo hash → archivo ya existe → no-op (ADR-0019).

## Qué NO está en el demo

Por scope explícito:

- **Multi-fuente**. Solo CelesTrak (vía FakeTransport).
- **Múltiples objetos reales**. Dos: ISS canónico (Vallado 2008) + GEO sintético del fixture.
- **Cesium 3D**. Solo groundtrack matplotlib (ADR-0008 reserva 3D para fases posteriores).
- **Maniobras / anomalías / agente LLM**. Fases 3-5.
- **Operaciones distribuidas**. ADR-0001/0012 local-first; el sistema corre íntegro en un solo proceso.

## Referencias

- Cierre de Fase 1: [ADR-0015](adr/0015-phase-1-closure.md).
- Cierre de Fase 2: [ADR-0021](adr/0021-phase-2-closure.md).
- Arquitectura de capas: [layers.md](architecture/layers.md).
- Invariantes verificados: [invariants.md](architecture/invariants.md).

## Limitaciones honestas

- El TLE sintético NORAD 99999 tiene epoch en 2024 y la ventana del demo en 2008 (epoch del TLE canónico ISS). Esto causa el σ enorme. **No es bug, es feature**: muestra que el sistema honestamente reporta incertidumbre catastrófica cuando aplica.
- El demo usa step de 10 min en el screening. Con step más fino TCA sería más preciso, miss más ajustada, Pc igualmente diminuto (la geometría LEO-vs-GEO domina).
- La covarianza isotropic spherical es la asunción más conservadora (ignorancia máxima). Sistemas con tracking real (USSF, LeoLabs) usan covarianzas anisotrópicas mucho más informativas. Orbital Sentinel no las tiene; ese es el contrato.
