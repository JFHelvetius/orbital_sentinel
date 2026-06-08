"""Installation Self-Verification (ADR-0013 enmienda 2).

Contrato cryptográfico frozen empaquetado con el deliverable, accesible
desde cualquier instalación tras ``pip install``.
"""

from orbital_sentinel.reproducibility.canonical_inputs import (
    build_canonical_artifacts,
)
from orbital_sentinel.reproducibility.models import (
    REPRODUCIBILITY_PACKAGE_VERSION,
    HashMismatch,
    InstallationVerificationReport,
)
from orbital_sentinel.reproducibility.verifier import verify_installation

__all__ = [
    "REPRODUCIBILITY_PACKAGE_VERSION",
    "HashMismatch",
    "InstallationVerificationReport",
    "build_canonical_artifacts",
    "verify_installation",
]
