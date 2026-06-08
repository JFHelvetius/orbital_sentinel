"""Time-series de OrbitalElements para un mismo NORAD (ADR-0027).

Envuelve una lista de :class:`OrbitalElement` ordenados por epoch ascendente
con validación estricta. Es la entrada de :func:`detect_maneuvers`.

Invariantes verificados al construir:

* ``len ≥ 2`` (necesario para tener al menos una transición).
* Todos los elementos pertenecen al mismo ``norad_cat_id``.
* ``epoch_datetime`` estrictamente ascendente (sin duplicados ni inversiones).
* ``tle_content_hash`` únicos (defensa contra carga duplicada).
"""

from __future__ import annotations

from datetime import datetime

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from orbital_sentinel.catalog.orbital_elements import OrbitalElement


class OrbitalElementSeries(BaseModel):
    """Serie temporal de OrbitalElements para un único NORAD (ADR-0027)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    norad_cat_id: int
    elements: list[OrbitalElement] = Field(min_length=2)
    series_start_epoch: AwareDatetime
    series_end_epoch: AwareDatetime
    n_elements: int = Field(ge=2)

    @classmethod
    def from_elements(
        cls, elements: list[OrbitalElement]
    ) -> OrbitalElementSeries:
        """Construye con validación estricta. Raises ``ValueError`` si:

        * ``len(elements) < 2``
        * Distinto ``norad_cat_id`` entre elementos
        * Epochs no estrictamente ascendentes
        * ``tle_content_hash`` duplicado
        """
        if len(elements) < 2:
            raise ValueError(
                f"OrbitalElementSeries requiere len ≥ 2; recibido {len(elements)}"
            )

        norad = elements[0].norad_cat_id
        for el in elements[1:]:
            if el.norad_cat_id != norad:
                raise ValueError(
                    f"OrbitalElementSeries requiere mismo norad_cat_id; "
                    f"encontrado {el.norad_cat_id} vs {norad}"
                )

        for i in range(1, len(elements)):
            prev = elements[i - 1].epoch_datetime
            curr = elements[i].epoch_datetime
            if not curr > prev:
                raise ValueError(
                    f"OrbitalElementSeries requiere epochs estrictamente "
                    f"ascendentes; índice {i} epoch={curr} no es > {prev}"
                )

        seen_hashes: set[str] = set()
        for el in elements:
            if el.tle_content_hash in seen_hashes:
                raise ValueError(
                    f"OrbitalElementSeries detecta tle_content_hash duplicado: "
                    f"{el.tle_content_hash[:12]}…"
                )
            seen_hashes.add(el.tle_content_hash)

        return cls(
            norad_cat_id=norad,
            elements=list(elements),
            series_start_epoch=_to_aware(elements[0].epoch_datetime),
            series_end_epoch=_to_aware(elements[-1].epoch_datetime),
            n_elements=len(elements),
        )


def _to_aware(dt: datetime) -> datetime:
    """Coacciona a tz-aware UTC. Los OrbitalElements lo son por construcción."""
    if dt.tzinfo is None:
        from datetime import timezone

        return dt.replace(tzinfo=timezone.utc)
    return dt
