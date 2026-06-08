"""Plano Orchestration: workflows de composición + (futuro) primitivas de scheduling.

Ver ADR-0002 enmienda 1 sobre la doble función de este plano.
"""

from orbital_sentinel.orchestration.ingest_pipeline import (
    IngestPipeline,
    IngestResult,
)

__all__ = [
    "IngestPipeline",
    "IngestResult",
]
