# ADR-0003: Layout `src/`, monorepo Python, gestor `uv`

**Estado:** Aceptado
**Fecha:** 2026-06-03
**Autor:** Orbital Sentinel
**Supersede a:** ninguno
**Relacionado con:** ADR-0000 (P4, P6), ADR-0001, ADR-0002

---

## Contexto

- Necesidad de empaquetar Python para desarrollo reproducible y distribución vía PyPI.
- Opciones de gestor: `pip`+`venv`, `poetry`, `uv`, `hatch`, `pdm`.
- Opciones de layout: `flat`, `src/`, multi-package.
- ADR-0001 exige lock file commiteado para reproducibilidad.

## Decisión

- **Layout `src/`** con paquete único `orbital_sentinel` bajo `src/`.
- **Monorepo Python** con un único `pyproject.toml`.
- **Extras opcionales** definidos en `[project.optional-dependencies]`: `viz`, `agent`, `dev`, `docs`.
- **`uv`** como gestor de proyecto y entorno.
- **`uv.lock` commiteado** al repositorio.

## Justificación

- `src/` previene la clase de bugs en que tests pasan accidentalmente importando desde el directorio del repo en lugar del paquete instalado.
- Monorepo permite refactor atómico entre planos (ADR-0002).
- Extras opcionales mantienen el install mínimo pequeño: Fase 1 no requiere `agent` ni todas las dependencias de `viz`.
- `uv` es rápido (10×–100× sobre pip), actively maintained por Astral, respeta totalmente `pyproject.toml`.
- `uv.lock` commiteado es prerrequisito de ADR-0001 (reproducible-first).

## Consecuencias

**Positivas**
- Instalaciones reproducibles bit a bit sobre un mismo sistema.
- Test isolation limpio.
- Velocidad de instalación reduce fricción de contribución.

**Negativas**
- Requiere editable install en desarrollo (`uv pip install -e .[dev]`). Coste cero en práctica.

**Neutras**
- Future split en paquetes múltiples es trivial con `uv` workspaces si llegara a ser necesario.

## Alternativas consideradas

### A. Flat layout
**Razón de rechazo:** import bugs intermitentes en tests, bien documentados.

### B. `poetry`
**Razón de rechazo:** más lento que `uv`, extensiones propietarias sobre `pyproject.toml`.

### C. `hatch`
**Razón de rechazo:** sólido pero menor tracción comunitaria.

### D. `pdm`
**Razón de rechazo:** similar a Poetry; sin ventaja sobre `uv`.

### E. `pip`+`venv` puro
**Razón de rechazo:** sin lock file estándar, reproducibilidad pobre.

### F. Multi-package monorepo desde día 1
**Razón de rechazo:** complejidad prematura sin caso de uso concreto.

## Alineación con ADR-0000

- **Refuerza P4** (lock file reproducible).
- **Refuerza P6** (estructura clara para documentación).
- **Sin tensiones.**

## Referencias

- PEP 517, PEP 518, PEP 621.
- Astral. *uv documentation.*
- Hynek Schlawack. *Testing & Packaging — Why `src/` Layout.*

---

## Historial de enmiendas

*Sin enmiendas a fecha de aceptación.*
