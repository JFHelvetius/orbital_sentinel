"""Persistencia de detecciones de conjunción (ADR-0019 v0.4).

Primera tabla Derived persistente del proyecto. Hasta este ADR, todos los
productos Derived (Ephemeris, ConjunctionAnalysis) han sido on-demand.

Identidad: SHA-256 content-addressable sobre ``(sorted_tle_hashes, window,
step, engine_version)``. Idempotente por construcción.

Storage: Parquet bajo ``data/derived/conjunctions/`` particionado por
``persisted_at`` (year/month). Mismo patrón que ``tle_snapshots``.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Iterator
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from orbital_sentinel.analytics.conjunctions.analysis import ConjunctionAnalysis
from orbital_sentinel.catalog.tle_snapshots import TLESnapshotsRepository
from orbital_sentinel.core.errors import OrbitalSentinelError

PERSISTED_CONJUNCTION_SCHEMA_VERSION = "0.3.0"
"""SemVer del esquema persistido.

v0.1.0 (ADR-0019): primer esquema persistido.
v0.2.0 (ADR-0020): añade 7 campos de Pc + covarianza declarada.
v0.3.0 (ADR-0044): añade anotación co-orbiting (2 campos). detection_content_hash
    NO cambia (engine_version se mantiene en 0.3.0).
"""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ConjunctionDetectionError(OrbitalSentinelError):
    """Error operando el repositorio de detecciones."""


def compute_detection_hash(analysis: ConjunctionAnalysis) -> str:
    """SHA-256 content-addressable para una ``ConjunctionAnalysis``.

    Canónico (sorted TLE hashes). Determinístico. Incluye versión del motor.
    NO incluye derived_at ni outputs.

    Garantía: misma entrada → mismo hash. Re-correr la misma screening produce
    el mismo hash → idempotencia.
    """
    pair = sorted(
        [
            analysis.element_a_tle_content_hash,
            analysis.element_b_tle_content_hash,
        ]
    )
    canonical = "|".join(
        [
            pair[0],
            pair[1],
            analysis.window_start.isoformat(),
            analysis.window_end.isoformat(),
            f"{analysis.step_minutes:.6f}",
            analysis.engine_version,
        ]
    )
    return hashlib.sha256(canonical.encode("ascii")).hexdigest()


class ConjunctionDetection(BaseModel):
    """Una fila persistida en la tabla ``conjunctions`` (ADR-0019).

    Es una ``ConjunctionAnalysis`` materializada con metadata de persistencia
    añadida. Flat schema para queries DuckDB directas.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    # --- Identidad persistida ---
    detection_content_hash: str = Field(
        description="SHA-256 PK content-addressable (compute_detection_hash)."
    )

    # --- Identidad de objetos (copiada de ConjunctionAnalysis) ---
    norad_a: int
    norad_b: int
    element_a_content_hash_source: str
    element_a_tle_index: int
    element_a_tle_content_hash: str
    element_b_content_hash_source: str
    element_b_tle_index: int
    element_b_tle_content_hash: str

    # --- Ventana y resultado ---
    window_start: AwareDatetime
    window_end: AwareDatetime
    step_minutes: float
    n_samples: int
    tca: AwareDatetime
    miss_distance_km: float
    relative_velocity_km_s: float
    minutes_from_epoch_a_at_tca: float
    minutes_from_epoch_b_at_tca: float

    # --- Honestidad declarada ---
    sgp4_uncertainty_baseline_km: float
    sgp4_uncertainty_growth_km_per_day: float
    tca_resolution_minutes: float
    tca_was_refined: bool

    # --- Pc y covarianza declarada (ADR-0020 v1.0) ---
    pc: float
    combined_hard_body_radius_km: float
    covariance_model_name: str
    covariance_baseline_sigma_km: float
    covariance_growth_sigma_km_per_day: float
    combined_sigma_at_tca_km: float
    pc_method: str

    # --- Anotación co-orbiting (ADR-0044) ---
    co_orbiting_velocity_threshold_km_s: float = Field(
        default=0.0,
        description="Umbral declarado de velocidad relativa (ADR-0044).",
    )
    is_apparent_co_orbiting: bool = Field(
        default=False,
        description="Co-movimiento (acoplado/co-orbitando), no colisión (ADR-0044).",
    )

    # --- Versioning del análisis original ---
    analysis_schema_version: str
    analysis_engine_version: str
    analysis_derived_at: AwareDatetime

    # --- Metadata de persistencia ---
    persistence_schema_version: str = Field(
        default=PERSISTED_CONJUNCTION_SCHEMA_VERSION
    )
    persisted_at: AwareDatetime

    @classmethod
    def from_analysis(
        cls,
        analysis: ConjunctionAnalysis,
        *,
        persisted_at: datetime,
    ) -> ConjunctionDetection:
        """Construye una detection persistible desde un análisis."""
        return cls(
            detection_content_hash=compute_detection_hash(analysis),
            norad_a=analysis.norad_a,
            norad_b=analysis.norad_b,
            element_a_content_hash_source=analysis.element_a_content_hash_source,
            element_a_tle_index=analysis.element_a_tle_index,
            element_a_tle_content_hash=analysis.element_a_tle_content_hash,
            element_b_content_hash_source=analysis.element_b_content_hash_source,
            element_b_tle_index=analysis.element_b_tle_index,
            element_b_tle_content_hash=analysis.element_b_tle_content_hash,
            window_start=analysis.window_start,
            window_end=analysis.window_end,
            step_minutes=analysis.step_minutes,
            n_samples=analysis.n_samples,
            tca=analysis.tca,
            miss_distance_km=analysis.miss_distance_km,
            relative_velocity_km_s=analysis.relative_velocity_km_s,
            minutes_from_epoch_a_at_tca=analysis.minutes_from_epoch_a_at_tca,
            minutes_from_epoch_b_at_tca=analysis.minutes_from_epoch_b_at_tca,
            sgp4_uncertainty_baseline_km=analysis.sgp4_uncertainty_baseline_km,
            sgp4_uncertainty_growth_km_per_day=analysis.sgp4_uncertainty_growth_km_per_day,
            tca_resolution_minutes=analysis.tca_resolution_minutes,
            tca_was_refined=analysis.tca_was_refined,
            pc=analysis.pc,
            combined_hard_body_radius_km=analysis.combined_hard_body_radius_km,
            covariance_model_name=analysis.covariance_model_name,
            covariance_baseline_sigma_km=analysis.covariance_baseline_sigma_km,
            covariance_growth_sigma_km_per_day=analysis.covariance_growth_sigma_km_per_day,
            combined_sigma_at_tca_km=analysis.combined_sigma_at_tca_km,
            pc_method=analysis.pc_method,
            co_orbiting_velocity_threshold_km_s=analysis.co_orbiting_velocity_threshold_km_s,
            is_apparent_co_orbiting=analysis.is_apparent_co_orbiting,
            analysis_schema_version=analysis.schema_version,
            analysis_engine_version=analysis.engine_version,
            analysis_derived_at=analysis.derived_at,
            persisted_at=persisted_at.astimezone(timezone.utc),
        )


