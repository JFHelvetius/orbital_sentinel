"""Orbital Sentinel — interfaz web.

Tres secciones:
  1. Casos de referencia  — explora los InvestigationCase incluidos en el repo.
  2. Verificar            — sube cualquier case.json y comprueba la cadena.
  3. Sobre el proyecto    — descripción, filosofía, enlaces.

Requisitos: pip install orbital-sentinel[app]
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from orbital_sentinel.analytics.investigations.models import InvestigationCase
from orbital_sentinel.analytics.investigations.verifier import verify_investigation_case

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_ROOT = Path(__file__).parent.parent
_CASES_DIR = _ROOT / "reference_cases"

# ---------------------------------------------------------------------------
# Datos estáticos
# ---------------------------------------------------------------------------

_NORAD_NAMES: dict[int, str] = {
    25544: "ISS",
    48274: "CSS Tianhe",
    67688: "HMU-SAT2",
    36086: "Progress MS-27",
    49044: "Crew Dragon (Endurance)",
    66664: "Cygnus NG-20",
    68319: "Soyuz MS-27",
    68689: "Crew Dragon (Freedom)",
    67796: "Progress MS-28",
    68837: "Tianzhou-8",
    69103: "Shenzhou-20",
}

_CASE_DISPLAY_NAMES: dict[str, str] = {
    "iss_conjunction_001": "ISS (25544) — Conjunciones 7 días · Jun 2026",
    "tiangong_conjunction_002": "CSS Tianhe (48274) — Conjunciones 7 días · Jun 2026",
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _norad_label(norad: int) -> str:
    name = _NORAD_NAMES.get(norad)
    return f"{name} ({norad})" if name else str(norad)


def _short_hash(h: str, n: int = 14) -> str:
    return h[:n] + "…"


def _list_reference_cases() -> list[str]:
    if not _CASES_DIR.exists():
        return []
    return sorted(
        d.name
        for d in _CASES_DIR.iterdir()
        if d.is_dir()
        and (d / "case.json").exists()
        and d.name != "external_audit_demo"
    )


@st.cache_data(show_spinner=False)
def _load_case(name: str) -> InvestigationCase:
    path = _CASES_DIR / name / "case.json"
    return InvestigationCase.model_validate_json(path.read_text(encoding="utf-8"))


def _evidence_rows(case: InvestigationCase) -> list[dict[str, Any]]:
    rows = []
    for be in case.evidence_bundle.evidence_payloads:
        ev = be.derived_evidence
        hp = ev.honesty_payload
        if ev.source_detector == "conjunction_detection_v01":
            secondary = int(hp.get("other_norad_cat_id", 0))
            miss = float(hp.get("miss_distance_km", 0.0))
            rows.append(
                {
                    "Objeto secundario": _norad_label(secondary),
                    "TCA (UTC)": ev.event_epoch.strftime("%Y-%m-%d  %H:%M:%S"),
                    "Distancia mín (km)": round(miss, 4),
                    "σ combinado (km)": round(
                        float(hp.get("combined_sigma_at_tca_km", 0.0)), 3
                    ),
                    "TCA refinado": "✓" if hp.get("tca_was_refined") else "—",
                    "Solo aparente": "sí" if ev.is_apparent_not_confirmed else "no",
                    "evidence_id": _short_hash(ev.evidence_id),
                }
            )
    return sorted(rows, key=lambda r: r["Distancia mín (km)"])


def _highlight_miss(row: pd.Series) -> list[str]:
    miss = row["Distancia mín (km)"]
    if miss > 10.0:
        return ["background-color:#fff3cd; font-weight:bold"] * len(row)
    if miss > 1.0:
        return ["background-color:#f0f8ff"] * len(row)
    return ["color:#888"] * len(row)


def _render_verification_badge(case: InvestigationCase) -> None:
    report = verify_investigation_case(case)
    if report.is_valid:
        st.success(
            f"✓ Cadena íntegra — {report.n_artifacts_verified} artefactos verificados",
            icon="🔒",
        )
    else:
        st.error(
            f"✗ Cadena rota — {report.n_findings} fallo(s)",
            icon="⚠️",
        )
        for f in report.findings:
            st.warning(
                f"`{f.finding_type}` · esperado `{_short_hash(f.expected)}` "
                f"· obtenido `{_short_hash(f.actual)}`"
            )


def _render_case(case: InvestigationCase, *, run_verify: bool = True) -> None:
    primary = case.evidence_bundle.object_id
    st.markdown(f"#### {_norad_label(primary)}")
    st.caption(
        f"case\\_id: `{_short_hash(case.case_id, 20)}`  ·  "
        f"producido: {case.derived_at.strftime('%Y-%m-%d %H:%M UTC')}  ·  "
        f"{case.evidence_bundle.n_evidence_payloads} evidencias"
    )

    if run_verify:
        _render_verification_badge(case)

    # Hipótesis
    for hyp in case.hypothesis_registry.hypotheses:
        st.info(f"**Hipótesis:** {hyp.hypothesis_label}", icon="📋")

    st.divider()

    # Tabla de evidencias
    rows = _evidence_rows(case)
    if rows:
        df = pd.DataFrame(rows)
        st.markdown("**Evidencias detectadas** (ordenadas por distancia mínima)")
        st.caption(
            "Amarillo = acercamiento no co-orbital (>10 km). "
            "Gris = objeto co-orbital (docking/acoplado)."
        )
        st.dataframe(
            df.style.apply(_highlight_miss, axis=1),
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("Sin evidencias de tipo conjunction en este caso.")

    # Explicación verbatim
    with st.expander("Texto de explicación (verbatim del agente)", expanded=False):
        st.code(case.explanation_artifact.explanation_text, language=None)

    # Cadena de custodia
    with st.expander("Cadena de custodia criptográfica", expanded=False):
        chain_items = [
            ("bundle_id", case.referenced_bundle_id),
            ("agent_input_id", case.referenced_agent_input_id),
            ("explanation_id", case.referenced_explanation_id),
            ("claim_registry_id", case.referenced_claim_registry_id),
            ("hypothesis_registry_id", case.referenced_hypothesis_registry_id),
            ("chain_id", case.referenced_chain_id),
            ("case_signature", case.case_signature),
        ]
        for label, h in chain_items:
            st.text(f"  {label}:\n  {h}")
        st.caption(
            "Cada hash se computa sobre el contenido del artefacto anterior. "
            "Cualquier modificación silenciosa rompe la cadena."
        )


# ---------------------------------------------------------------------------
# Páginas
# ---------------------------------------------------------------------------


def _page_reference_cases() -> None:
    st.header("Casos de referencia", divider="gray")
    st.write(
        "Casos producidos a partir de una ingesta real de CelesTrak el 2026-06-08. "
        "Cada caso incluye la cadena criptográfica completa desde los bytes originales "
        "hasta las conclusiones. Cualquier persona puede verificarlos offline con "
        "`orbital-sentinel verify-investigation-case`."
    )

    cases = _list_reference_cases()
    if not cases:
        st.error("No se encontraron casos de referencia. Verifica que el repositorio esté completo.")
        return

    options = {_CASE_DISPLAY_NAMES.get(c, c): c for c in cases}
    label = st.selectbox("Selecciona un caso:", list(options.keys()))
    selected = options[label]

    with st.spinner("Cargando y verificando…"):
        try:
            case = _load_case(selected)
        except Exception as exc:
            st.error(f"Error al cargar `{selected}/case.json`: {exc}")
            return

    _render_case(case)

    # Cross-case hint
    if len(cases) > 1:
        st.divider()
        st.caption(
            "💡 El objeto **HMU-SAT2 (67688)** aparece como acercamiento real en "
            "**ambos** casos (ISS y CSS Tianhe) en la misma ventana de 7 días. "
            "Correlación solo visible porque la evidencia es content-addressable."
        )


def _page_verify() -> None:
    st.header("Verificar un InvestigationCase", divider="gray")
    st.write(
        "Sube cualquier `case.json` producido por Orbital Sentinel. "
        "La verificación ejecuta los mismos verifiers que CI y "
        "**no envía ningún dato a ningún servidor**."
    )

    uploaded = st.file_uploader(
        "Arrastra aquí tu case.json",
        type=["json"],
        key="verify_upload",
        help="Archivo producido por `orbital-sentinel investigate` o equivalente.",
    )

    if not uploaded:
        st.info(
            "Descarga uno de los casos de referencia desde la pestaña anterior "
            "o desde el repositorio de GitHub para probar.",
            icon="ℹ️",
        )
        return

    raw = uploaded.read().decode("utf-8")

    with st.spinner("Verificando…"):
        try:
            case = InvestigationCase.model_validate_json(raw)
        except Exception as exc:
            st.error(
                f"El archivo no pudo parsearse como `InvestigationCase`. "
                f"Detalle: `{exc}`"
            )
            return

        report = verify_investigation_case(case)

    # Resultado prominente
    if report.is_valid:
        st.success(
            f"**Cadena íntegra.** {report.n_artifacts_verified} artefactos verificados, "
            f"0 fallos.",
            icon="🔒",
        )
    else:
        st.error(
            f"**Cadena rota.** {report.n_findings} fallo(s) encontrado(s).",
            icon="⚠️",
        )
        for f in report.findings:
            st.warning(
                f"`{f.finding_type}`  \n"
                f"Esperado: `{f.expected[:32]}…`  \n"
                f"Obtenido: `{f.actual[:32]}…`"
            )

    st.divider()
    _render_case(case, run_verify=False)

    with st.expander("Reporte completo (JSON)", expanded=False):
        st.json(report.model_dump(mode="json"))


def _page_about() -> None:
    st.header("Sobre el proyecto", divider="gray")

    st.markdown(
        """
