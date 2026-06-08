"""Benchmark de concurrencia Parquet+DuckDB sobre la capa Raw.

Una sola pregunta arquitectónica: ¿el patrón actual mantiene throughput
aceptable y consistencia de lectura bajo concurrencia representativa de Fase 2?

Acotaciones de scope (deliberadas):
- Solo capa Raw (``tle_snapshots``). Normalized usa el mismo patrón pyarrow+
  filesystem; sus números son proporcionales.
- Solo threading (no multiprocessing). El cuello que importa es I/O y locks de
  filesystem, no GIL.
- Workload sintético, no TLEs reales. Estamos midiendo el subsistema de
  almacenamiento, no el parser ni el normalizador.
- No exploramos compresión, mem profile, ni distintas versiones de DuckDB.
- Sin red.

Ejecución::

    .venv\\Scripts\\python.exe benchmarks\\duckdb_concurrency\\runner.py
"""

from __future__ import annotations

import hashlib
import json
import platform
import statistics
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import pyarrow

from orbital_sentinel import __version__ as os_version
from orbital_sentinel.catalog import TLESnapshot, TLESnapshotsRepository

# --- Parámetros ----------------------------------------------------------

N_SNAPSHOTS_PER_SCENARIO = 200
WORKER_COUNTS_CONCURRENT = (2, 4, 8)
SNAPSHOT_PAYLOAD_TEMPLATE = (
    "1 25544U 98067A   08264.51782528 -.00002182  00000-0 -11606-4 0  2927\n"
    "2 25544  51.6416 247.4627 0006703 130.5360 325.0288 15.72125391563537\n"
) * 5  # ~700 bytes, tamaño realista de un GP TLE multi-objeto


@dataclass
class ScenarioResult:
    name: str
    n_writers: int
    n_readers: int
    n_snapshots: int
    elapsed_sec: float
    throughput_inserts_per_sec: float
    successes: int
    failures: int
    final_row_count: int
    integrity_ok: bool
    reader_query_count: int = 0
    reader_query_latency_ms_p50: float | None = None
    reader_query_latency_ms_p95: float | None = None
    reader_query_latency_ms_max: float | None = None
    notes: str = ""


def make_synthetic_snapshot(seq: int) -> TLESnapshot:
    """Snapshot determinístico y único por ``seq``."""
    payload = f"# benchmark seq={seq}\n" + SNAPSHOT_PAYLOAD_TEMPLATE
    encoded = payload.encode("ascii")
    # content_hash sintético derivado del seq (no del payload), no nos importa
    # la consistencia con raw_text para este benchmark: medimos storage, no parsing.
    return TLESnapshot(
        content_hash=hashlib.sha256(f"benchmark-snapshot-{seq}".encode()).hexdigest(),
        source="benchmark",
        dataset=f"synthetic-{seq:06d}",
        url=f"benchmark://synthetic/{seq}",
        fetched_at=datetime(2026, 6, 3, 12, 0, tzinfo=timezone.utc),
        raw_text=payload,
        n_bytes=len(encoded),
    )


def _check_integrity(repo: TLESnapshotsRepository, expected: int) -> tuple[int, bool]:
    """Cuenta filas y verifica que todas las inserciones quedaron persistidas."""
    actual = repo.count()
    return actual, actual == expected


def scenario_single_writer(
    repo: TLESnapshotsRepository, snapshots: list[TLESnapshot]
) -> ScenarioResult:
    """Baseline: un solo escritor secuencial."""
    failures = 0
    start = time.perf_counter()
    for s in snapshots:
        try:
            repo.insert(s)
        except Exception:  # noqa: BLE001
            failures += 1
    elapsed = time.perf_counter() - start

    successes = len(snapshots) - failures
    final, ok = _check_integrity(repo, successes)
    return ScenarioResult(
        name="single_writer",
        n_writers=1,
        n_readers=0,
        n_snapshots=len(snapshots),
        elapsed_sec=elapsed,
        throughput_inserts_per_sec=successes / elapsed if elapsed > 0 else 0.0,
        successes=successes,
        failures=failures,
        final_row_count=final,
        integrity_ok=ok,
    )


def scenario_concurrent_writers(
    repo: TLESnapshotsRepository,
    snapshots: list[TLESnapshot],
    n_workers: int,
) -> ScenarioResult:
    """N workers escriben snapshots distintos al mismo directorio."""

    def worker(s: TLESnapshot) -> bool:
        try:
            repo.insert(s)
            return True
        except Exception:  # noqa: BLE001
            return False

    start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=n_workers) as ex:
        results = list(ex.map(worker, snapshots))
    elapsed = time.perf_counter() - start

    successes = sum(results)
    failures = len(results) - successes
    final, ok = _check_integrity(repo, successes)
    return ScenarioResult(
        name=f"concurrent_writers_{n_workers}",
        n_writers=n_workers,
        n_readers=0,
        n_snapshots=len(snapshots),
        elapsed_sec=elapsed,
        throughput_inserts_per_sec=successes / elapsed if elapsed > 0 else 0.0,
        successes=successes,
        failures=failures,
        final_row_count=final,
        integrity_ok=ok,
    )


