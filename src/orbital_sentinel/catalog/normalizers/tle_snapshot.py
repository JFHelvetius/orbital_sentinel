"""Normalización ``TLESnapshot`` (Raw) → lista de ``OrbitalElement`` (Normalized).

Función pura y determinista. No requiere SGP4, ni red, ni ninguna librería
de física. Solo el parser TLE local de :mod:`orbital_sentinel.ingestion.parsers.tle`.

Trazabilidad
------------
Cada ``OrbitalElement`` producido lleva:

* ``content_hash_source`` apuntando a ``TLESnapshot.content_hash``.
* ``tle_index`` con su posición dentro del snapshot.
* ``tle_content_hash`` identificando el TLE individual.
* ``engine_version`` con la versión del normalizador.
* ``derived_at`` con el instante de la derivación.

Idempotencia
------------
La función en sí es pura. La idempotencia operativa la garantiza el
repositorio: re-insertar la misma colección sobre el mismo
``(engine_version, content_hash_source)`` es no-op (ADR-0006 sin UPDATE).
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timedelta, timezone

from orbital_sentinel.catalog.orbital_elements import (
    ORBITAL_ELEMENTS_SCHEMA_VERSION,
    OrbitalElement,
)
from orbital_sentinel.catalog.tle_snapshots import TLESnapshot
from orbital_sentinel.core.errors import NormalizationError, TLEParseError
from orbital_sentinel.ingestion.parsers.tle import TLE_LINE_LENGTH, parse_tle

NORMALIZER_VERSION = "0.1.0"
"""SemVer del algoritmo de normalización (se persiste como ``engine_version``)."""


def iter_tle_blocks(text: str) -> Iterator[tuple[int, str]]:
    """Itera los bloques TLE de un texto que puede contener varios.

    Yields:
        ``(index, block)`` donde ``index`` es la posición 0-based del bloque y
        ``block`` es el texto del TLE (2 o 3 líneas) listo para ``parse_tle``.

    Acepta:
    - Solo dos líneas por TLE (sin línea de nombre).
    - Tres líneas por TLE (con línea de nombre).
    - Mezcla de ambos formatos en el mismo texto.
    - Terminadores ``\\n`` o ``\\r\\n``.
    - Líneas en blanco entre bloques.

    Raises:
        NormalizationError: si el texto termina con un bloque truncado.
    """
    raw_lines = text.replace("\r\n", "\n").split("\n")
    lines = [ln for ln in raw_lines if ln.strip() != ""]

    i = 0
    index = 0
    while i < len(lines):
        line = lines[i]
        is_two_line_block = len(line) == TLE_LINE_LENGTH and line.startswith("1 ")
        if is_two_line_block:
            if i + 1 >= len(lines):
                raise NormalizationError(
                    f"Bloque TLE truncado en índice {index}: falta línea 2"
                )
            block = line + "\n" + lines[i + 1]
            yield index, block
            i += 2
        else:
            if i + 2 >= len(lines):
                raise NormalizationError(
                    f"Bloque TLE truncado en índice {index}: faltan líneas"
                )
            block = line + "\n" + lines[i + 1] + "\n" + lines[i + 2]
            yield index, block
            i += 3
        index += 1


def tle_epoch_to_datetime(epoch_year: int, epoch_day: float) -> datetime:
    """Convierte ``(epoch_year, epoch_day)`` a ``datetime`` UTC.

    Convención TLE: día ``1.0`` = 1 de enero a las 00:00:00 UTC. Día
    ``N.frac`` = ``N-1`` días después del 1 de enero más ``frac * 86400``
    segundos.
    """
    int_day = int(epoch_day)
    frac = epoch_day - int_day
    base = datetime(epoch_year, 1, 1, tzinfo=timezone.utc) + timedelta(days=int_day - 1)
    return base + timedelta(seconds=frac * 86400.0)


def normalize_snapshot(
    snapshot: TLESnapshot,
    *,
    derived_at: datetime,
    engine_version: str = NORMALIZER_VERSION,
) -> list[OrbitalElement]:
    """Deriva los ``OrbitalElement`` de un ``TLESnapshot``.

    Args:
        snapshot: snapshot Raw cuya ``raw_text`` contiene uno o más TLEs.
        derived_at: timestamp UTC de la derivación. Debe ser tz-aware.
        engine_version: versión SemVer del normalizador (por defecto
            :data:`NORMALIZER_VERSION`). Sobrescribible para tests o para
            ejecutar derivaciones controladas con versiones explícitas.

    Returns:
        Lista de ``OrbitalElement`` con la misma cardinalidad que el número
        de TLEs en el snapshot, en el mismo orden. Misma entrada → misma
        salida (función pura).

    Raises:
        NormalizationError: si ``derived_at`` es naive o si algún bloque TLE
            no puede parsearse. ADR-0006 prohíbe normalizaciones parciales
            silenciosas.
    """
    if derived_at.tzinfo is None:
        raise NormalizationError("derived_at debe ser timezone-aware")

    derived_at_utc = derived_at.astimezone(timezone.utc)
    elements: list[OrbitalElement] = []
    for idx, block in iter_tle_blocks(snapshot.raw_text):
        try:
            tle = parse_tle(block)
        except TLEParseError as exc:
            raise NormalizationError(
                f"Fallo parseando TLE índice {idx} del snapshot "
                f"{snapshot.content_hash[:12]}…: {exc}"
            ) from exc
        elements.append(
            OrbitalElement(
                content_hash_source=snapshot.content_hash,
                tle_index=idx,
                tle_content_hash=tle.content_hash,
                object_name=tle.name,
                norad_cat_id=tle.norad_cat_id,
                classification=tle.classification,
                intl_designator=tle.intl_designator,
                epoch_year=tle.epoch_year,
                epoch_day=tle.epoch_day,
                epoch_datetime=tle_epoch_to_datetime(tle.epoch_year, tle.epoch_day),
                mean_motion_dot=tle.mean_motion_dot,
                mean_motion_ddot=tle.mean_motion_ddot,
                bstar=tle.bstar,
                ephemeris_type=tle.ephemeris_type,
                element_set_number=tle.element_set_number,
                inclination_deg=tle.inclination_deg,
                raan_deg=tle.raan_deg,
                eccentricity=tle.eccentricity,
                arg_perigee_deg=tle.arg_perigee_deg,
                mean_anomaly_deg=tle.mean_anomaly_deg,
                mean_motion=tle.mean_motion,
                rev_number=tle.rev_number,
                schema_version=ORBITAL_ELEMENTS_SCHEMA_VERSION,
                engine_version=engine_version,
                derived_at=derived_at_utc,
            )
        )
    return elements
