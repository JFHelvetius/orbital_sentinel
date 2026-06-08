# ADR-0013: Reproducibility Under Declared Environment

**Estado:** Aceptado
**Fecha:** 2026-06-03
**Autor:** Orbital Sentinel
**Supersede a:** parcialmente ADR-0001 (junto con ADR-0012)
**Relacionado con:** ADR-0000 (P1, P4), ADR-0006, ADR-0010, ADR-0012

---

## Contexto

- ADR-0001 acoplaba reproducibilidad con local-first y prometía bit-exactness universal. El red-team review (F1, F2) demostró que (a) la bit-exactness universal no es alcanzable en el stack, y (b) los dos principios son ortogonales.
- ADR-0000 P1 fue reformulada como "Reproducibilidad bajo entorno declarado" (enmienda 1, 2026-06-03).
- Este ADR captura **solo el principio de reproducibilidad** y cómo se opera. El principio de local-first se trata en ADR-0012.

## Decisión

Cualquier inferencia debe poder reproducirse partiendo de cuatro coordenadas declaradas:

1. **Código** identificado por commit del repositorio.
2. **Configuración** identificada por hash del archivo de config usado en el run.
3. **Datos crudos** identificados por `content_hash` de los artefactos de entrada.
4. **Entorno** declarado: lockfile (`uv.lock`), sistema operativo + arquitectura, versiones de librerías nativas relevantes (BLAS, DuckDB, sgp4 wheel).

### Régimen de garantías

- **Bit-exacta** entre dos ejecuciones en el mismo entorno declarado, con el mismo código, config y datos.
- **Funcionalmente equivalente** entre entornos compatibles (misma versión MAJOR de los componentes versionados por ADR-0010; diferencias numéricas dentro de tolerancia documentada).
- **No garantizada bit-exacta** entre arquitecturas, compiladores o vendors distintos. Esa garantía no es alcanzable en este stack y declararla sería deshonesto.

### Mecanismos de soporte

1. **`uv.lock` commiteado** (ADR-0003). Misma versión exacta de Python deps en cualquier reinstalación.
2. **Imagen OCI de referencia** publicada por release. Define `entorno_canonico_<version>` para reproducción cross-host.
3. **Tests de regresión** que reejecutan inferencias canónicas y comparan contra outputs almacenados. Si fallan en el entorno canónico sin causa declarada, el release no sale.
4. **Versionado de algoritmos y datos** (ADR-0010) que permite mapear cada output a sus coordenadas.
5. **Inmutabilidad de Raw + sin UPDATE** (ADR-0006) que garantiza inputs estables.

### Resolución de tensiones con local-first (ADR-0012)

Cuando reproducibilidad y local-first entran en tensión, **manda reproducibilidad**.

- Cache local cuya invalidación no es detectable de forma fiable se considera anti-patrón. Toda caché incorpora el hash de los inputs que la determinan.
- Updates in-place de artefactos remotos (Ollama models, tiles, embeddings) que el sistema cachea: el sistema debe detectar el cambio (re-hash al cargar) o forzar rebuild explícito.
- Si una capacidad solo es posible sacrificando reproducibilidad, se marca como `experimental` y se excluye del régimen P1/P4.

### Límites declarados explícitamente

Este ADR no promete:

- Reproducibilidad bit-exacta de outputs LLM aún con seeds y temperaturas iguales en GPU (CUDA reduction order). Esa propiedad no es alcanzable.
- Reproducibilidad de visualizaciones a nivel de pixel (depende de driver de GPU, sistema de ventanas, fuentes).
- Reproducibilidad de timings (tiempo de wall-clock varía).

Lo que sí promete: que las **propiedades materiales** del output (valores numéricos en regímenes deterministas, decisiones de detección, contenido de tablas) son recuperables exactamente en el entorno canónico, y comparables entre entornos compatibles dentro de tolerancia documentada.

## Justificación

