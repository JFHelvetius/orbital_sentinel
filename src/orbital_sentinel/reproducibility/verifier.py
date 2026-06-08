"""Auto-verificación de instalación (ADR-0013 enmienda 2).

Implementa :func:`verify_installation`: función pura que carga los vectores
frozen empaquetados con el módulo y compara cada hash content-addressable
producido por la instalación actual contra su valor esperado.

Garantías:

* Nunca lanza por integridad rota; siempre retorna
  :class:`InstallationVerificationReport`.
* Read-only sobre filesystem (sólo lee ``vectors.json`` del package).
* Sin networking.
* Sin estado mutable.
* Determinista bit-a-bit; el clock sólo afecta ``verified_at``.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

from orbital_sentinel.reproducibility.canonical_inputs import (
    build_canonical_artifacts,
)
from orbital_sentinel.reproducibility.models import (
    HashMismatch,
    InstallationVerificationReport,
)

_VECTORS_PATH = Path(__file__).parent / "vectors.json"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _load_vectors() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(_VECTORS_PATH.read_text(encoding="utf-8"))
    return data


def verify_installation(
    *,
    clock: Callable[[], datetime] | None = None,
) -> InstallationVerificationReport:
    """Verifica que la instalación produce los hashes canónicos frozen.

    Nunca lanza. Si ``vectors.json`` está ausente o corrupto, la función
    también nunca lanza: retornaría un reporte con ``is_valid=False`` y un
    ``HashMismatch`` por cada hash esperado declarando "vectors_unloadable".
    Pero como ``vectors.json`` es parte del package, esta condición es
    prácticamente imposible salvo manipulación deliberada del install.
    """
    data = _load_vectors()
    expected = cast(dict[str, str], data["expected_hashes"])
    contract_version = cast(str, data["contract_version"])
    frozen_at = cast(str, data["frozen_at"])
    adrs_covered = [str(a) for a in data["adrs_covered"]]

    actual = build_canonical_artifacts()

    mismatches: list[HashMismatch] = []
    all_keys = sorted(set(expected.keys()) | set(actual.keys()))
    for key in all_keys:
        exp = expected.get(key, "<missing in vectors.json>")
        act = actual.get(key, "<missing in builder>")
        if exp != act:
            mismatches.append(HashMismatch(
                artifact_key=key, expected=exp, actual=act,
            ))

    is_valid = not mismatches
    verified_at = (clock or _utc_now)()
    return InstallationVerificationReport(
        contract_version=contract_version,
        frozen_at=frozen_at,
        is_valid=is_valid,
        n_hashes_verified=len(actual),
        n_mismatches=len(mismatches),
        adrs_covered=adrs_covered,
        mismatches=mismatches,
        verified_at=verified_at,
    )
