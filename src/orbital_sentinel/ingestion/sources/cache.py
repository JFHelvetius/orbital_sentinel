"""Cache content-addressable de bytes descargados.

Layout en disco::

    root/
        blobs/<hash[:2]>/<hash>.bin    # bytes nombrados por SHA-256
        index.jsonl                    # append-only, una entrada por fetch

El cache cumple dos funciones complementarias:

* **Content-addressable storage** (ADR-0006): dos fetchs con bytes idénticos
  comparten un único blob en disco. La key es el SHA-256 de los bytes.
* **Source-keyed index** (ADR-0012): mapea ``(source, dataset)`` a la cadena
  histórica de observaciones, lo que permite al fetcher consultar la última
  observación sin volver a la red dentro de la ventana ``max_age``.

El cache es transitorio y puede purgarse sin pérdida de datos canónicos: el
registro inmutable vive en la capa Raw (``tle_snapshots``).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path
from typing import NamedTuple

from orbital_sentinel.core.errors import IngestionError


class CacheError(IngestionError):
    """Error operando el cache local."""


class CacheIndexEntry(NamedTuple):
    """Una entrada del índice del cache."""

    source: str
    dataset: str
    content_hash: str
    fetched_at: datetime
    url: str


class FetchCache:
    """Cache local de bytes descargados, content-addressable, con índice append-only."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.blobs_dir = self.root / "blobs"
        self.index_path = self.root / "index.jsonl"
        self.root.mkdir(parents=True, exist_ok=True)
        self.blobs_dir.mkdir(exist_ok=True)

    # --- Operaciones content-addressable ----------------------------------

    def has_blob(self, content_hash: str) -> bool:
        return self._blob_path(content_hash).is_file()

    def get_blob(self, content_hash: str) -> bytes:
        path = self._blob_path(content_hash)
        if not path.is_file():
            raise CacheError(f"Blob ausente: {content_hash}")
        return path.read_bytes()

    def put_blob(self, raw_bytes: bytes) -> str:
        """Almacena bytes; devuelve el content_hash. Idempotente."""
        content_hash = hashlib.sha256(raw_bytes).hexdigest()
        path = self._blob_path(content_hash)
        if path.is_file():
            return content_hash
        path.parent.mkdir(exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(raw_bytes)
        tmp.replace(path)
        return content_hash

    # --- Operaciones de índice -------------------------------------------

    def record(
        self,
        *,
        source: str,
        dataset: str,
        content_hash: str,
        fetched_at: datetime,
        url: str,
    ) -> None:
        """Añade una entrada al índice. ``fetched_at`` debe ser tz-aware."""
        if fetched_at.tzinfo is None:
            raise CacheError("fetched_at debe ser timezone-aware")
        payload = {
            "source": source,
            "dataset": dataset,
            "content_hash": content_hash,
            "fetched_at": fetched_at.astimezone(timezone.utc).isoformat(),
            "url": url,
        }
        with self.index_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, sort_keys=True) + "\n")

    def latest_for(self, source: str, dataset: str) -> CacheIndexEntry | None:
        """Devuelve la observación más reciente para ``(source, dataset)``."""
        latest: CacheIndexEntry | None = None
        for entry in self._iter_index():
            if entry.source != source or entry.dataset != dataset:
                continue
            if latest is None or entry.fetched_at > latest.fetched_at:
                latest = entry
        return latest

    # --- Internos --------------------------------------------------------

    def _iter_index(self) -> Iterator[CacheIndexEntry]:
        if not self.index_path.is_file():
            return
        with self.index_path.open("r", encoding="utf-8") as f:
            for raw_line in f:
                line = raw_line.strip()
                if not line:
                    continue
                payload = json.loads(line)
                yield CacheIndexEntry(
                    source=payload["source"],
                    dataset=payload["dataset"],
                    content_hash=payload["content_hash"],
                    fetched_at=datetime.fromisoformat(payload["fetched_at"]),
                    url=payload["url"],
                )

    def _blob_path(self, content_hash: str) -> Path:
        if len(content_hash) != 64:
            raise CacheError(f"content_hash con longitud inválida: {content_hash}")
        return self.blobs_dir / content_hash[:2] / f"{content_hash}.bin"