**Orbital Sentinel** es software de código abierto que permite a cualquier persona —
sin acceso privilegiado a datos, sin autoridad, sin necesidad de confiar en nadie —
*demostrar* qué está ocurriendo en órbita y *auditar* la afirmación de cualquier otro.

No es un rastreador de satélites. No es un panel de control. Es una
**cadena de custodia content-addressable** que vincula cada conclusión con los bytes
originales públicos que la produjeron.

---

### La arquitectura en cinco puntos

1. **Los bytes originales de CelesTrak se direccionan por SHA-256.**
   Si esos bytes cambian mañana (porque CelesTrak actualiza el TLE), el hash
   fija lo que *yo* descargué.

2. **Cada artefacto derivado lleva el hash de sus entradas.**
   Bundle → Agent Input → Explanation → Claims → Hypothesis → Chain → Case.
   Rompe un eslabón y el siguiente hash es incorrecto.

3. **La explicación es mecánica**, no generada. Cada frase es una plantilla
   rellena con datos: *"El detector X identificó el evento Y en el instante Z"*.
   Sin LLM, sin NLP, sin juicio sobre lo que *significa*.

4. **Los verifiers son funciones puras** que siempre devuelven un reporte
   estructurado. Nunca una excepción. Nunca un fallo silencioso.

