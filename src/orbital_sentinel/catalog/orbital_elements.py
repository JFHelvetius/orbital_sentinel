"""``orbital_elements``: primera tabla de la capa Normalized (ADR-0006).

Cada fila representa un TLE individual parseado y validado a partir de un
``TLESnapshot`` de la capa Raw. La derivación es **pura y determinista**: no
involucra propagación, ni red, ni dependencias físicas más allá del parser
local TLE.

Identidad
---------
Compuesta: ``(content_hash_source, tle_index)``.

* ``content_hash_source`` es la **clave foránea lógica** a
  ``tle_snapshots.content_hash``. La integridad referencial no se enforza a
  nivel de motor (no hay FK constraint en Parquet), pero el invariante se
  mantiene por construcción del normalizador y se valida con tests de
  consistencia.
* ``tle_index`` localiza la posición 0-based dentro del snapshot fuente.

Versionado (ADR-0010)
---------------------
Tres versiones independientes coexisten en cada fila:

* ``schema_version``: SemVer del esquema Parquet de esta tabla.
* ``engine_version``: SemVer del algoritmo normalizador. Permite que
  derivaciones con normalizadores distintos coexistan sin destruirse
  mutuamente (regla de coexistencia de ADR-0010).
* ``derived_at``: instante UTC en que se ejecutó la derivación (operacional,
  no contractual).

Storage (ADR-0004)
------------------
Layout en disco::

    root/
        engine_version=<X.Y.Z>/
            source_<hash[:2]>/
                snap_<content_hash_source>.parquet

Un único archivo Parquet contiene todas las filas derivadas de un mismo
snapshot por un mismo normalizador. Inserción idempotente: si el archivo
existe, no se reescribe (ADR-0006 sin UPDATE).
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Sequence
from datetime import datetime
from pathlib import Path
from typing import Literal

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
from pydantic import BaseModel, ConfigDict, Field

from orbital_sentinel.core.errors import OrbitalSentinelError

ORBITAL_ELEMENTS_SCHEMA_VERSION = "0.1.0"
"""Versión SemVer del esquema de la tabla (ADR-0010)."""


Classification = Literal["U", "C", "S"]


class OrbitalElementsError(OrbitalSentinelError):
    """Error operando el repositorio de ``orbital_elements``."""


class OrbitalElement(BaseModel):
    """Una fila de ``orbital_elements`` (capa Normalized).

    Pertenencia de campos:

    * **Provenance** (link a Raw): ``content_hash_source``, ``tle_index``.
    * **TLE identity**: ``tle_content_hash``, ``object_name``.
    * **Catalog identity**: ``norad_cat_id``, ``classification``,
      ``intl_designator``.
    * **Epoch**: ``epoch_year``, ``epoch_day`` (forma TLE original) y
      ``epoch_datetime`` (derivado determinístico).
    * **Mean elements**: el resto de los campos físicos del TLE.
    * **Derivation context**: ``schema_version``, ``engine_version``,
      ``derived_at``.

    Lo que **NO** pertenece a este modelo (vive en Raw, recuperable vía JOIN):
    ``source``, ``dataset``, ``url``, ``fetched_at``, ``raw_text``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    # --- Provenance (link a Raw) ---
    content_hash_source: str = Field(
        description="FK lógica a tle_snapshots.content_hash."
    )
    tle_index: int = Field(description="Posición 0-based dentro del snapshot.")

    # --- TLE identity (independiente del snapshot) ---
    tle_content_hash: str = Field(
        description="SHA-256 hex del TLE individual (line1+\\n+line2)."
    )
    object_name: str | None = Field(
        default=None,
        description="Nombre opcional (línea 0 del TLE) si está presente.",
    )

    # --- Catalog identity ---
    norad_cat_id: int = Field(description="Número de catálogo NORAD.")
    classification: Classification = Field(description="Marca de clasificación U/C/S.")
    intl_designator: str = Field(description="Designador internacional, rstripped.")

    # --- Epoch ---
    epoch_year: int = Field(description="Año de la época (cuatro dígitos).")
    epoch_day: float = Field(description="Día del año con fracción decimal.")
    epoch_datetime: datetime = Field(
        description="Época como datetime UTC, derivada de (epoch_year, epoch_day)."
    )

    # --- Mean elements ---
    mean_motion_dot: float = Field(description="Primera derivada/2 [rev/día²].")
    mean_motion_ddot: float = Field(description="Segunda derivada/6 [rev/día³].")
    bstar: float = Field(description="Término de drag BSTAR [1/radio terrestre].")
    ephemeris_type: int = Field(description="Tipo de efemérides (típicamente 0).")
    element_set_number: int = Field(description="Número de element set del catálogo.")
    inclination_deg: float = Field(description="Inclinación [deg].")
    raan_deg: float = Field(description="Ascensión recta del nodo ascendente [deg].")
    eccentricity: float = Field(description="Eccentricidad (adimensional).")
    arg_perigee_deg: float = Field(description="Argumento del perigeo [deg].")
    mean_anomaly_deg: float = Field(description="Anomalía media [deg].")
    mean_motion: float = Field(description="Mean motion [rev/día].")
    rev_number: int = Field(description="Número de revolución en la época.")

    # --- Derivation context (versioning ADR-0010) ---
    schema_version: str = Field(
        default=ORBITAL_ELEMENTS_SCHEMA_VERSION,
        description="SemVer del esquema (ADR-0010).",
    )
    engine_version: str = Field(
        description="SemVer del normalizador que produjo esta fila (ADR-0010).",
    )
    derived_at: datetime = Field(description="UTC timestamp de la derivación.")


