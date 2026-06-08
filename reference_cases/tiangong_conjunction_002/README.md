# Reference Case 002 — Tiangong Conjunction Risk Assessment

**Segundo caso real de Orbital Sentinel.** Demuestra que el sistema opera independientemente de la geografía política o el operador del objeto orbital. Misma snapshot Celestrak que el caso 001 — confirma reproducibilidad cross-objeto.

## Resumen

- **Pregunta**: ¿Qué aproximaciones cercanas se predicen para la Estación Espacial China (módulo TIANHE) en los próximos 7 días?
- **Objeto primario**: NORAD 48274 (CSS TIANHE — Tianhe core module)
- **Fuente**: Idéntica al caso 001 (Celestrak `stations`, snapshot del 2026-06-08T14:07:52Z)
- **Ventana de análisis**: 2026-06-08T14:00Z a 2026-06-15T14:00Z
- **Threshold**: 50 km
- **Step grid**: 5 min

## Resultado del análisis

6 eventos de conjunción detectados:

| Evidence ID prefix | NORAD | Objeto | Miss (km) | Nota |
|---|---|---|---|---|
| ... | 54216 | CSS (MENGTIAN) | 0.00 | Módulo Tiangong docked |
| ... | 53239 | CSS (WENTIAN) | 0.00 | Módulo Tiangong docked |
| ... | 69180 | SHENZHOU-23 | 0.00 | Vehículo crew docked |
| ... | 69049 | TIANZHOU-10 | 0.00 | Vehículo cargo docked |
| ... | **67684** | **CORAL** | **49.24** | **Aproximación real no asociada** |
| ... | **67688** | **HMU-SAT2** | **25.70** | **Aproximación real no asociada** |

4 de 6 son módulos/vehículos co-orbitales esperados. **2 aproximaciones reales** con satélites no relacionados (CORAL y HMU-SAT2, ambos cubesats).

**Nota cross-case interesante**: HMU-SAT2 aparece como aproximación a la ISS (46.91 km) en el caso 001 y a Tiangong (25.70 km) en el caso 002 dentro de la misma ventana de 7 días. Patrón real verificable independientemente.

Todos los eventos llevan `is_apparent_not_confirmed=True` y `Pc=0.0`.

## Artefactos generados

| Archivo | ID content-addressable |
|---|---|
| `bundle.json` | bundle_id `b021fbe1986367b3…` |
| `artifact.json` | explanation_id (mecánico) |
| `claim_registry.json` | registry_id `7dc8f5e02a91d158…` (6 claims) |
| `hypothesis_registry.json` | registry_id `1f1beac5e8e2d92f…` (1 hipótesis) |
| `chain.json` | chain_id `1fd63babe321bb12…` |
| `case.json` | **case_id `32d71fe60400b6a8c0fcbf1e62a19449e06a3d034ef6e0476c29fc746e05a38b`** |
| `external_source_registry.json` | registry_id `ef0b9918a8b26462…` |

## Garantías cryptográficas cross-case

Este caso comparte el mismo `source_payload_hash` (Celestrak snapshot del 2026-06-08T14:07:52Z) que el caso 001:

```
both cases reference: source_payload_hash = 8ebce06318d885caf194e9819fd457aace3fb0f49c5c35ad62f0218ed745c4f9
```

Pero producen `bundle_id`, `case_id`, y todos los demás hashes **distintos** porque el objeto primario es diferente. Esta es la garantía de ADR-0029: la identidad content-addressable distingue objetos aunque compartan upstream.

## Cómo reverificar (cualquier tercero)

```bash
pip install orbital-sentinel
orbital-sentinel self-verify --strict
orbital-sentinel verify-investigation-case case.json --strict
orbital-sentinel verify-external-source-registry external_source_registry.json --bundle-file bundle.json --strict
orbital-sentinel verify-bundle bundle.json --strict
```

Todas deben retornar `is_valid=true` con 0 findings.

## Lo que este caso demuestra

1. **El sistema es objeto-agnóstico**. Funciona idénticamente para la ISS (operador NASA/Roscosmos/JAXA/ESA/CSA) y para Tiangong (operador CMSA/CASC). Cero acoplamiento político.
2. **Misma snapshot Celestrak, distintos casos**. Un único acto de ingestión sirve a múltiples investigaciones independientes.
3. **Patrón cross-case real**. HMU-SAT2 (cubesat) tiene aproximaciones a ambas estaciones espaciales en la misma ventana. Esto sería invisible sin un sistema de evidencia content-addressable que permita correlación.
4. **Reproducibilidad real**. Los `source_payload_hash` coinciden entre casos. Cualquier tercero con acceso a la URL de Celestrak puede recomputar el hash de payload original.

## Fuente de datos

- **URL**: `https://celestrak.org/NORAD/elements/gp.php?GROUP=stations&FORMAT=tle`
- **Fetched at**: 2026-06-08T14:07:52.097802Z (idéntico a caso 001)
- **Payload SHA-256**: `8ebce06318d885caf194e9819fd457aace3fb0f49c5c35ad62f0218ed745c4f9`

---

Segundo caso real. La promesa de visión opera ahora sobre múltiples objetos orbitales de distintos operadores, demostrando neutralidad técnica.