5. **El contrato está congelado.** 16 hashes canónicos en el test suite.
   CI los verifica en cada commit. Cualquier cambio que altere silenciosamente
   el output de hash hace fallar CI.

---

### Lo que esto *no* es

- **Sin IA, sin LLM, sin ML.** El sistema no *interpreta*; *cita*.
- **Sin puntuaciones de riesgo.** Solo geometría con incertidumbre declarada.
- **Sin autoridad central.** Productores, revisores y disidentes tienen
  garantías criptográficas idénticas.
- **Sin dependencias externas en runtime** más allá de
  stdlib + Pydantic + DuckDB + PyArrow + SGP4.

---
"""
    )

    col1, col2, col3 = st.columns(3)
    with col1:
        st.link_button("Código en GitHub", "https://github.com/JFHelvetius/orbital_sentinel")
    with col2:
        st.link_button("Instalar desde PyPI", "https://pypi.org/project/orbital-sentinel/")
    with col3:
        st.link_button(
            "Por qué existe este proyecto",
            "https://github.com/JFHelvetius/orbital_sentinel/blob/main/docs/why-this-exists.md",
        )

    st.divider()
    st.caption(
        "Licencia Apache 2.0 · Sin afiliación con ninguna agencia espacial · "
        "Todos los datos provienen de fuentes públicas (CelesTrak)."
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    st.set_page_config(
        page_title="Orbital Sentinel",
        page_icon="🛰️",
        layout="wide",
        initial_sidebar_state="collapsed",
        menu_items={
            "Get Help": "https://github.com/JFHelvetius/orbital_sentinel/discussions",
            "Report a bug": "https://github.com/JFHelvetius/orbital_sentinel/issues",
            "About": (
                "Orbital Sentinel — infraestructura verificable para afirmaciones orbitales. "
                "Apache 2.0. Sin IA."
            ),
        },
    )

    st.title("🛰️  Orbital Sentinel")
    st.caption(
        "Infraestructura verificable para afirmaciones sobre el entorno orbital. "
        "Sin IA · Sin puntuaciones de riesgo · Sin autoridad central."
    )

    tab_cases, tab_verify, tab_about = st.tabs([
        "📋  Casos de referencia",
        "🔍  Verificar un caso",
        "ℹ️  Sobre el proyecto",
    ])

    with tab_cases:
        _page_reference_cases()
    with tab_verify:
        _page_verify()
    with tab_about:
        _page_about()


if __name__ == "__main__":
    main()
