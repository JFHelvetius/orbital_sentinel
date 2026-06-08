"""Transporte HTTP inyectable.

La capa de transporte está aislada para que los tests inyecten implementaciones
sin red (ver ADR-0012, ADR-0013). El default usa ``urllib`` de la stdlib, sin
añadir dependencias de terceros para HTTP.
"""

from __future__ import annotations

import urllib.error
import urllib.request
from typing import Protocol

from orbital_sentinel.core.errors import IngestionError


class TransportError(IngestionError):
    """Error transportando bytes desde una fuente remota."""


class HttpTransport(Protocol):
    """Contrato HTTP mínimo: GET con cabeceras y timeout, devuelve bytes."""

    def get(self, url: str, *, headers: dict[str, str], timeout: float) -> bytes:
        ...


class UrllibTransport:
    """Implementación basada en ``urllib`` de la stdlib.

    Sin dependencias adicionales (ADR-0012 baseline). Suficiente para Phase 1.
    """

    def get(self, url: str, *, headers: dict[str, str], timeout: float = 30.0) -> bytes:
        request = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload: bytes = response.read()
                return payload
        except urllib.error.URLError as exc:
            raise TransportError(f"HTTP fetch failed: {url}: {exc}") from exc