_ARROW_SCHEMA = pa.schema(
    [
        pa.field("detection_content_hash", pa.string(), nullable=False),
        pa.field("norad_a", pa.int64(), nullable=False),
        pa.field("norad_b", pa.int64(), nullable=False),
        pa.field("element_a_content_hash_source", pa.string(), nullable=False),
        pa.field("element_a_tle_index", pa.int32(), nullable=False),
        pa.field("element_a_tle_content_hash", pa.string(), nullable=False),
        pa.field("element_b_content_hash_source", pa.string(), nullable=False),
        pa.field("element_b_tle_index", pa.int32(), nullable=False),
        pa.field("element_b_tle_content_hash", pa.string(), nullable=False),
        pa.field("window_start", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("window_end", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("step_minutes", pa.float64(), nullable=False),
        pa.field("n_samples", pa.int64(), nullable=False),
        pa.field("tca", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("miss_distance_km", pa.float64(), nullable=False),
        pa.field("relative_velocity_km_s", pa.float64(), nullable=False),
        pa.field("minutes_from_epoch_a_at_tca", pa.float64(), nullable=False),
        pa.field("minutes_from_epoch_b_at_tca", pa.float64(), nullable=False),
        pa.field("sgp4_uncertainty_baseline_km", pa.float64(), nullable=False),
        pa.field("sgp4_uncertainty_growth_km_per_day", pa.float64(), nullable=False),
        pa.field("tca_resolution_minutes", pa.float64(), nullable=False),
        pa.field("tca_was_refined", pa.bool_(), nullable=False),
        pa.field("pc", pa.float64(), nullable=False),
        pa.field("combined_hard_body_radius_km", pa.float64(), nullable=False),
        pa.field("covariance_model_name", pa.string(), nullable=False),
        pa.field("covariance_baseline_sigma_km", pa.float64(), nullable=False),
        pa.field("covariance_growth_sigma_km_per_day", pa.float64(), nullable=False),
        pa.field("combined_sigma_at_tca_km", pa.float64(), nullable=False),
        pa.field("pc_method", pa.string(), nullable=False),
        pa.field("co_orbiting_velocity_threshold_km_s", pa.float64(), nullable=False),
        pa.field("is_apparent_co_orbiting", pa.bool_(), nullable=False),
        pa.field("analysis_schema_version", pa.string(), nullable=False),
        pa.field("analysis_engine_version", pa.string(), nullable=False),
        pa.field("analysis_derived_at", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("persistence_schema_version", pa.string(), nullable=False),
        pa.field("persisted_at", pa.timestamp("us", tz="UTC"), nullable=False),
    ]
)


class ConjunctionDetectionsRepository:
    """Repositorio Parquet/DuckDB de detecciones persistidas (ADR-0019).

    Layout::

        root/
            year=YYYY/
                month=MM/
                    det_<detection_content_hash>.parquet  (1 fila por archivo)

    Idempotente por content_hash. ADR-0006 sin UPDATE.
    """

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    # --- Escritura ----------------------------------------------------------

    def insert(self, detection: ConjunctionDetection) -> bool:
        """Inserta. Devuelve ``True`` si nuevo, ``False`` si ya existía."""
        path = self._path(detection)
        if path.exists():
            return False
        path.parent.mkdir(parents=True, exist_ok=True)
        table = self._to_arrow([detection])
        tmp = path.with_suffix(".tmp")
        pq.write_table(table, tmp, compression="zstd")
        tmp.replace(path)
        return True

    def insert_many(self, detections: Iterable[ConjunctionDetection]) -> int:
        """Inserta cada detection. Devuelve cuántas se escribieron."""
        written = 0
        for d in detections:
            if self.insert(d):
                written += 1
        return written

    # --- Consulta -----------------------------------------------------------

    def count(self) -> int:
        if not self._has_any_parquet():
            return 0
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT COUNT(*) FROM read_parquet('{self._glob()}', hive_partitioning=false)"
            ).fetchone()
        return int(row[0]) if row else 0

    def get(self, detection_content_hash: str) -> ConjunctionDetection | None:
        if not self._has_any_parquet():
            return None
        with self._connect() as conn:
            arrow_table = conn.execute(
                f"""
                SELECT *
                FROM read_parquet('{self._glob()}', hive_partitioning=false)
                WHERE detection_content_hash = ?
                LIMIT 1
                """,
                [detection_content_hash],
            ).to_arrow_table()
        if len(arrow_table) == 0:
            return None
        return ConjunctionDetection.model_validate(arrow_table.to_pylist()[0])

    def iter_all(self) -> Iterator[ConjunctionDetection]:
        if not self._has_any_parquet():
            return
        with self._connect() as conn:
            arrow_table = conn.execute(
                f"SELECT * FROM read_parquet('{self._glob()}', hive_partitioning=false)"
            ).to_arrow_table()
        for record in arrow_table.to_pylist():
            yield ConjunctionDetection.model_validate(record)

    def find_by_norad(
        self,
        norad_cat_id: int,
        *,
        limit: int | None = None,
    ) -> list[ConjunctionDetection]:
        """Devuelve detecciones que involucran ``norad_cat_id`` (lado A o B).

        Ordenadas por ``miss_distance_km`` ascendente.
        """
        if not self._has_any_parquet():
            return []
        sql = f"""
            SELECT *
            FROM read_parquet('{self._glob()}', hive_partitioning=false)
            WHERE norad_a = ? OR norad_b = ?
            ORDER BY miss_distance_km
        """
        if limit is not None:
            sql += f"\n            LIMIT {int(limit)}"
        with self._connect() as conn:
            arrow_table = conn.execute(
                sql, [norad_cat_id, norad_cat_id]
            ).to_arrow_table()
        return [
            ConjunctionDetection.model_validate(r)
            for r in arrow_table.to_pylist()
        ]

    # --- Internos -----------------------------------------------------------

    def _path(self, detection: ConjunctionDetection) -> Path:
        ts = detection.persisted_at.astimezone(timezone.utc)
        return (
            self.root
            / f"year={ts.year}"
            / f"month={ts.month:02d}"
            / f"det_{detection.detection_content_hash}.parquet"
        )

    def _glob(self) -> str:
        return str(self.root / "**" / "*.parquet").replace("\\", "/")

    def _has_any_parquet(self) -> bool:
        return any(self.root.rglob("*.parquet"))

    def _connect(self) -> duckdb.DuckDBPyConnection:
        conn = duckdb.connect(database=":memory:")
        conn.execute("SET TimeZone='UTC'")
        return conn

    def _to_arrow(self, detections: Iterable[ConjunctionDetection]) -> pa.Table:
        rows = list(detections)
        return pa.table(
            {
                "detection_content_hash": [d.detection_content_hash for d in rows],
                "norad_a": [d.norad_a for d in rows],
                "norad_b": [d.norad_b for d in rows],
                "element_a_content_hash_source": [d.element_a_content_hash_source for d in rows],
                "element_a_tle_index": [d.element_a_tle_index for d in rows],
                "element_a_tle_content_hash": [d.element_a_tle_content_hash for d in rows],
                "element_b_content_hash_source": [d.element_b_content_hash_source for d in rows],
                "element_b_tle_index": [d.element_b_tle_index for d in rows],
                "element_b_tle_content_hash": [d.element_b_tle_content_hash for d in rows],
                "window_start": [d.window_start for d in rows],
                "window_end": [d.window_end for d in rows],
                "step_minutes": [d.step_minutes for d in rows],
                "n_samples": [d.n_samples for d in rows],
                "tca": [d.tca for d in rows],
                "miss_distance_km": [d.miss_distance_km for d in rows],
                "relative_velocity_km_s": [d.relative_velocity_km_s for d in rows],
                "minutes_from_epoch_a_at_tca": [d.minutes_from_epoch_a_at_tca for d in rows],
                "minutes_from_epoch_b_at_tca": [d.minutes_from_epoch_b_at_tca for d in rows],
                "sgp4_uncertainty_baseline_km": [d.sgp4_uncertainty_baseline_km for d in rows],
                "sgp4_uncertainty_growth_km_per_day": [
                    d.sgp4_uncertainty_growth_km_per_day for d in rows
                ],
                "tca_resolution_minutes": [d.tca_resolution_minutes for d in rows],
                "tca_was_refined": [d.tca_was_refined for d in rows],
                "pc": [d.pc for d in rows],
                "combined_hard_body_radius_km": [d.combined_hard_body_radius_km for d in rows],
                "covariance_model_name": [d.covariance_model_name for d in rows],
                "covariance_baseline_sigma_km": [d.covariance_baseline_sigma_km for d in rows],
                "covariance_growth_sigma_km_per_day": [
                    d.covariance_growth_sigma_km_per_day for d in rows
                ],
                "combined_sigma_at_tca_km": [d.combined_sigma_at_tca_km for d in rows],
                "pc_method": [d.pc_method for d in rows],
                "co_orbiting_velocity_threshold_km_s": [
                    d.co_orbiting_velocity_threshold_km_s for d in rows
                ],
                "is_apparent_co_orbiting": [d.is_apparent_co_orbiting for d in rows],
                "analysis_schema_version": [d.analysis_schema_version for d in rows],
                "analysis_engine_version": [d.analysis_engine_version for d in rows],
                "analysis_derived_at": [d.analysis_derived_at for d in rows],
                "persistence_schema_version": [d.persistence_schema_version for d in rows],
                "persisted_at": [d.persisted_at for d in rows],
            },
            schema=_ARROW_SCHEMA,
        )


# --- Integridad cross-layer Raw → Detection ------------------------------


class DetectionOrphan(BaseModel):
    """Una detection con referencia rota a la capa Raw."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    detection_content_hash: str
    missing_side: str  # "a" o "b"
    missing_content_hash_source: str


class DetectionsIntegrityReport(BaseModel):
    """Resultado de ``verify_detections_integrity``."""

    model_config = ConfigDict(extra="forbid")

    orphan_detections: list[DetectionOrphan] = Field(default_factory=list)
    n_detections_checked: int = 0

    @property
    def has_violations(self) -> bool:
        return bool(self.orphan_detections)


def verify_detections_integrity(
    snapshots: TLESnapshotsRepository,
    detections: ConjunctionDetectionsRepository,
) -> DetectionsIntegrityReport:
    """Verifica que cada detection referencia ``tle_snapshots`` existentes.

    Para cada detection, comprueba ``element_a_content_hash_source`` y
    ``element_b_content_hash_source`` contra Raw. Si falta, ``DetectionOrphan``.

    No comprueba contra Normalized porque Normalized es regenerable desde Raw
    (ADR-0006). Verificar Raw es suficiente para la trazabilidad real.
    """
    raw_hashes = {s.content_hash for s in snapshots.iter_all()}
    orphans: list[DetectionOrphan] = []
    n_checked = 0
    for det in detections.iter_all():
        n_checked += 1
        if det.element_a_content_hash_source not in raw_hashes:
            orphans.append(
                DetectionOrphan(
                    detection_content_hash=det.detection_content_hash,
                    missing_side="a",
                    missing_content_hash_source=det.element_a_content_hash_source,
                )
            )
        if det.element_b_content_hash_source not in raw_hashes:
            orphans.append(
                DetectionOrphan(
                    detection_content_hash=det.detection_content_hash,
                    missing_side="b",
                    missing_content_hash_source=det.element_b_content_hash_source,
                )
            )
    return DetectionsIntegrityReport(
        orphan_detections=orphans,
        n_detections_checked=n_checked,
    )
