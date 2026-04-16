"""Orchestration layer: search and indexing."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from km import Chunk, VaultConfig
from km.chunker import chunk_markdown, scan_vault
from km.config import load_config, resolve_for_file
from km.embedder import Embedder
from km.store import Store


def _should_index(config: VaultConfig, relative_path: str) -> bool:
    """Return False if any override matching this path sets index=False."""
    for override in config.overrides:
        files = override.get("files", "")
        patterns = [files] if isinstance(files, str) else list(files)
        for pattern in patterns:
            if PurePosixPath(relative_path).match(pattern):
                return override.get("index") is not False
    return True  # no override matched → index by default


@dataclass(frozen=True, slots=True)
class SearchResult:
    chunk: Chunk
    distance: float


class Searcher:
    def __init__(
        self,
        vault_root: Path,
        store: Store | None = None,
        embedder: object | None = None,
    ) -> None:
        self._vault_root = vault_root

        if store is None:
            km_dir = vault_root / ".km"
            km_dir.mkdir(parents=True, exist_ok=True)
            self._store = Store(km_dir / "index.db")
            self._owns_store = True
        else:
            self._store = store
            self._owns_store = False

        if embedder is None:
            self._embedder = Embedder(cache_dir=vault_root / ".km" / "models")
        else:
            self._embedder = embedder

    def __enter__(self) -> Searcher:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        if self._owns_store:
            self._store.close()

    def search(self, query: str, k: int = 10) -> list[SearchResult]:
        query_vec = self._embedder.embed([query])[0]
        pairs = self._store.knn_search(query_vec, k=k)
        return [SearchResult(chunk=c, distance=d) for c, d in pairs]

    def _chunk_and_embed_file(
        self, text: str, relative: str, config: VaultConfig
    ) -> list[tuple[Chunk, list[float]]]:
        """Chunk a file's text and embed the chunks. Returns (chunk, vector) pairs."""
        file_config = resolve_for_file(config, relative)
        chunks = chunk_markdown(text, relative, file_config)
        if not chunks:
            return []
        vectors = self._embedder.embed([c.content for c in chunks])
        return list(zip(chunks, vectors, strict=True))

    def index_vault(self) -> dict[str, int]:
        """Full re-index: scan → chunk → embed → store. Returns stats."""
        config = load_config(self._vault_root)
        paths = scan_vault(self._vault_root, config.scan)

        all_items: list[tuple[Chunk, list[float]]] = []
        for absolute in paths:
            relative = str(absolute.relative_to(self._vault_root))
            if not _should_index(config, relative):
                continue
            text = absolute.read_text(encoding="utf-8")
            all_items.extend(self._chunk_and_embed_file(text, relative, config))

        self._store.clear()
        self._store.bulk_insert(all_items)
        return self._store.stats()

    def update_files(self, paths: list[str]) -> dict[str, int]:
        """Re-index named files (vault-relative). Deletes chunks for missing files."""
        config = load_config(self._vault_root)
        files_processed = 0
        chunks_inserted = 0

        for relative in paths:
            if not _should_index(config, relative):
                continue
            absolute = self._vault_root / relative
            if not absolute.exists():
                self._store.upsert_file(relative, [])
                files_processed += 1
                continue
            text = absolute.read_text(encoding="utf-8")
            items = self._chunk_and_embed_file(text, relative, config)
            self._store.upsert_file(relative, items)
            files_processed += 1
            chunks_inserted += len(items)

        return {"files": files_processed, "chunks": chunks_inserted}