def scenario_reader_during_writes(
    repo: TLESnapshotsRepository,
    snapshots: list[TLESnapshot],
    n_writers: int,
) -> ScenarioResult:
    """Reader hace ``count()`` en bucle mientras N writers insertan."""
    reader_latencies_ms: list[float] = []
    reader_failures = 0
    stop = threading.Event()

    def reader() -> None:
        nonlocal reader_failures
        while not stop.is_set():
            t0 = time.perf_counter()
            try:
                repo.count()
            except Exception:  # noqa: BLE001
                reader_failures += 1
            reader_latencies_ms.append((time.perf_counter() - t0) * 1000)

    def writer(s: TLESnapshot) -> bool:
        try:
            repo.insert(s)
            return True
        except Exception:  # noqa: BLE001
            return False

    reader_thread = threading.Thread(target=reader, daemon=True)
    reader_thread.start()

    start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=n_writers) as ex:
        results = list(ex.map(writer, snapshots))
    elapsed = time.perf_counter() - start

    stop.set()
    reader_thread.join(timeout=5.0)

    successes = sum(results)
    failures = len(results) - successes
    final, ok = _check_integrity(repo, successes)

    sorted_lat = sorted(reader_latencies_ms)
    p50 = statistics.median(sorted_lat) if sorted_lat else None
    p95 = sorted_lat[int(len(sorted_lat) * 0.95)] if len(sorted_lat) >= 20 else None
    return ScenarioResult(
        name=f"reader_with_{n_writers}_writers",
        n_writers=n_writers,
        n_readers=1,
        n_snapshots=len(snapshots),
        elapsed_sec=elapsed,
        throughput_inserts_per_sec=successes / elapsed if elapsed > 0 else 0.0,
        successes=successes,
        failures=failures,
        final_row_count=final,
        integrity_ok=ok,
        reader_query_count=len(reader_latencies_ms),
        reader_query_latency_ms_p50=p50,
        reader_query_latency_ms_p95=p95,
        reader_query_latency_ms_max=max(reader_latencies_ms) if reader_latencies_ms else None,
        notes=f"reader_failures={reader_failures}",
    )


def run_all() -> dict:
    results: list[ScenarioResult] = []

    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)

        # 1. baseline
        snaps = [make_synthetic_snapshot(i) for i in range(N_SNAPSHOTS_PER_SCENARIO)]
        results.append(
            scenario_single_writer(TLESnapshotsRepository(base / "baseline"), snaps)
        )

        # 2-4. concurrent writers
        for k in WORKER_COUNTS_CONCURRENT:
            snaps = [
                make_synthetic_snapshot(i + 1_000_000 * k)
                for i in range(N_SNAPSHOTS_PER_SCENARIO)
            ]
            results.append(
                scenario_concurrent_writers(
                    TLESnapshotsRepository(base / f"writers_{k}"), snaps, k
                )
            )

        # 5. reader + 1 writer
        snaps = [
            make_synthetic_snapshot(i + 7_000_000) for i in range(N_SNAPSHOTS_PER_SCENARIO)
        ]
        results.append(
            scenario_reader_during_writes(
                TLESnapshotsRepository(base / "reader_1w"), snaps, 1
            )
        )

        # 6. reader + 4 writers
        snaps = [
            make_synthetic_snapshot(i + 8_000_000) for i in range(N_SNAPSHOTS_PER_SCENARIO)
        ]
        results.append(
            scenario_reader_during_writes(
                TLESnapshotsRepository(base / "reader_4w"), snaps, 4
            )
        )

    env = {
        "platform": platform.platform(),
        "python": sys.version.split()[0],
        "duckdb": duckdb.__version__,
        "pyarrow": pyarrow.__version__,
        "orbital_sentinel": os_version,
        "n_snapshots_per_scenario": N_SNAPSHOTS_PER_SCENARIO,
    }

    return {
        "env": env,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "results": [asdict(r) for r in results],
    }


def _print_summary(data: dict) -> None:
    print()
    print(f"Env: {data['env']['platform']}")
    print(
        f"     Python {data['env']['python']}  "
        f"duckdb {data['env']['duckdb']}  "
        f"pyarrow {data['env']['pyarrow']}"
    )
    print()
    header = (
        f"{'Scenario':<28} {'W':>3} {'R':>3} {'N':>5} "
        f"{'Time(s)':>9} {'ins/s':>10} {'Fail':>5} {'Int':>4}"
    )
    print(header)
    print("-" * len(header))
    for r in data["results"]:
        print(
            f"{r['name']:<28} {r['n_writers']:>3} {r['n_readers']:>3} "
            f"{r['n_snapshots']:>5} "
            f"{r['elapsed_sec']:>9.3f} {r['throughput_inserts_per_sec']:>10.1f} "
            f"{r['failures']:>5} {'OK' if r['integrity_ok'] else 'FAIL':>4}"
        )
        if r.get("reader_query_count"):
            p50 = r.get("reader_query_latency_ms_p50")
            p95 = r.get("reader_query_latency_ms_p95")
            mx = r.get("reader_query_latency_ms_max")
            if p50 is not None:
                print(f"    -> reader: {r['reader_query_count']} queries, p50={p50:.2f}ms")
                if p95 is not None and mx is not None:
                    print(f"               p95={p95:.2f}ms  max={mx:.2f}ms")
            else:
                print("    -> reader: no latency data")


def main() -> Path:
    print("Running DuckDB+Parquet concurrency benchmark...")
    data = run_all()
    out_dir = Path(__file__).resolve().parent / "results"
    out_dir.mkdir(exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = out_dir / f"{ts}.json"
    out_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    _print_summary(data)
    print(f"\nResults JSON: {out_path}")
    return out_path


if __name__ == "__main__":
    main()
