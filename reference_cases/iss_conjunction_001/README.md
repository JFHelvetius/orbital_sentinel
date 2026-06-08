# Reference Case 001 — ISS Conjunction Risk Assessment

**Primer caso real de Orbital Sentinel.** Demuestra el sistema operando end-to-end sobre datos reales de Celestrak. Cualquier tercero puede reproducir y verificar bit-a-bit los artefactos publicados aquí.

## Resumen

- **Pregunta**: ¿Qué aproximaciones cercanas se predicen para la Estación Espacial Internacional en los próximos 7 días?
- **Objeto primario**: NORAD 25544 (ISS — ZARYA)
- **Fuente**: Celestrak GROUP `stations` (25 objetos, TLE público)
- **Ingestado el**: 2026-06-08T14:07:52Z
- **Ventana de análisis**: 2026-06-08T14:00Z a 2026-06-15T14:00Z (7 días)
- **Threshold**: 50 km
- **Step grid**: 5 min (2017 muestras por par)

## Resultado del análisis

9 eventos de conjunción detectados:

| Evidence ID | NORAD | Objeto | TCA | Miss (km) | Nota |
|---|---|---|---|---|---|
| `193fbef…` | 36086 | POISK | 2026-06-08T14:00Z | 0.00 | Módulo ISS docked |
| `354b662…` | 49044 | ISS (NAUKA) | 2026-06-08T14:00Z | 0.00 | Módulo ISS docked |
| `4b95d9f…` | 68319 | PROGRESS-MS 33 | 2026-06-08T14:00Z | 0.00 | Vehículo visitante docked |
| `5b5eaac…` | 68689 | CYGNUS NG-24 | 2026-06-08T14:00Z | 0.57 | Co-orbital |
| `76b8db6…` | 67796 | CREW DRAGON 12 | 2026-06-08T14:00Z | 0.57 | Vehículo visitante docked |
| `82df843…` | 66664 | SOYUZ-MS 28 | 2026-06-08T14:00Z | 0.00 | Vehículo visitante docked |
| `ba4dc89…` | 68837 | PROGRESS-MS 34 | 2026-06-08T14:00Z | 0.57 | Vehículo visitante docked |
| `f28a7d1…` | 69103 | DRAGON CRS-34 | 2026-06-08T14:00Z | 0.00 | Vehículo visitante docked |
| **`ea141da…`** | **67688** | **HMU-SAT2** | **2026-06-14T08:46:28Z** | **46.91** | **Aproximación real no asociada** |

8 de 9 eventos corresponden a módulos/vehículos físicamente acoplados o en proximidad de operaciones rutinarias del ISS — comportamiento esperado del catálogo `stations`. **El evento ea141da… representa una aproximación real entre ISS y HMU-SAT2 a 46.9 km el 14 de junio.**

Todos los eventos llevan `is_apparent_not_confirmed=True` y `Pc=0.0` (probabilidad de colisión no calculada porque no se proveyó `combined_hard_body_radius_km`). El sistema NO afirma riesgo de colisión — sólo geometría observacional.

## Artefactos generados (verificables offline)

| Archivo | ID content-addressable |
|---|---|
| `bundle.json` | bundle_id `1093d437…` |
| `agent_input.json` | agent_input_id `from bundle` |
| `artifact.json` | explanation_id `518614169a93…` |
| `claim_registry.json` | registry_id `7fbb3a288ece…` (9 claims) |
| `hypothesis_registry.json` | registry_id `c7ed9a920c0e…` (1 hipótesis) |
| `chain.json` | chain_id `ec3b417371…` |
| `case.json` | **case_id `c22942d172adb9543eca63caacde3a7861979ec473ad5df7c1b7be6f8a2b58a2`** |
| `external_source_registry.json` | registry_id `2ce5fe8865b7…` |

Cada uno verificable con `orbital-sentinel verify-*`.

## Cómo reverificar (cualquier tercero)

```bash
# 1. Instala la versión canónica de Orbital Sentinel
pip install orbital-sentinel

# 2. Verifica que tu instalación produce los hashes canónicos
orbital-sentinel self-verify --strict

# 3. Descarga este reference case
git clone <repo> && cd reference_cases/iss_conjunction_001

# 4. Verifica el caso de investigación
orbital-sentinel verify-investigation-case case.json --strict
# Esperado: is_valid=true, n_findings=0

# 5. Verifica la procedencia externa
orbital-sentinel verify-external-source-registry external_source_registry.json \
    --bundle-file bundle.json --strict
# Esperado: is_valid=true, n_findings=0

# 6. Verifica el bundle individualmente
orbital-sentinel verify-bundle bundle.json --strict
# Esperado: is_valid=true, integrity_failures=[]
```

## Garantías cryptográficas

- **`case_id` content-addressable**: deriva de los inputs canónicos del caso. Inalterable sin que cambie el hash.
- **`bundle_id == bundle_signature`**: invariante hard de ADR-0031.
- **`source_bundle_id` (en provenance) == bundle.bundle_id**: binding cryptográfico entre caso y provenance.
- **`source_payload_hash`** del registry: SHA-256 de los bytes literales devueltos por Celestrak. Cualquiera con acceso a la URL original puede recomputarlo.

## Fuente de los datos

- **URL**: `https://celestrak.org/NORAD/elements/gp.php?GROUP=stations&FORMAT=tle`
- **Fetched at**: 2026-06-08T14:07:52.097802Z
- **Payload SHA-256**: `8ebce06318d885caf194e9819fd457aace3fb0f49c5c35ad62f0218ed745c4f9`
- **Provider**: celestrak
- **Content type**: tle_text

## Reportes de verificación incluidos

- `bundle_verification.json` — output literal de `verify-bundle`
- `case_verification.json` — output literal de `verify-investigation-case`
- `source_verification.json` — output literal de `verify-external-source-registry`
- `installation_verification.json` — output literal de `self-verify` en la instalación productora

## Lo que este caso NO hace

- **No afirma probabilidad de colisión**. Pc=0 por construcción (sin radio físico declarado).
- **No clasifica riesgo**. Sólo enumera geometría observacional.
- **No interpreta**. El `explanation_text` es template-driven mecánico ("detector X identified conjunction with NORAD=Y at TCA=Z").

## Honesto sobre las limitaciones

- Los TLEs son snapshots con incertidumbre orbital declarada (`sgp4_uncertainty_baseline_km=3.0`).
- La predicción a 7 días tiene `combined_sigma_at_tca_km ≈ 2.4-10 km`. Los miss distances reportados son inferiores a esa incertidumbre en muchos casos, lo cual el sistema preserva en `is_apparent_not_confirmed=True`.
- Una sola ingestion → no se pueden detectar maniobras (eso requiere serie temporal). Este caso usa exclusivamente la geometría instantánea.
- El catálogo `stations` excluye debris. Riesgos reales por debris no están representados.

---

Este es el primer caso real del proyecto. La promesa fundacional de ADR-0000 — *"reconstruir la cadena completa que conecta una afirmación con la evidencia original"* — opera empíricamente sobre datos reales por primera vez.
