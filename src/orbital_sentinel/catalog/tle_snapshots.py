"""``tle_snapshots``: primera tabla de la capa Raw (ADR-0006).

Cada fila representa un snapshot de bytes descargado de una fuente, identificado
por su ``content_hash``. La tabla es **append-only** y **content-addressable**:
dos descargas con bytes idénticos producen el mismo hash y se deduplican.

Storage (ADR-0004):

* Parquet como formato canónico en disco.
* Particionamiento por año/mes en directorios estilo Hive (``year=YYYY/month=MM/``).
* Una fila por archivo (``snap_<content_hash>.parquet``). Estrategia naive pero
  parallel-safe y trivial de auditar.
* DuckDB como motor de consulta sobre el glob recursivo.

Schema versionado (ADR-0010): la constante :data:`TLE_SNAPSHOTS_SCHEMA_VERSION`
se persiste en cada fila para que migraciones futuras puedan razonar sobre
compatibilidad.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
from pydantic import BaseModel, ConfigDict, Field

from orbital_sentinel.core.errors import OrbitalSentinelError

TLE_SNAPSHOTS_SCHEMA_VERSION = "0.1.0"
"""Versión SemVer del esquema (ADR-0010)."""


class CatalogError(OrbitalSentinelError):
    """Error operando el catálogo."""


class TLESnapshot(BaseModel):
    """Una fila de ``tle_snapshots``.

    Identidad por ``content_hash``. ``fetched_at`` marca cuándo se observó por
    primera vez este contenido bit-idéntico.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    content_hash: str = Field(description="SHA-256 hex de los bytes recibidos.")
    source: str = Field(description="Nombre de la fuente, e.g. 'celestrak'.")
    dataset: str = Field(description="Identificador del dataset dentro de la fuente.")
    url: str = Field(description="URL canónica de origen.")
    fetched_at: datetime = Field(description="UTC timestamp del primer fetch.")
    raw_text: str = Field(description="Texto crudo (decodificado ASCII).")
    n_bytes: int = Field(description="Tamaño en bytes del payload original.")
    schema_version: str = Field(
        default=TLE_SNAPSHOTS_SCHEMA_VERSION,
        description="Versión SemVer del esquema (ADR-0010).",
    )


_ARROW_SCHEMA = pa.schema(
    [
        pa.field("content_hash", pa.string(), nullable=False),
        pa.field("source", pa.string(), nullable=False),
        pa.field("dataset", pa.string(), nullable=False),
        pa.field("url", pa.string(), nullable=False),
        pa.field("fetched_at", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("raw_text", pa.string(), nullable=False),
        pa.field("n_bytes", pa.int64(), nullable=False),
        pa.field("schema_version", pa.string(), nullable=False),
    ]
)


class TLESnapshotsRepository:
    """Repositorio Parquet+DuckDB para ``tle_snapshots``.

    Inserción: una fila por archivo Parquet bajo
    ``root/year=YYYY/month=MM/snap_<content_hash>.parquet``. Inserciones con un
    ``content_hash`` ya presente son no-ops (idempotencia content-addressable).

    Lectura: ``read_parquet`` recursivo via DuckDB. Si no hay archivos, las
    consultas devuelven el equivalente a un resultado vacío.
    """

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    # --- Escritura -------------------------------------------------------

    def insert(self, snapshot: TLESnapshot) -> bool:
        """Inserta un snapshot. Devuelve True si se escribió, False si ya existía."""
        path = self._snapshot_path(snapshot)
        if path.exists():
            return False
        path.parent.mkdir(parents=True, exist_ok=True)
        table = self._snapshot_to_arrow(snapshot)
        tmp = path.with_suffix(".tmp")
        pq.write_table(table, tmp, compression="zstd")
        tmp.replace(path)
        return True

    # --- Consulta --------------------------------------------------------

    def get(self, content_hash: str) -> TLESnapshot | None:
        if not self._has_any_parquet():
            return None
        with self._connect() as conn:
            arrow_table = conn.execute(
                f"""
                SELECT *
                FROM read_parquet('{self._glob()}', hive_partitioning=false)
                WHERE content_hash = ?
                LIMIT 1
                """,
                [content_hash],
            ).to_arrow_table()
        if len(arrow_table) == 0:
            return None
        return TLESnapshot.model_validate(arrow_table.to_pylist()[0])

    def count(self) -> int:
        if not self._has_any_parquet():
            return 0
        with self._connect() as conn:
            result = conn.execute(
                f"SELECT COUNT(*) FROM read_parquet('{self._glob()}', hive_partitioning=false)"
            ).fetchone()
        return int(result[0]) if result else 0

    def iter_all(self) -> Iterator[TLESnapshot]:
        if not self._has_any_parquet():
            return
        with self._connect() as conn:
            arrow_table = conn.execute(
                f"SELECT * FROM read_parquet('{self._glob()}', hive_partitioning=false)"
            ).to_arrow_table()
        for record in arrow_table.to_pylist():
            yield TLESnapshot.model_validate(record)

    # --- Internos --------------------------------------------------------

    def _snapshot_path(self, snapshot: TLESnapshot) -> Path:
        ts = snapshot.fetched_at.astimezone(timezone.utc)
        return (
            self.root
            / f"year={ts.year}"
            / f"month={ts.month:02d}"
            / f"snap_{snapshot.content_hash}.parquet"
        )

    def _glob(self) -> str:
        # DuckDB acepta globs con '/'; normalizamos para Windows.
        return str(self.root / "**" / "*.parquet").replace("\\", "/")

    def _has_any_parquet(self) -> bool:
        return any(self.root.rglob("*.parquet"))

    def _connect(self) -> duckdb.DuckDBPyConnection:
        conn = duckdb.connect(database=":memory:")
        # Forzar UTC en la sesión: evita que DuckDB consulte la TZ del sistema
        # operativo, lo que requiere tzdata IANA disponible (no garantizado en
        # Windows). Coherente con ADR-0013: el régimen de reproducibilidad
        # opera en UTC declarado.
        conn.execute("SET TimeZone='UTC'")
        return conn

    def _snapshot_to_arrow(self, snapshot: TLESnapshot) -> pa.Table:
        return pa.table(
            {
                "content_hash": [snapshot.content_hash],
                "source": [snapshot.source],
                "dataset": [snapshot.dataset],
                "url": [snapshot.url],
                "fetched_at": [snapshot.fetched_at],
                "raw_text": [snapshot.raw_text],
                "n_bytes": [snapshot.n_bytes],
                "schema_version": [snapshot.schema_version],
            },
            schema=_ARROW_SCHEMA,
        )
