# ADR-0031: Verifiable Evidence Bundle Layer v0.1

**Estado:** Aceptado
**Fecha:** 2026-06-06
**Autor:** Orbital Sentinel
**Supersede a:** ninguno
**Relacionado con:** ADR-0000 (P1, P2, P3, P4, P7, P8), ADR-0002 enmienda 1, ADR-0006, ADR-0010, ADR-0020, ADR-0027, ADR-0028, ADR-0029, ADR-0030

---

## Contexto

ADR-0029 emitió `DerivedEvidence` con `honesty_payload`. ADR-0030 proyectó el catálogo en `ExplanationContext` con `honesty_payload_hash` por referencia. Cuando un consumidor downstream recibe el contexto JSON, puede leer los hashes — pero **no puede verificarlos** porque el payload original vive en otra parte (in-process, en el `EvidenceCatalog` que ya no existe tras la invocación CLI).

Consecuencias arquitectónicas:

1. El context layer transmite afirmaciones de integridad no verificables.
2. No existe un artefacto autocontenido portátil que un tercero pueda recibir y validar offline.
3. Toda comunicación cross-organization requiere confianza externa al canal.

El sistema, hasta ahora, era internamente honesto pero **externamente inverificable**. ADR-0031 cierra ese gap como último paso pre-LLM.

## Decisión

Crear `analytics/bundles/` con cuatro modelos, dos helpers de firma, un builder, un verifier y dos subcomandos CLI.

### Hard invariant (recomendación arquitectónica aprobada)

**`bundle_id == bundle_signature` siempre.**

`bundle_id` es alias estricto de `bundle_signature`. No es un identificador independiente. El model_validator de `EvidenceBundle` rechaza cualquier construcción donde difieran. Razón: el bundle es content-addressable; dos identificadores para el mismo contenido crearían riesgo de divergencia silenciosa.

### Estructura de archivos

```
analytics/bundles/
    hashing.py     ← ÚNICA fuente de SHA-256 canonicalization
    models.py      ← modelos frozen, extra="forbid"
    builder.py     ← context + catalog → bundle (sin validación)
    verifier.py    ← bundle → report (nunca lanza, nunca muta)
```

### Modelos

- **`EvidenceBundle`** (root): `bundle_id`, `bundle_signature`, `bundle_payload_signature`, `object_id`, `context: ExplanationContext`, `evidence_payloads: list[BundledEvidence]`, versioning, `derived_at`.
- **`BundledEvidence`**: `evidence_id`, `derived_evidence: DerivedEvidence` (payload completo, no solo hash), `recomputed_payload_hash`, `payload_integrity_verified_at_build`.
- **`BundleVerificationReport`**: `bundle_id`, `is_valid`, contadores agregados, 5 checks individuales booleanos (incluido `bundle_id_is_alias_of_bundle_signature`), lista de `integrity_failures`, versioning, `verified_at`.
- **`BundleIntegrityFailure`**: contrato cerrado con 8 `failure_type` literales.

### Firmas anidadas

```
bundle_payload_signature = SHA-256(canonical_json(sorted(payloads)))
bundle_signature        = SHA-256(context_id | bundle_payload_signature | bundle_engine_version)
bundle_id               = bundle_signature   (alias hard)
```

Ordenamiento de payloads: `(derived_evidence.event_epoch asc, evidence_id asc)`.

### API pública

```python
build_evidence_bundle(context, catalog, *, clock=None) -> EvidenceBundle
verify_bundle(bundle, *, clock=None) -> BundleVerificationReport
compute_bundle_payload_signature(payloads) -> str
compute_bundle_signature(*, context_id, bundle_payload_signature, bundle_engine_version) -> str
compute_payload_hash(payload) -> str
canonical_json(obj) -> str
```

Garantías:
- `build_evidence_bundle` es pura, no valida.
- `verify_bundle` es pura, **nunca lanza** por integridad rota — siempre retorna reporte.
- Cero RNG.
- Cero wall clock en lógica semántica; `derived_at` y `verified_at` son metadata.

### Identificadores

| Constante | Valor v0.1 |
|----------|-----------|
| `BUNDLE_SCHEMA_VERSION` | `0.1.0` |
| `BUNDLE_ENGINE_VERSION` | `0.1.0` |
| `VERIFIER_ENGINE_VERSION` | `0.1.0` |

### CLI

```
orbital-sentinel bundle <norad_id>
    [--from ISO_UTC] [--to ISO_UTC]
    [--detector {maneuver|anomaly|conjunction}]
    [--baseline-days N] [--threshold-sigma S]
    [--min-baseline-samples N] [--engine-version X.Y.Z]
    [--raw-root PATH] [--normalized-root PATH] [--detections-root PATH]

orbital-sentinel verify-bundle <bundle_file|->
    [--strict]
```

`verify-bundle` con `--strict` retorna exit code 1 si `is_valid=False`. Sin `--strict`, retorna 0 con reporte (decisión del caller).

## Lo que este ADR NO incluye

- ❌ Firma criptográfica (HMAC, RSA, X.509, GPG) — solo SHA-256 content-addressable.
- ❌ Transporte (red, S3, email).
- ❌ Compresión.
- ❌ Encriptación.
- ❌ Esquemas alternativos (CBOR, Protobuf).
- ❌ Persistencia en `analytics/bundles/`.
- ❌ Repository pattern nuevo.
- ❌ Bundle anti-adversarial — integridad para good-faith consumers, no resistencia a un atacante con acceso al código.
- ❌ Modificación de `EvidenceCatalog`, `ExplanationContext`, `DerivedEvidence`, detectores, repositorios.
- ❌ ML, IA, clasificación, scoring, ranking, threat/risk levels, recomendaciones, alertas.
- ❌ Servicios externos, bases de datos nuevas.
- ❌ Dependencias runtime nuevas.

## Justificación

### Por qué ADR-0031 antes de Fase 5 (Agente Explicativo)

1. **El agente debe consumir input verificable**, no claims de integridad sin pre-imagen.
2. **El agente necesita un input canónico citable**: `bundle_id` da el referente concreto que el output del agente puede declarar.
3. **La cadena de auditoría debe cerrarse antes del componente más opaco** (el LLM).
4. **ADR-0031 es la operacionalización final de ADR-0020**: el honesty pattern se vuelve verificable end-to-end.

### Por qué bundle_id como alias estricto

Una segunda identidad para el mismo contenido es riesgo de divergencia silenciosa. El bundle es content-addressable: existe **una** identidad. Múltiples nombres para la misma cosa generan confusión sin valor.

## Alineación con ADR-0000

- **Refuerza P1, P4**: bundle es **el mecanismo** por el cual la evidencia llega a terceros sin pérdida ni alteración silenciosa.
- **Refuerza P2**: honesty fields heredados; verifier no clasifica.
- **Refuerza P3**: stdlib only.
- **Refuerza P7, P8**: sin red, sin servicios.
- **Sin tensiones.**

## Referencias

- ADR-0010 (versioning).
- ADR-0020 (honesty pattern).
- ADR-0029 (Evidence Layer).
- ADR-0030 (Explanation Context Layer).

---

## Historial de enmiendas

*Sin enmiendas a fecha de aceptación.*
