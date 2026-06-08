# ADR-0007: Licencia Apache-2.0

**Estado:** Aceptado
**Fecha:** 2026-06-03
**Autor:** Orbital Sentinel
**Supersede a:** ninguno
**Relacionado con:** ADR-0000 (P5)

---

## Contexto

- El proyecto será público desde el día 1.
- La licencia define qué se puede hacer con el código, qué garantías se ofrecen, y cómo se protegen las contribuciones.
- ADR-0000 P5 establece licencia permisiva como propiedad irrenunciable.

## Decisión

**Apache License 2.0** para todo el código y documentación originales del proyecto.

- Archivo `LICENSE` en la raíz del repositorio.
- Headers de copyright en archivos fuente recomendados, no obligatorios para PRs (reduce fricción de contribución).
- `NOTICE` file añadido cuando se incorporen Works que lo requieran.

## Justificación

- Permite uso comercial, derivado y sublicensing sin condiciones más allá de mantener notice y disclaimers.
- **Cláusula explícita de patentes** (sección 3): grant + retaliation. MIT y BSD no la tienen.
- Compatible con prácticamente todas las licencias OSI mediante sublicensing en derived works.
- Estándar de facto en el ecosistema de astrodinámica OSS moderno (`sgp4`, `skyfield`, `astropy`).
- AGPL/GPL rechazadas: copyleft reduce adopción comercial benigna sin beneficio claro para los objetivos del proyecto.

## Consecuencias

**Positivas**
- Adopción máxima posible.
- Cláusula de patentes reduce riesgo legal para usuarios downstream.
- Compatible con afiliación futura a fundaciones (NumFOCUS, OpenSSF).

**Negativas**
- Permite que derivados se mantengan cerrados. Es deliberado.

**Neutras**
- Cesión a fundación en el futuro puede requerir CLA o DCO; decisión diferida a ADR específico cuando aplique.

## Alternativas consideradas

### A. MIT
**Razón de rechazo:** sin cláusula de patentes explícita.

### B. BSD-3-Clause
**Razón de rechazo:** similar a MIT; sin patentes.

### C. AGPL-3.0
**Razón de rechazo:** copyleft viral reduce adopción comercial sin beneficio para los objetivos.

### D. GPL-3.0
**Razón de rechazo:** copyleft de propagación amplio; reduce uso embedded en productos derivados.

### E. MPL-2.0
**Razón de rechazo:** copyleft file-level añade complejidad de cumplimiento sin alineación clara con objetivos.

## Alineación con ADR-0000

- **Implementa P5** literalmente.
- **Compatible con audiencia secundaria** (derivados comerciales sin filtros).
- **Compatible con disclaimer operacional** (Apache 2.0 incluye "AS IS").
- **Sin tensiones.**

## Referencias

- Apache Software Foundation. *Apache License, Version 2.0.*
- OSI. *License analysis matrix.*

---

## Historial de enmiendas

*Sin enmiendas a fecha de aceptación.*