_ARROW_SCHEMA = pa.schema(
    [
        pa.field("content_hash_source", pa.string(), nullable=False),
        pa.field("tle_index", pa.int32(), nullable=False),
        pa.field("tle_content_hash", pa.string(), nullable=False),
        pa.field("object_name", pa.string(), nullable=True),
        pa.field("norad_cat_id", pa.int64(), nullable=False),
        pa.field("classification", pa.string(), nullable=False),
        pa.field("intl_designator", pa.string(), nullable=False),
        pa.field("epoch_year", pa.int32(), nullable=False),
        pa.field("epoch_day", pa.float64(), nullable=False),
        pa.field("epoch_datetime", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("mean_motion_dot", pa.float64(), nullable=False),
        pa.field("mean_motion_ddot", pa.float64(), nullable=False),
        pa.field("bstar", pa.float64(), nullable=False),
        pa.field("ephemeris_type", pa.int32(), nullable=False),
        pa.field("element_set_number", pa.int32(), nullable=False),
        pa.field("inclination_deg", pa.float64(), nullable=False),
        pa.field("raan_deg", pa.float64(), nullable=False),
        pa.field("eccentricity", pa.float64(), nullable=False),
        pa.field("arg_perigee_deg", pa.float64(), nullable=False),
        pa.field("mean_anomaly_deg", pa.float64(), nullable=False),
        pa.field("mean_motion", pa.float64(), nullable=False),
        pa.field("rev_number", pa.int64(), nullable=False),
        pa.field("schema_version", pa.string(), nullable=False),
        pa.field("engine_version", pa.string(), nullable=False),
        pa.field("derived_at", pa.timestamp("us", tz="UTC"), nullable=False),
    ]
)


class OrbitalElementsRepository:
    """Repositorio Parquet+DuckDB para ``orbital_elements``.

    Un archivo por ``(engine_version, content_hash_source)``: todas las filas
    derivadas de un mismo snapshot por una misma versión del normalizador
    viven en un único Parquet.

    Inserción
    ---------
    ``insert_many`` exige que todas las filas del batch compartan
    ``content_hash_source`` y ``engine_version``. La operación es **idempotente**:
    si el archivo ya existe, no se reescribe (ADR-0006 sin UPDATE). Devuelve
    el número de filas escritas (0 si no-op).

    Consulta
    --------
    Las queries usan DuckDB sobre el glob recursivo con ``hive_partitioning=false``:
    las columnas de partición (``engine_version=``) no contaminan el modelo,
    porque su valor ya vive explícitamente dentro del Parquet.
    """

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    # --- Escritura -------------------------------------------------------

    def insert_many(self, elements: Sequence[OrbitalElement]) -> int:
        if not elements:
            return 0
        first = elements[0]
        for el in elements[1:]:
            if el.content_hash_source != first.content_hash_source:
                raise OrbitalElementsError(
                    "insert_many requiere un único content_hash_source por batch"
                )
            if el.engine_version != first.engine_version:
                raise OrbitalElementsError(
                    "insert_many requiere un único engine_version por batch"
                )
        indices = [el.tle_index for el in elements]
        if len(set(indices)) != len(indices):
            raise OrbitalElementsError(
                "tle_index duplicado dentro del batch"
            )

        path = self._snapshot_path(
            engine_version=first.engine_version,
            content_hash_source=first.content_hash_source,
        )
        if path.exists():
            return 0
        path.parent.mkdir(parents=True, exist_ok=True)
        table = self._elements_to_arrow(elements)
        tmp = path.with_suffix(".tmp")
        pq.write_table(table, tmp, compression="zstd")
        tmp.replace(path)
        return len(elements)

    # --- Consulta --------------------------------------------------------

    def count(self) -> int:
        if not self._has_any_parquet():
            return 0
        with self._connect() as conn:
            result = conn.execute(
                f"SELECT COUNT(*) FROM read_parquet('{self._glob()}', hive_partitioning=false)"
            ).fetchone()
        return int(result[0]) if result else 0

    def get_by_snapshot(
        self,
        content_hash_source: str,
        *,
        engine_version: str | None = None,
    ) -> list[OrbitalElement]:
        """Devuelve los elementos de un snapshot, ordenados por ``tle_index``."""
        if not self._has_any_parquet():
            return []
        where = "WHERE content_hash_source = ?"
        params: list[object] = [content_hash_source]
        if engine_version is not None:
            where += " AND engine_version = ?"
            params.append(engine_version)
        with self._connect() as conn:
            arrow_table = conn.execute(
                f"""
                SELECT *
                FROM read_parquet('{self._glob()}', hive_partitioning=false)
                {where}
                ORDER BY tle_index
                """,
                params,
            ).to_arrow_table()
        return [OrbitalElement.model_validate(r) for r in arrow_table.to_pylist()]

    def find_latest_by_norad_id(
        self,
        norad_cat_id: int,
        *,
        engine_version: str | None = None,
    ) -> OrbitalElement | None:
        """Devuelve el ``OrbitalElement`` con mayor ``epoch_datetime`` para un NORAD ID.

        Si hay múltiples ``engine_version`` y no se especifica, se selecciona el
        de SemVer más alto a igualdad de epoch. Devuelve ``None`` si no existe
        ninguna fila para ese NORAD ID.
        """
        if not self._has_any_parquet():
            return None
        where = "WHERE norad_cat_id = ?"
        params: list[object] = [norad_cat_id]
        if engine_version is not None:
            where += " AND engine_version = ?"
            params.append(engine_version)
        with self._connect() as conn:
            arrow_table = conn.execute(
                f"""
                SELECT *
                FROM read_parquet('{self._glob()}', hive_partitioning=false)
                {where}
                ORDER BY epoch_datetime DESC, engine_version DESC
                LIMIT 1
                """,
                params,
            ).to_arrow_table()
        if len(arrow_table) == 0:
            return None
        return OrbitalElement.model_validate(arrow_table.to_pylist()[0])

    def find_all_by_norad_id(
        self,
        norad_cat_id: int,
        *,
        engine_version: str | None = None,
    ) -> list[OrbitalElement]:
        """Devuelve todos los ``OrbitalElement`` de un NORAD ID.

        Ordenados por ``epoch_datetime`` ascendente (secuencia física,
        no orden de ingestión).

        Si ``engine_version`` se especifica, filtra por esa versión. Sin
        filtrar, mezcla versiones — el caller (ej. detector de maniobras)
        debe declarar esa elección en sus honesty fields. ADR-0027.
        """
        if not self._has_any_parquet():
            return []
        where = "WHERE norad_cat_id = ?"
        params: list[object] = [norad_cat_id]
        if engine_version is not None:
            where += " AND engine_version = ?"
            params.append(engine_version)
        with self._connect() as conn:
            arrow_table = conn.execute(
                f"""
                SELECT *
                FROM read_parquet('{self._glob()}', hive_partitioning=false)
                {where}
                ORDER BY epoch_datetime ASC, engine_version ASC
                """,
                params,
            ).to_arrow_table()
        return [OrbitalElement.model_validate(r) for r in arrow_table.to_pylist()]

    def iter_all(self) -> Iterator[OrbitalElement]:
        if not self._has_any_parquet():
            return
        with self._connect() as conn:
            arrow_table = conn.execute(
                f"SELECT * FROM read_parquet('{self._glob()}', hive_partitioning=false)"
            ).to_arrow_table()
        for record in arrow_table.to_pylist():
            yield OrbitalElement.model_validate(record)

    def engine_versions_for(self, content_hash_source: str) -> list[str]:
        """Devuelve las ``engine_version`` distintas que han derivado un snapshot."""
        if not self._has_any_parquet():
            return []
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT DISTINCT engine_version
                FROM read_parquet('{self._glob()}', hive_partitioning=false)
                WHERE content_hash_source = ?
                ORDER BY engine_version
                """,
                [content_hash_source],
            ).fetchall()
        return [str(r[0]) for r in rows]

    # --- Internos --------------------------------------------------------

    def _snapshot_path(self, *, engine_version: str, content_hash_source: str) -> Path:
        return (
            self.root
            / f"engine_version={engine_version}"
            / f"source_{content_hash_source[:2]}"
            / f"snap_{content_hash_source}.parquet"
        )

    def _glob(self) -> str:
        return str(self.root / "**" / "*.parquet").replace("\\", "/")

    def _has_any_parquet(self) -> bool:
        return any(self.root.rglob("*.parquet"))

    def _connect(self) -> duckdb.DuckDBPyConnection:
        conn = duckdb.connect(database=":memory:")
        conn.execute("SET TimeZone='UTC'")
        return conn

    def _elements_to_arrow(self, elements: Iterable[OrbitalElement]) -> pa.Table:
        rows = list(elements)
        return pa.table(
            {
                "content_hash_source": [el.content_hash_source for el in rows],
                "tle_index": [el.tle_index for el in rows],
                "tle_content_hash": [el.tle_content_hash for el in rows],
                "object_name": [el.object_name for el in rows],
                "norad_cat_id": [el.norad_cat_id for el in rows],
                "classification": [el.classification for el in rows],
                "intl_designator": [el.intl_designator for el in rows],
                "epoch_year": [el.epoch_year for el in rows],
                "epoch_day": [el.epoch_day for el in rows],
                "epoch_datetime": [el.epoch_datetime for el in rows],
                "mean_motion_dot": [el.mean_motion_dot for el in rows],
                "mean_motion_ddot": [el.mean_motion_ddot for el in rows],
                "bstar": [el.bstar for el in rows],
                "ephemeris_type": [el.ephemeris_type for el in rows],
                "element_set_number": [el.element_set_number for el in rows],
                "inclination_deg": [el.inclination_deg for el in rows],
                "raan_deg": [el.raan_deg for el in rows],
                "eccentricity": [el.eccentricity for el in rows],
                "arg_perigee_deg": [el.arg_perigee_deg for el in rows],
                "mean_anomaly_deg": [el.mean_anomaly_deg for el in rows],
                "mean_motion": [el.mean_motion for el in rows],
                "rev_number": [el.rev_number for el in rows],
                "schema_version": [el.schema_version for el in rows],
                "engine_version": [el.engine_version for el in rows],
                "derived_at": [el.derived_at for el in rows],
            },
            schema=_ARROW_SCHEMA,
        )