- Refleja honestamente lo que el stack puede entregar.
- Conserva la propiedad operacional importante: dos investigadores con el mismo entorno canónico obtienen los mismos números.
- Permite que el proyecto sea citable: un paper puede referenciar `(commit, config_hash, dataset_hash, env=canonical_v1.2.0)` y ser reproducido.

## Consecuencias

**Positivas**
- Honestidad sobre lo que el sistema puede prometer.
- Releases tienen criterio claro de "sale o no sale".
- Posible auditar regresiones de reproducibilidad.

**Negativas**
- Mantener imagen OCI de referencia añade overhead operacional.
- "Entornos compatibles" requiere definición — gestionado vía ADR-0010 MAJOR rules.

**Neutras**
- Reproducibilidad cross-platform queda como propiedad emergente, no garantizada.

## Alternativas consideradas

### A. Reproducibilidad universal bit a bit
**Razón de rechazo:** F1 demostró que no es alcanzable en este stack.

### B. Best-effort reproducibility
**Razón de rechazo:** no es citable; no es ciencia.

### C. Reproducibilidad solo dentro del mismo proceso
**Razón de rechazo:** trivialmente cierta y no útil para colaboración.

## Alineación con ADR-0000

- **Implementa P1** (reformulada en enmienda 1).
- **Implementa P4** (validación operacional).
- **Refuerza P6** (régimen de garantías documentado).
- **Sin tensiones** dentro de las garantías declaradas.

## Referencias

- ACM. *Artifact Review and Badging — Current Version (v1.1).*
- Software Heritage. *Principles on archive and reproducibility.*

---

## Historial de enmiendas

### Enmienda 1 (2026-06-07): Validación empírica del contrato cryptográfico

Hasta esta fecha, la propiedad de reproducibilidad bit-a-bit declarada por
este ADR era validada únicamente por tests de comportamiento que afirmaban
"dos invocaciones del builder producen el mismo hash" (clock-isolation,
determinismo local). **Ningún test verificaba que para inputs canónicos
congelados los hashes producidos coincidieran con valores externamente
declarados.**

Esta enmienda incorpora un mecanismo de validación empírica permanente:

**`tests/reproducibility/`** — Frozen Reproducibility Vectors v1.0.0.

- Inputs canónicos frozen (`fixed_clock`, NORAD canónico, evento sintético,
  payloads literales) declarados en `canonical_inputs.py`.
- Hashes esperados frozen en `vectors.json` para cada capa content-
  addressable de ADR-0029 a ADR-0042 (16 hashes en v1.0.0).
- Suite pytest que compara producción vs. fixture y falla con
  `DRIFT DETECTADO en <artifact_key>` ante cualquier discrepancia.

### Contrato cryptográfico v1.0.0

| Hash | Valor frozen |
|------|--------------|
| `evidence_id` (ADR-0029) | `ed043b4e…` |
| `bundle_id` (ADR-0031) | `e66d8d94…` |
| `agent_input_id` (ADR-0032) | `2b113734…` |
| `explanation_id` (ADR-0033) | `ed8711b0…` |
| `claim_id_0` (ADR-0035) | `dce08e45…` |
| `claim_registry_id` (ADR-0035) | `f9e206d3…` |
| `hypothesis_id_0` (ADR-0036) | `0a1b98b0…` |
| `hypothesis_registry_id` (ADR-0036) | `990a0c1a…` |
| `chain_id` (ADR-0037) | `be5fb091…` |
| `case_id` (ADR-0038) | `c16e2caf…` |
| `revocation_id` (ADR-0039) | `439bd740…` |
| `revocation_ledger_id` (ADR-0039) | `2c71a803…` |
| `source_record_id` (ADR-0040) | `7347fcfe…` |
| `external_source_registry_id` (ADR-0040) | `d19a8299…` |
| `dissent_id` (ADR-0041) | `b6bb6cd1…` |
| `dissent_ledger_id` (ADR-0041) | `1e57e348…` |

