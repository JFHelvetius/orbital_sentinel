"""Tipos públicos del subsistema de sources: ``RawArtifact`` y ``Source``."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field


class RawArtifact(BaseModel):
    """Bytes descargados con su procedencia.

    Es el contrato de salida de toda implementación de :class:`Source`.
    Contiene la información mínima necesaria para registrar una fila
    inmutable en la capa Raw (ADR-0006) sin tener que reconstruir el
    contexto desde la red.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    source: str = Field(description="Nombre de la fuente, e.g. 'celestrak'.")
    dataset: str = Field(description="Identificador del dataset dentro de la fuente.")
    url: str = Field(description="URL canónica de la cual se descargó.")
    fetched_at: datetime = Field(description="Timestamp UTC del fetch.")
    raw_bytes: bytes = Field(description="Bytes recibidos sin modificar.")
    content_hash: str = Field(description="SHA-256 hex de ``raw_bytes``.")


class Source(Protocol):
    """Interfaz mínima de una fuente. Devuelve :class:`RawArtifact`.

    Implementaciones decidirán de dónde vienen los bytes (red, cache, fixture).
    """

    name: str

    def fetch(self, dataset: str) -> RawArtifact:
        ...
