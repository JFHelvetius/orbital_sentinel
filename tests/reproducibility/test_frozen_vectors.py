"""Suite empírica del contrato de reproducibilidad (ADR-0013 enmiendas 1+2).

Importa los constructores canónicos y los vectores frozen desde el package
de producción :mod:`orbital_sentinel.reproducibility` (ADR-0013 enmienda 2)
y compara los hashes content-addressable producidos contra los esperados.

Cualquier discrepancia indica:

* Un cambio deliberado en el contrato cryptográfico → debe ir acompañado de
  enmienda al ADR-0013 + regeneración explícita de ``vectors.json``.
* Una regresión accidental → debe revertirse antes de merge.

Esta suite es **read-only sobre el código de producción**. Borrar
``tests/reproducibility/`` deja el sistema funcionando idéntico.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from orbital_sentinel.reproducibility import build_canonical_artifacts
from orbital_sentinel.reproducibility import verifier as _repro_verifier

VECTORS_PATH = Path(_repro_verifier.__file__).parent / "vectors.json"


def _load_vectors() -> dict[str, object]:
    return json.loads(VECTORS_PATH.read_text(encoding="utf-8"))


# --- Existencia y estructura del fixture --------------------------------


def test_vectors_file_exists() -> None:
    assert VECTORS_PATH.is_file(), f"vectors.json no encontrado en {VECTORS_PATH}"


def test_vectors_file_has_required_top_level_keys() -> None:
    data = _load_vectors()
    for key in (
        "contract_version", "frozen_at", "documentation",
        "canonical_inputs", "expected_hashes", "adrs_covered",
    ):
        assert key in data, f"vectors.json carece de la clave '{key}'"


def test_vectors_contract_version_is_semver() -> None:
    data = _load_vectors()
    version = data["contract_version"]
    assert isinstance(version, str)
    parts = version.split(".")
    assert len(parts) == 3, f"contract_version no es SemVer X.Y.Z: {version}"
    for p in parts:
        assert p.isdigit(), f"contract_version contiene componente no numérico: {p}"


# --- Determinismo del generador --------------------------------------


def test_canonical_builder_is_deterministic() -> None:
    """Dos invocaciones del builder producen el mismo conjunto de hashes."""
    a = build_canonical_artifacts()
    b = build_canonical_artifacts()
    assert a == b


# --- Cobertura: cada hash esperado tiene su contrapartida ------------


def test_every_expected_hash_is_produced_by_builder() -> None:
    data = _load_vectors()
    expected: dict[str, str] = data["expected_hashes"]  # type: ignore[assignment]
    actual = build_canonical_artifacts()
    missing_from_actual = set(expected.keys()) - set(actual.keys())
    assert not missing_from_actual, (
        f"Hashes declarados en vectors.json pero no producidos por el builder: "
        f"{sorted(missing_from_actual)}"
    )


def test_every_produced_hash_has_expected_vector() -> None:
    """Garantía simétrica: ningún hash producido queda sin frozen."""
    data = _load_vectors()
    expected: dict[str, str] = data["expected_hashes"]  # type: ignore[assignment]
    actual = build_canonical_artifacts()
    missing_from_vectors = set(actual.keys()) - set(expected.keys())
    assert not missing_from_vectors, (
        f"Hashes producidos pero sin entry en vectors.json: "
        f"{sorted(missing_from_vectors)}. "
        "Añadir su valor frozen tras revisión humana."
    )


# --- Hash-by-hash: el contrato real -------------------------------


@pytest.mark.parametrize(
    "artifact_key",
    [
        "evidence_id",
        "bundle_id",
        "agent_input_id",
        "explanation_id",
        "claim_id_0",
        "claim_registry_id",
        "hypothesis_id_0",
        "hypothesis_registry_id",
        "chain_id",
        "case_id",
        "revocation_id",
        "revocation_ledger_id",
        "source_record_id",
        "external_source_registry_id",
        "dissent_id",
        "dissent_ledger_id",
    ],
)
def test_frozen_hash_matches_expected(artifact_key: str) -> None:
    """Para cada artefacto content-addressable: hash producido == hash frozen."""
    data = _load_vectors()
    expected: dict[str, str] = data["expected_hashes"]  # type: ignore[assignment]
    actual = build_canonical_artifacts()
    assert actual[artifact_key] == expected[artifact_key], (
        f"DRIFT DETECTADO en {artifact_key}: "
        f"frozen={expected[artifact_key]}, "
        f"actual={actual[artifact_key]}. "
        "Esto indica un cambio (deliberado o accidental) en el contrato "
        "cryptográfico. Si es deliberado: bump contract_version, "
        "actualiza vectors.json, enmienda ADR-0013, documenta el motivo."
    )


# --- Sanidad de los hashes -----------------------------------------


@pytest.mark.parametrize(
    "artifact_key",
    [
        "evidence_id", "bundle_id", "agent_input_id", "explanation_id",
        "claim_id_0", "claim_registry_id", "hypothesis_id_0",
        "hypothesis_registry_id", "chain_id", "case_id",
        "revocation_id", "revocation_ledger_id", "source_record_id",
        "external_source_registry_id", "dissent_id", "dissent_ledger_id",
    ],
)
def test_frozen_hash_is_well_formed_sha256(artifact_key: str) -> None:
    """Garantía estructural: cada hash es SHA-256 hex (64 chars, hex)."""
    data = _load_vectors()
    expected: dict[str, str] = data["expected_hashes"]  # type: ignore[assignment]
    h = expected[artifact_key]
    assert isinstance(h, str)
    assert len(h) == 64, f"{artifact_key} no tiene 64 caracteres: len={len(h)}"
    int(h, 16)  # debe parsearse como hex (raise si no)


# --- Cobertura de ADRs declarada ----------------------------------


def test_adrs_covered_includes_all_content_addressable_layers() -> None:
    """vectors.json declara qué ADRs cubre. Debe incluir al menos las capas
    content-addressable de ADR-0029 a ADR-0041."""
    data = _load_vectors()
    covered: list[str] = data["adrs_covered"]  # type: ignore[assignment]
    required = {
        "ADR-0029", "ADR-0031", "ADR-0032", "ADR-0033", "ADR-0035",
        "ADR-0036", "ADR-0037", "ADR-0038", "ADR-0039", "ADR-0040",
        "ADR-0041",
    }
    missing = required - set(covered)
    assert not missing, (
        f"vectors.json declara cobertura incompleta. Faltan: {sorted(missing)}"
    )
