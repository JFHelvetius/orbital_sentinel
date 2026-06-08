"""Agent Input Contract v0.1 (ADR-0032)."""

from orbital_sentinel.analytics.agent_contract.builder import build_agent_input
from orbital_sentinel.analytics.agent_contract.models import (
    CONTRACT_ENGINE_VERSION,
    CONTRACT_SCHEMA_VERSION,
    AgentInput,
    ConsumerClass,
    compute_agent_input_id,
)

__all__ = [
    "CONTRACT_ENGINE_VERSION",
    "CONTRACT_SCHEMA_VERSION",
    "AgentInput",
    "ConsumerClass",
    "build_agent_input",
    "compute_agent_input_id",
]