Valores completos en `tests/reproducibility/vectors.json`.

### Régimen operativo

- **Extensión** (añadir nueva capa content-addressable): no bumpea
  `contract_version`. Procedimiento documentado en
  `tests/reproducibility/README.md`.
- **Modificación deliberada del contrato** (cambio en canonicalización
  existente): bumpea `contract_version` mayor, regenera `vectors.json`,
  documenta el motivo en nueva enmienda a este ADR, requiere revisión
  humana del diff antes de merge.
- **Regresión accidental**: la suite falla en CI; debe revertirse antes
  de merge.

### Garantía añadida

Antes de la enmienda: reproducibilidad bit-a-bit era una **propiedad
declarada**.

Después de la enmienda: reproducibilidad bit-a-bit es una **propiedad
empíricamente verificada en cada CI run**, congelada contra una baseline
externa, y resistente a regresiones silenciosas.

Esto cierra el ciclo entre el principio fundacional ADR-0000 P1 y su
verificación operativa.

### Enmienda 2 (2026-06-08): Promoción del contrato al deliverable instalable

La enmienda 1 implementó la validación empírica del contrato cryptográfico
en `tests/reproducibility/`. Esto resolvía la propiedad bajo desarrollo,
pero **el contrato no se incluía en el wheel/sdist**: un consumidor que
ejecutaba `pip install orbital-sentinel` no recibía `vectors.json` y por
tanto **no podía verificar que su instalación produce los hashes
canónicos**.

Esto rompía la promesa fundacional para todos los roles no-dev (revisor
independiente, disidente). Para verificar, debían clonar el repositorio.
Inaceptable para "Wikipedia verificable del espacio cercano".

Esta enmienda promueve el contrato al package instalable:

* `tests/reproducibility/canonical_inputs.py` → `src/orbital_sentinel/reproducibility/canonical_inputs.py`
* `tests/reproducibility/vectors.json` → `src/orbital_sentinel/reproducibility/vectors.json`
* Añade `src/orbital_sentinel/reproducibility/models.py` con
  `InstallationVerificationReport` (frozen, extra="forbid").
* Añade `src/orbital_sentinel/reproducibility/verifier.py` con
  `verify_installation()` (función pura, nunca lanza, retorna report).
* Añade subcomando CLI `orbital-sentinel self-verify [--strict]`.

`tests/reproducibility/test_frozen_vectors.py` importa ahora desde el
package de producción; la suite de tests sigue siendo válida y pasa los
mismos 39 tests sin duplicar lógica.

### Procedimiento end-user post-instalación

```
$ pip install orbital-sentinel
$ orbital-sentinel self-verify --strict
{"contract_version": "1.0.0", "is_valid": true, "n_hashes_verified": 16, ...}
```

Salida JSON parseable, exit 0 si canónico, exit 1 con `--strict` si
detecta drift. Sin argumentos posicionales, sin contexto previo del
usuario, sin acceso al árbol fuente.

### Mecanismos de ADR-0013 implementados tras la enmienda 2

| Mecanismo declarado | Estado |
|---|---|
| 1. `uv.lock` commiteado | ✓ |
| 2. Imagen OCI de referencia | ⚠ pendiente (operacional, no scope de código) |
| 3. Tests de regresión canónicos | ✓ (enmiendas 1 + 2 permiten ejecución tanto en dev como en runtime instalado) |
| 4. Versionado de algoritmos y datos | ✓ |
| 5. Inmutabilidad de Raw | ✓ |

4/5 mecanismos cerrados en código. El restante (imagen OCI) es trabajo de
release engineering, fuera del scope arquitectónico.

### Garantía añadida

Antes de la enmienda 2: validación empírica accessible **sólo a developers**.

Después de la enmienda 2: validación empírica accessible **a cualquier
consumidor del wheel** mediante un comando CLI sin contexto. El contrato
cryptográfico es ahora parte permanente del deliverable.
