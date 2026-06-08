# ADR-0011: Secrets Management

**Estado:** Aceptado
**Fecha:** 2026-06-03
**Autor:** Orbital Sentinel
**Supersede a:** ninguno
**Relacionado con:** ADR-0000 (P3, P7, P8), ADR-0012

---

## Contexto

- Space-Track requiere usuario/contraseña para acceso completo.
- CelesTrak ratelimita y requiere `User-Agent` identificable.
- Anthropic Claude (ADR-0009 opt-in) requiere `ANTHROPIC_API_KEY`.
- Cesium Ion (ADR-0008 opt-in) requiere token.
- Cualquier fuente o servicio futuro tendrá su propio régimen.
- El red-team review (F9) identificó la ausencia de política como agujero.
- Local-first (ADR-0012) y baseline coste cero (P3) implican que ninguna credencial es obligatoria; el sistema debe operar sin ellas en modo degradado.

## Decisión

### Principios

1. **Ninguna credencial es obligatoria** para Fase 1 baseline. Las fuentes sin auth (CelesTrak con `User-Agent` y rate-limit respetado) son suficientes para arrancar.
2. **Las credenciales son ampliaciones**, no dependencias. Si una credencial está ausente, la capacidad asociada se degrada con un warning legible, no con un error.
3. **El proyecto nunca commitea credenciales.** Sin excepciones.

### Ubicaciones permitidas

Las credenciales viven, en orden de preferencia:

1. **Variables de entorno** con prefijo `ORBITAL_SENTINEL_*` (por ejemplo `ORBITAL_SENTINEL_SPACETRACK_USER`).
2. **Archivo local `.env`** en la raíz del proyecto del usuario, ignorado por `.gitignore`.
3. **OS keyring** vía `keyring` Python library, opt-in y documentado, para usuarios que prefieren no tener secrets en disco plano.

El cargador de configuración (`core/config.py`) lee en este orden con override hacia abajo: env > .env > keyring > sin credencial.

### Inyección en CI

- CI público (GitHub Actions sobre repositorio público) **no tiene acceso a credenciales** de servicios autenticados. Es deliberado: garantiza que cualquier observador puede reproducir el pipeline público sin secrets.
- Tests que requieran fuentes autenticadas se marcan `@pytest.mark.requires_secret(SERVICE)` y se saltan en CI público con un mensaje claro.
- Para validación interna, el mantenedor puede ejecutar la suite completa localmente con sus credenciales en `.env`.

### Política para contribuidores externos

- Una PR no debe necesitar credenciales para pasar CI. Si una capacidad nueva requiere fuente autenticada, los tests deben tener fixtures cacheados como artefactos en `tests/fixtures/` (con permiso de la fuente cuando aplique).
- La documentación de cada fuente autenticada explica cómo obtener la credencial, en qué jurisdicción aplican términos de uso, y qué capacidades se degradan sin ella.

### Rotación, expiración y fugas

- El sistema no rota credenciales automáticamente. La rotación es responsabilidad del usuario.
- En caso de fuga detectada (commit accidental, log filtrado), la PR de mitigación debe:
  1. Revocar la credencial en la fuente.
  2. Reescribir historia git solo si la credencial ya estaba publicada (`git filter-repo` o BFG).
  3. Documentar el incidente en `docs/incidents/`.
- Pre-commit hook que escanea por patrones de secrets conocidos (`detect-secrets` o `gitleaks`) se activa por defecto.

### Inventario de credenciales

Cada fuente o servicio que requiera credencial mantiene una entrada en `docs/credentials/registry.md` con:

- Servicio.
- Variable de entorno.
- Capacidad que habilita.
- Modo de degradación sin ella.
- Link a la página de gestión de la credencial en el proveedor.

### Disclaimer sobre TOS

Acceso a fuentes autenticadas implica aceptar sus términos. El proyecto documenta esto pero no monitoriza cumplimiento del usuario; es responsabilidad de quien configura la credencial.

## Justificación

- Coherente con local-first (ADR-0012): no se asume nada por defecto.
- Coherente con P3: baseline funciona sin coste.
- Coherente con P7: fuentes públicas como primarias; autenticadas como complemento.
- Pre-commit + CI sin secrets en repo público minimiza superficie de fuga.

## Consecuencias

**Positivas**
- Setup baseline es "git clone + uv sync"; sin necesidad de pedir credenciales para empezar.
- Contributores externos pueden trabajar sin barreras.
- CI público es honestamente reproducible.

**Negativas**
- Algunas capacidades quedan inaccesibles a contributores sin credenciales (aceptable; es el régimen de Space-Track).
- Tests que requieren creds se saltan en CI público, reduciendo cobertura efectiva (mitigable con fixtures cacheados).

**Neutras**
- El registry de credenciales es documentación viva; requiere actualización.

## Alternativas consideradas

### A. Solo variables de entorno, sin `.env`
**Razón de rechazo:** fricción para desarrollo local; `.env` es práctica estándar.

### B. Secret manager remoto (Vault, AWS Secrets Manager, etc.)
**Razón de rechazo:** viola local-first; introduce dependencia obligatoria.

### C. Credenciales en config files versionados (encriptados con SOPS, sealed-secrets)
**Razón de rechazo:** complejidad operativa fuera del scope de un proyecto sin equipo dedicado.

### D. Ningún manejo formal de secrets
**Razón de rechazo:** lo que el red-team review F9 ya rechazó.

## Alineación con ADR-0000

- **Refuerza P3** (baseline gratuito).
- **Refuerza P7** (fuentes públicas como primarias).
- **Refuerza P8** (sin dependencia remota obligatoria).
- **Sin tensiones.**

## Referencias

- `detect-secrets`, `gitleaks` documentation.
- `python-keyring` documentation.
- 12-factor app methodology, factor III (Config).

---

## Historial de enmiendas

*Sin enmiendas a fecha de aceptación.*
