"""Implementación SGP4 del propagador (ADR-0005, ADR-0014).

Usa la librería ``sgp4`` (Brandon Rhodes, port directo del Fortran de Vallado).
El wrapper:

1. Verifica consistencia ``element.content_hash_source == snapshot.content_hash``.
2. Extrae las dos líneas TLE originales desde ``snapshot.raw_text`` en la
   posición ``element.tle_index``.
3. Verifica que ``sha256(line1+\\n+line2) == element.tle_content_hash``
   (defensa en profundidad contra corrupción cross-layer).
4. Construye un ``Satrec`` con ``Satrec.twoline2rv(line1, line2)``: nunca con
   ``Satrec.sgp4init()`` desde campos parseados, para mantener coherencia
   bit-exacta con la librería en cualquier futuro cambio del parser.
5. Convierte ``datetime`` UTC → Julian Date con ``sgp4.api.jday``.
6. Llama ``sat.sgp4(jd, fr)`` por cada instante y produce un :class:`Ephemeris`.

Determinismo: en el mismo entorno declarado (ADR-0013), dos llamadas con los
mismos inputs producen ``Ephemeris`` bit-idénticos (excepto ``derived_at``,
que se materializa una vez por llamada y se comparte por todos los outputs).
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Sequence
from datetime import datetime, timezone

from sgp4.api import Satrec, jday

from orbital_sentinel.catalog.normalizers import iter_tle_blocks
from orbital_sentinel.catalog.orbital_elements import OrbitalElement
from orbital_sentinel.catalog.tle_snapshots import TLESnapshot
from orbital_sentinel.core.errors import PropagationError
from orbital_sentinel.propagation.ephemeris import (
    EPHEMERIS_SCHEMA_VERSION,
    Ephemeris,
)

SGP4_PROPAGATOR_VERSION = "0.1.0"
"""SemVer del wrapper SGP4 (ADR-0010 engine_version).

Captura **solo** este wrapper. La versión de la librería ``sgp4`` está
pinned en ``pyproject.toml`` / ``uv.lock`` y forma parte del entorno declarado
(ADR-0013). Cualquier cambio de comportamiento de la librería que altere
outputs requiere bump de PATCH en este wrapper para registrar la divergencia.
"""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Sgp4Propagator:
    """Propagador SGP4 sobre ``OrbitalElement`` → ``Ephemeris`` en memoria.

    On-demand por defecto. No persiste. ADR-0006 enmienda 1.
    """

    name: str = "sgp4"
    engine_version: str = SGP4_PROPAGATOR_VERSION

    def __init__(self, *, clock: Callable[[], datetime] | None = None) -> None:
        self._clock: Callable[[], datetime] = clock if clock is not None else _utc_now

    def propagate(
        self,
        element: OrbitalElement,
        snapshot: TLESnapshot,
        times: Sequence[datetime],
    ) -> list[Ephemeris]:
        """Propaga ``element`` a los instantes ``times``.

        Args:
            element: la fila Normalized.
            snapshot: la fila Raw que contiene el TLE original. Debe ser el
                snapshot referenciado por ``element.content_hash_source``.
            times: instantes UTC. Cada uno produce un ``Ephemeris``. Lista
                vacía devuelve lista vacía.

        Returns:
            ``len(times)`` ``Ephemeris`` en el mismo orden.

        Raises:
            PropagationError: si element y snapshot no son consistentes, si
                el TLE no se puede reconstruir, si la librería SGP4 falla al
                inicializar, o si algún instante no es tz-aware.
        """
        if element.content_hash_source != snapshot.content_hash:
            raise PropagationError(
                "OrbitalElement y TLESnapshot inconsistentes: "
                f"element.content_hash_source={element.content_hash_source[:12]}…, "
                f"snapshot.content_hash={snapshot.content_hash[:12]}…"
            )

        line1, line2 = _extract_tle_lines(snapshot, element.tle_index)
        _verify_tle_hash(line1, line2, element.tle_content_hash)

        try:
            sat = Satrec.twoline2rv(line1, line2)
        except Exception as exc:
            raise PropagationError(
                f"Satrec.twoline2rv falló para el TLE {element.tle_content_hash[:12]}…: {exc}"
            ) from exc

        if sat.error != 0:
            raise PropagationError(
                f"sgp4init devolvió código de error {sat.error} "
                f"para el TLE {element.tle_content_hash[:12]}…"
            )

        if not times:
            return []

        derived_at = self._clock()
        epoch = element.epoch_datetime

        result: list[Ephemeris] = []
        for t in times:
            if t.tzinfo is None:
                raise PropagationError(
                    "Todos los evaluation_time deben ser timezone-aware (ADR-0013)"
                )
            t_utc = t.astimezone(timezone.utc)
            jd, fr = jday(
                t_utc.year,
                t_utc.month,
                t_utc.day,
                t_utc.hour,
                t_utc.minute,
                t_utc.second + t_utc.microsecond * 1e-6,
            )
            err_code, r, v = sat.sgp4(jd, fr)
            minutes_from_epoch = (t_utc - epoch).total_seconds() / 60.0

            result.append(
                Ephemeris(
                    orbital_element_content_hash_source=element.content_hash_source,
                    orbital_element_tle_index=element.tle_index,
                    tle_content_hash=element.tle_content_hash,
                    norad_cat_id=element.norad_cat_id,
                    evaluation_time=t_utc,
                    minutes_from_epoch=minutes_from_epoch,
                    position_teme_x_km=float(r[0]),
                    position_teme_y_km=float(r[1]),
                    position_teme_z_km=float(r[2]),
                    velocity_teme_x_km_s=float(v[0]),
                    velocity_teme_y_km_s=float(v[1]),
                    velocity_teme_z_km_s=float(v[2]),
                    sgp4_error_code=int(err_code),
                    schema_version=EPHEMERIS_SCHEMA_VERSION,
                    engine_version=self.engine_version,
                    derived_at=derived_at,
                )
            )
        return result

    def propagate_at_epoch(
        self, element: OrbitalElement, snapshot: TLESnapshot
    ) -> Ephemeris:
        """Conveniencia: propaga al epoch del propio TLE."""
        return self.propagate(element, snapshot, [element.epoch_datetime])[0]


def _extract_tle_lines(snapshot: TLESnapshot, tle_index: int) -> tuple[str, str]:
    """Localiza las dos líneas TLE del bloque ``tle_index`` dentro del snapshot."""
    for idx, block in iter_tle_blocks(snapshot.raw_text):
        if idx != tle_index:
            continue
        lines = block.split("\n")
        if len(lines) < 2:
            raise PropagationError(
                f"Bloque TLE en índice {tle_index} tiene menos de 2 líneas"
            )
        return lines[-2], lines[-1]
    raise PropagationError(
        f"TLE index {tle_index} no encontrado en snapshot {snapshot.content_hash[:12]}…"
    )


def _verify_tle_hash(line1: str, line2: str, expected_hash: str) -> None:
    """Comprueba que la reconstrucción coincide con ``element.tle_content_hash``."""
    canonical = (line1 + "\n" + line2).encode("ascii")
    actual = hashlib.sha256(canonical).hexdigest()
    if actual != expected_hash:
        raise PropagationError(
            "Hash del TLE reconstruido no coincide con tle_content_hash: "
            f"esperado={expected_hash[:12]}…, actual={actual[:12]}…"
        )
