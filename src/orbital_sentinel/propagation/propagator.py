"""Contrato mínimo de propagador (Protocol).

ADR-0005 estableció SGP4 como único motor de propagación de v1 pero declaró
una interfaz abstracta para no bloquear extensión futura (e.g., OMM/SP,
propagadores numéricos). Este módulo define ese contrato.

Implementaciones actuales: :class:`Sgp4Propagator`.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

from orbital_sentinel.catalog.orbital_elements import OrbitalElement
from orbital_sentinel.catalog.tle_snapshots import TLESnapshot
from orbital_sentinel.propagation.ephemeris import Ephemeris


class Propagator(Protocol):
    """Contrato mínimo de un propagador.

    Un propagador toma una fila Normalized (``element``) y su snapshot Raw
    (``snapshot``, fuente de los bytes originales) y produce una lista de
    :class:`Ephemeris` en los instantes solicitados.

    Implementaciones deben:

    - Verificar consistencia ``element ↔ snapshot`` antes de propagar.
    - Cargar las dos líneas TLE originales desde el ``snapshot.raw_text``
      en lugar de reconstruirlas desde campos parseados.
    - Preservar códigos de error del motor (no ocultarlos).
    - Marcar cada Ephemeris con su propio ``engine_version`` y ``derived_at``.
    """

    name: str
    engine_version: str

    def propagate(
        self,
        element: OrbitalElement,
        snapshot: TLESnapshot,
        times: Sequence[datetime],
    ) -> list[Ephemeris]:
        ...
