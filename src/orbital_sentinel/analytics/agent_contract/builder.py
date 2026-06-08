"""Builder del :class:`AgentInput` (ADR-0032).

Función pura. Internamente ejecuta :func:`verify_bundle`. Si el bundle no
es válido, lanza :class:`AgentInputRejectedError` con el report adjunto.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone

from orbital_sentinel.analytics.agent_contract.models import (
    CONTRACT_ENGINE_VERSION,
    AgentInput,
    ConsumerClass,
    compute_agent_input_id,
)
from orbital_sentinel.analytics.bundles import EvidenceBundle, verify_bundle
from orbital_sentinel.core.errors import AgentInputRejectedError


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def build_agent_input(
    bundle: EvidenceBundle,
    *,
    declared_consumer_class: ConsumerClass,
    clock: Callable[[], datetime] | None = None,
) -> AgentInput:
    """Construye un :class:`AgentInput` solo si el bundle pasa verificación.

    Raises:
        AgentInputRejectedError: si ``verify_bundle(bundle).is_valid`` es False.
            El error porta el ``verification_report`` para inspección.
    """
    report = verify_bundle(bundle, clock=clock)
    if not report.is_valid:
        raise AgentInputRejectedError(
            f"Bundle {bundle.bundle_id[:12]}… rejected: "
            f"{len(report.integrity_failures)} integrity failure(s); "
            "is_valid=False.",
            verification_report=report,
        )
    agent_input_id = compute_agent_input_id(
        bundle_id=bundle.bundle_id,
        declared_consumer_class=declared_consumer_class,
        contract_engine_version=CONTRACT_ENGINE_VERSION,
    )
    return AgentInput(
        agent_input_id=agent_input_id,
        bundle=bundle,
        verification_report=report,
        declared_consumer_class=declared_consumer_class,
        contract_acceptance_at=(clock or _utc_now)(),
    )
