# Frozen Reproducibility Vectors

Implementación empírica de ADR-0013 (Reproducibility Under Declared
Environment).

## Propósito

Toda la arquitectura de Orbital Sentinel (ADR-0029 a ADR-0042) descansa
sobre una propiedad fundamental: **mismos inputs → mismos hashes content-
addressable, siempre, en cualquier instancia, en cualquier momento**.

Esta propiedad estaba **declarada** pero no **validada empíricamente**.
Esta suite cierra esa brecha: para inputs canónicos congelados, cada hash
producido por la implementación actual debe coincidir bit-a-bit con el
valor frozen en `vectors.json`.

Cualquier futuro cambio que altere silenciosamente la canonicalización
de cualquier capa (orden de keys en JSON, función de hash, formato de
serialización, orden de campos en `compute_*`) **rompe la propiedad
fundacional** y es detectado por CI inmediatamente.

## Contrato

- `contract_version`: SemVer del contrato cryptográfico. Bump mayor
  cuando los hashes cambian deliberadamente.
- `frozen_at`: fecha de congelación de la versión actual.
- `canonical_inputs`: declaración legible humana de los inputs que generan
  los hashes esperados.
- `expected_hashes`: SHA-256 hex content-addressable producido por cada
  capa para los inputs canónicos.
- `adrs_covered`: ADRs cuyo contrato cryptográfico está validado por
  este fixture.

## Componentes

| Archivo | Rol |
|---|---|
| `__init__.py` | Marker de paquete. |
| `canonical_inputs.py` | Constantes frozen + función `build_canonical_artifacts()` pura. |
| `vectors.json` | Fixture frozen: inputs declarados + hashes esperados. |
| `test_frozen_vectors.py` | Suite de pytest que compara producción vs. fixture. |
| `README.md` | Este documento. |

## Garantías

1. **Read-only sobre código de producción.** Borrar `tests/reproducibility/`
   deja el sistema funcionando idéntico.
2. **Cero dependencias nuevas.** Sólo módulos ya presentes.
3. **Determinismo absoluto.** `_clock` fijo, sin filesystem, sin red.
4. **Fail-fast.** Cualquier discrepancia genera un mensaje claro
   `DRIFT DETECTADO en <artifact_key>` con frozen vs. actual.
5. **Tiempo de ejecución.** La suite completa corre en < 1 segundo.

## Cómo extender cuando se añade una capa nueva

1. Añadir el constructor de la capa en `canonical_inputs.build_canonical_artifacts()`,
   produciendo el nuevo `content-addressable id`.
2. Ejecutar `python -c "from tests.reproducibility.canonical_inputs import
   build_canonical_artifacts; import json; print(json.dumps(build_canonical_artifacts(),
   indent=2, sort_keys=True))"` y capturar el nuevo hash.
3. Añadir el hash a `expected_hashes` en `vectors.json` tras revisión humana.
4. Añadir el `artifact_key` a las dos parametrizaciones (`test_frozen_hash_matches_expected`
   y `test_frozen_hash_is_well_formed_sha256`) en `test_frozen_vectors.py`.
5. Añadir el ADR correspondiente a `adrs_covered` en `vectors.json`.
6. NO bumpear `contract_version` — sólo extiendes el set frozen.

## Cómo proceder ante un cambio deliberado del contrato cryptográfico

Si una refactorización LEGÍTIMA cambia los hashes (ejemplo: cambia el
campo del modelo, cambia el orden canónico de inputs en una función
`compute_*`, etc.):

1. **Bump `contract_version`** en `vectors.json` (mayor: 1.0.0 → 2.0.0).
2. **Regenera `expected_hashes`** ejecutando el comando del paso 2 de
   "extender".
3. **Actualiza `frozen_at`** al día del cambio.
4. **Enmienda ADR-0013** documentando:
   - Versión anterior (1.0.0) y nueva (2.0.0).
   - Razón del cambio.
   - Implicaciones de compatibility: cualquier artefacto pre-cambio
     puede verificarse contra contract_version 1.0.0; nuevos contra 2.0.0.
5. **Revisión humana del diff** antes de merge.

## Lo que esta suite NO valida

- Comportamiento de los verifiers (existen tests dedicados).
- Detección de tampering (existen tests dedicados).
- Errores de schema Pydantic (existen tests dedicados).
- Rendimiento.

Esta suite SÓLO valida que para inputs frozen, los hashes producidos son
exactamente los hashes esperados. Es el contrato cryptográfico mínimo.
