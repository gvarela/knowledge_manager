---
project: phase-3-embedding-and-search
ticket: null
created: 2026-04-15
created_timestamp: 2026-04-15T18:50:17Z
status: complete
last_updated: 2026-04-16
researcher: gvarela
git_commit: d385d73b0c7364eae8641442b6690e3f263158ab
git_branch: main
repository: knowledge-manager
tags: [research, codebase, phase-3-embedding-and-search]
---

# Research: Phase 3 — Embedding + Search

**Created**: 2026-04-15 18:50 UTC
**Last Updated**: 2026-04-15
**Ticket**: N/A
**Git Commit**: d385d73
**Branch**: main

## Research Question

How should we wrap `fastembed` and compose it with the existing chunker + store to deliver full-vault indexing and incremental updates? Specifically: what does each Phase 1+2 module currently expose, what does the `fastembed` API look like, and what conventions must Phase 3 match?

## Summary

Phase 3 has three building blocks already in place and one new external library to integrate.

**In the codebase.** Phase 1 delivered `chunk_markdown(text, file_path, config) -> list[Chunk]` and `scan_vault(vault_path, scan_config) -> list[Path]` plus the `load_config` / `resolve_for_file` pair that turns `.km/config.toml` into typed dataclasses. Phase 2 delivered `Store`, a context-manager-protocol class with `insert`, `bulk_insert`, `upsert_file`, `knn_search`, `stats`, `clear`, `close`. Both phases follow a strict import DAG (`__init__.py` exports types and is imported by everyone else; nothing else cycles back), all dataclasses are `frozen=True, slots=True`, and tests use real implementations rather than mocks. `src/km/embedder.py` and `src/km/search.py` are empty (single-line files, no imports). `src/km/cli.py` is a stub that raises `SystemExit`.

**The integration gap.** Two concrete pieces of plumbing have no current owner: (1) the resolved `index = false` override key — `_OVERRIDE_FIELDS` in `config.py:10` accepts it and `resolve_for_file` explicitly skips it (`config.py:78`), but no module reads or acts on it; (2) `scan_vault` returns absolute `Path` objects but `Store.upsert_file` expects vault-relative `str` `file_path`. Phase 3 needs to bridge both gaps inside the orchestration layer.

**The external library.** `fastembed` is a Qdrant-maintained ONNX-only embedding library (no PyTorch). Its `TextEmbedding` class defaults to `BAAI/bge-small-en-v1.5` (384 dims, ~68 MB quantized ONNX). The `.embed(documents, batch_size=256)` method returns a generator of numpy `float32` arrays — must be wrapped with `list(...)` to materialize and `.tolist()` to convert to Python lists before passing to `sqlite-vec`. The model emits L2-normalized vectors, which means sqlite-vec's default L2 distance produces the same ranking as cosine similarity. Per fastembed's own model description, prefix engineering ("query: " / "passage: ") is "not so necessary" for v1.5; the library's `query_embed` and `passage_embed` methods on the BGE base class fall through to plain `embed()` with no prefix injection.

## Detailed Findings

### Existing km API surface

#### Shared types (`src/km/__init__.py`)

`__all__` exports: `["Chunk", "ChunkConfig", "ScanConfig", "VaultConfig", "__version__"]` (`__init__.py:41`). The module imports nothing from `km.*` — only stdlib (`dataclasses`, `pathlib.PurePosixPath`, `typing.Literal`).

All four dataclasses use `@dataclass(frozen=True, slots=True)`:

- `ChunkConfig` (`__init__.py:8-13`): `split_on: tuple[str, ...]`, `strip_frontmatter: bool`, `min_chunk_chars: int`, `strategy: Literal["default", "atomic"]`. No `index` field.
- `ScanConfig` (`__init__.py:16-19`): `include: tuple[str, ...]`, `exclude_dotdirs: bool`.
- `VaultConfig` (`__init__.py:22-26`): wraps `chunk: ChunkConfig`, `scan: ScanConfig`, `overrides: tuple[dict, ...]`. The `overrides` field stores raw dicts as loaded from TOML — not further typed.
- `Chunk` (`__init__.py:29-38`): `file_path: str`, `section_header: str`, `content: str`, `directory: str = field(init=False)`. `directory` is computed in `__post_init__` from `PurePosixPath(file_path).parts[0]` (or `""` if the file sits at the vault root). Because the dataclass is frozen, the assignment uses `object.__setattr__`.

#### Config layer (`src/km/config.py`)

`load_config(vault_path: Path) -> VaultConfig` (`config.py:22-63`):
- Looks for `vault_path / ".km" / "config.toml"`. If absent, returns `VaultConfig()` with all defaults.
- Validates four levels — top-level keys, `[defaults]`, `[scan]`, each `[[overrides]]` entry — against the introspected dataclass field sets in `_KNOWN_TOP_LEVEL`, `_CHUNK_FIELDS`, `_SCAN_FIELDS`, `_OVERRIDE_FIELDS` (`config.py:7-10`).
- Coerces TOML arrays to tuples for `split_on` and `include` (so dataclass default-equality holds).
- Raises `ValueError` (or `tomllib.TOMLDecodeError`, which subclasses `ValueError`) on any unknown key or malformed TOML.

`resolve_for_file(config: VaultConfig, file_path: str) -> ChunkConfig` (`config.py:66-86`):
- `file_path` is vault-relative.
- Walks `config.overrides` in order. For each override, checks each pattern in its `"files"` list (or single string) via `PurePosixPath(file_path).match(pattern)`. On the first match, copies all keys (skipping `"files"` and `"index"`) into a resolved dict.
- Constructs and returns `ChunkConfig(**resolved)`.

The `"index"` key in an override is parsed and validated but never copied into `ChunkConfig`. No code in any module reads or filters on it. **Phase 3 will be the first consumer of `index = false`** — it must read overrides directly (`config.overrides`) since `resolve_for_file` discards the value.

#### Chunker (`src/km/chunker.py`)

`scan_vault(vault_path: Path, config: ScanConfig) -> list[Path]` (`chunker.py:9-21`):
- Iterates `config.include` patterns, calls `vault_path.glob(pattern)` for each, filters `is_file()`.
- If `config.exclude_dotdirs` is True, drops any path whose `relative_to(vault_path).parts` contains any segment starting with `.`.
- Deduplicates via a `set[Path]`, returns `sorted(results)`.
- **Returns absolute `Path` objects** (because `vault_path.glob` does, when `vault_path` is absolute).
- On a non-existent `vault_path`, `Path.glob` returns an empty iterator — the function returns `[]` without raising. Confirmed by `test_scan_vault_on_nonexistent_path_raises` (`test_chunker.py:124-132`, which actually asserts `== []`).

`chunk_markdown(text: str, file_path: str, config: ChunkConfig) -> list[Chunk]` (`chunker.py:35-83`):
- Pure function, no I/O. Accepts text directly.
- Order of operations: `text.strip()` → empty check → optional frontmatter strip via `_FRONTMATTER_RE` (`chunker.py:6`, regex `r"^---\n.*?\n---\n?"` with `re.DOTALL`) → empty-after-strip check → `min_chunk_chars` short-circuit → `strategy == "atomic"` short-circuit → header-driven splitting using `_LEVEL_TO_PART` (`chunker.py:24-32`) which only knows `"h1"` and `"h2"`.
- Returns `[]` for empty/whitespace-only/frontmatter-only inputs.

#### Store (`src/km/store.py`, 141 lines)

Two-table sqlite-vec persistence. The module docstring (`store.py:1-10`) documents the invariant: `chunks.id == vec_chunks.rowid` for every row.

Constructor: `Store(db_path: Path, dim: int = 384)` (`store.py:41-51`). Opens connection, loads `sqlite_vec` extension, sets `PRAGMA journal_mode=WAL`, creates schema with `IF NOT EXISTS`. Schema: `chunks(id PK AUTOINCREMENT, file_path, section_header, content, directory)` + `vec_chunks USING vec0(embedding float[{dim}])` + `idx_chunks_file_path` (`store.py:19-36`).

Public methods:

| Method | Signature | Behavior |
|---|---|---|
| `insert` | `(chunk: Chunk, embedding: list[float]) -> int` | Single insert in `with self._conn` transaction. Returns rowid. |
| `bulk_insert` | `(items: list[tuple[Chunk, list[float]]]) -> None` | All items in one transaction. |
| `upsert_file` | `(file_path: str, items: list[...]) -> None` | One transaction: SELECT ids → DELETE chunks by file_path → DELETE vec_chunks by rowid IN (...) → insert new pairs. Empty `items` deletes only. Nonexistent `file_path` is a no-op delete then inserts. |
| `knn_search` | `(query_embedding: list[float], k: int = 10) -> list[tuple[Chunk, float]]` | JOIN query: `vec_chunks v JOIN chunks c ON c.id = v.rowid WHERE v.embedding MATCH ? AND v.k = ? ORDER BY v.distance`. Reconstructs `Chunk` from `(file_path, section_header, content)` only — `directory` is recomputed by `__post_init__`. Returns `[]` on empty DB. |
| `stats` | `() -> dict[str, int]` | `{"files": int, "chunks": int}` from `COUNT(DISTINCT file_path), COUNT(*)`. |
| `clear` | `() -> None` | DELETE from both tables in one transaction. Does NOT reset autoincrement. |
| `close` | `() -> None` | `self._conn.close()`. |
| `__enter__` / `__exit__` | context manager | `__exit__` always calls `self.close()`, does not suppress exceptions (`store.py:137-141`). |

Internal helpers:
- `_check_dim(embedding)` raises `ValueError(f"embedding has {len(embedding)} dimensions, expected {self._dim}")` (`store.py:53-57`). Called by `insert` and `knn_search` (and via `_insert_pair`, by `bulk_insert` and `upsert_file`).
- `_insert_pair(chunk, embedding)` (`store.py:59-74`) is the single insertion path. All callers run inside `with self._conn:`.

Vector serialization uses `sqlite_vec.serialize_float32(embedding)` — accepts a Python list of floats (numpy arrays must be `.tolist()`-converted first).

#### CLI/main (currently stubbed)

- `src/km/__main__.py` (4 lines): calls `cli.main()`.
- `src/km/cli.py` (2 lines): `def main() -> None: raise SystemExit("km: not yet implemented")`.

Phase 4 territory; out of scope for Phase 3.

### fastembed library (external dependency to add)

**Source/version:** `fastembed` 0.8.0 on PyPI (released 2026-03-23). Python `>=3.10`. Install: `pip install fastembed`. Wheel ~114 KB; runtime weight is the ONNX model. Dependencies: `onnxruntime`, `huggingface-hub`, `tokenizers`, `numpy`, `loguru`, `tqdm`, `mmh3`, `pillow`, `py-rust-stemmers`. **No PyTorch.** GPU is a separate package (`fastembed-gpu`), not an extra.

**Primary class:** `from fastembed import TextEmbedding`. Constructor signature (`fastembed/text/text_embedding.py`):

```python
TextEmbedding(
    model_name: str = "BAAI/bge-small-en-v1.5",
    cache_dir: str | None = None,
    threads: int | None = None,
    providers: Sequence[OnnxProvider] | None = None,
    cuda: bool | Device = Device.AUTO,
    device_ids: list[int] | None = None,
    lazy_load: bool = False,
    **kwargs,  # e.g. local_files_only=True
)
```

With `lazy_load=False` (default), the model downloads at constructor time. With `lazy_load=True`, deferred until first `.embed()` call.

**Embedding method:** `.embed(documents, batch_size=256, parallel=None) -> Iterable[NumpyArray]`. Accepts a single string or any iterable of strings. **Returns a generator** — iteration triggers ONNX inference. Each yielded item is `NDArray[np.float32]` of shape `(384,)`. Convert to native list via `.tolist()`.

**`BAAI/bge-small-en-v1.5` specifics** (from `onnx_embedding.py` registry):
- Dimension: 384
- Model file: quantized ONNX `model_optimized.onnx` from `qdrant/bge-small-en-v1.5-onnx-q` on HuggingFace
- Disk size: 0.067 GB (~68 MB)
- Max input: 512 tokens (truncated)
- Default model — `TextEmbedding()` with no args picks it.
- Description field: `"Prefixes for queries/documents: not so necessary, 2023 year."`

**Query vs passage:** Three methods exist on `TextEmbedding`: `embed`, `query_embed`, `passage_embed`. For `BAAI/bge-small-en-v1.5` (handled by `OnnxTextEmbedding`), `query_embed` and `passage_embed` are inherited from `TextEmbeddingBase` and simply call `embed()` with no prefix modification:

```python
# fastembed/text/text_embedding_base.py
def passage_embed(self, texts, **kwargs):
    yield from self.embed(texts, **kwargs)

def query_embed(self, query, **kwargs):
    if isinstance(query, str):
        yield from self.embed([query], **kwargs)
    else:
        yield from self.embed(query, **kwargs)
```

For this model, calling `query_embed(q)` and `embed([q])` produce identical outputs.

**Cache path** (`fastembed/common/utils.py::define_cache_dir`): defaults to `os.path.join(tempfile.gettempdir(), "fastembed_cache")`, overridable via `FASTEMBED_CACHE_PATH` env var or the `cache_dir=` constructor arg. On macOS that resolves to `/var/folders/.../T/fastembed_cache` or `/tmp/fastembed_cache`. Subsequent runs check the cache first via `local_files_only=True` then fall back to download with retry.

**Normalization:** `OnnxTextEmbedding._post_process_onnx_output` extracts the CLS token (`embeddings[:, 0]`) then calls `normalize()` (L2). Output vectors are unit-length.

### Distance metric compatibility (sqlite-vec ↔ fastembed)

sqlite-vec defaults `vec0` virtual tables to **L2 (Euclidean) distance** for KNN. The current Store uses the default — `embedding float[{dim}]` with no `distance_metric=` modifier (`store.py:24`).

For L2-normalized unit vectors `a` and `b`:
- `cosine_similarity(a, b) = a · b`
- `L2_distance(a, b)² = 2 - 2 · (a · b) = 2 - 2 · cosine_similarity(a, b)`

L2 distance is a strictly monotonic decreasing function of cosine similarity for unit vectors. **Ranking by ascending L2 distance is identical to ranking by descending cosine similarity.** No schema change is required to use BGE embeddings with the existing Store.

(sqlite-vec also supports `distance_metric=cosine` and `distance_metric=L1` as opt-in modifiers per the `vec0` API reference at alexgarcia.xyz/sqlite-vec.)

### Existing test conventions

`tests/conftest.py` (13 lines) defines a single fixture `store` that creates `tmp_path / "index.db"`, opens it in a context manager, and yields the open `Store`. Type hint: `Iterator[Store]`. Tests with non-default `dim` or those exercising reopen create their own `Store` directly.

**Test naming:** `test_<subject>_<behavior>` consistently — `test_load_config_from_toml`, `test_knn_search_returns_nearest`, `test_insert_rejects_wrong_dim_embedding`, etc.

**Slow marker:** Configured in `pyproject.toml:33` as `markers = ["slow: tests that download models or hit disk heavily"]`. Currently no test in the codebase uses `@pytest.mark.slow`; Phase 3 is the first.

**No mocking.** Grep for `Mock`, `MagicMock`, `monkeypatch`, `@patch` across `tests/` returns zero matches. The pattern is real implementations + fake/deterministic data.

**Fake-vector convention:** Inline list multiplication. Standard 384-dim vector is `[0.1] * 384`. Distance-ordering tests use sparse directional vectors like `[1.0] + [0.0] * 383` and `[0.9] + [0.1] + [0.0] * 382` (`test_store.py:51-67`). No helper functions — embeddings are constructed inline.

**Error assertion:** `with pytest.raises(ValueError, match="383"):` — context-manager form, regex substring match (`test_store.py:171, 178`; `test_config.py:44, 52, 60, 70, 80`).

**Import style:** Public dataclasses from `km`; functions/classes from their submodules. `from km import Chunk, ChunkConfig, ScanConfig` and `from km.chunker import chunk_markdown, scan_vault`, `from km.store import Store`, `from km.config import load_config, resolve_for_file`. No wildcard imports, no relative imports.

## Architecture Documentation

### Patterns Found

**Frozen-slots dataclasses everywhere** with `field(init=False)` for derived fields and `object.__setattr__` in `__post_init__` to bypass the frozen guard:
- Example: `src/km/__init__.py:29-38` (`Chunk.__post_init__` deriving `directory`)

**Strict layered import DAG** confirmed by analyzer:

| Module | Imports from `km.*` | Status |
|---|---|---|
| `__init__.py` | nothing (stdlib only) | exists |
| `config.py` | `ChunkConfig`, `ScanConfig`, `VaultConfig` from `km` | exists |
| `chunker.py` | `Chunk`, `ChunkConfig`, `ScanConfig` from `km` | exists |
| `store.py` | `Chunk` from `km` | exists |
| `embedder.py` | (target: nothing — plain str/float in/out) | empty file |
| `search.py` | (target: `config`, `chunker`, `store`, `embedder`, `__init__`) | empty file |
| `cli.py` | (target: `search`, `config`) | stub raising SystemExit |
| `__main__.py` | `cli` | exists |

**Single transactional path in Store.** All inserts route through `_insert_pair` (`store.py:59-74`); all mutating public methods wrap their work in `with self._conn:`. Read-only methods (`stats`, `knn_search`) have no transaction wrapper.

**Configuration validation at load time.** `load_config` rejects unknown keys at four levels via field-set introspection from the dataclasses themselves (`config.py:7-10`). Validation errors include the offending key name in the message.

**Test isolation via `tmp_path`.** Every persistent test uses pytest's `tmp_path` fixture, never a hardcoded path or a shared file.

### Component connections (current state)

```
                 ┌────────────────────┐
                 │  __init__.py       │  (Chunk, *Config, __version__)
                 │  no km imports     │
                 └─────────┬──────────┘
                           │ types
       ┌───────────────────┼───────────────────┬──────────────┐
       ▼                   ▼                   ▼              ▼
  config.py           chunker.py           store.py       embedder.py  ← EMPTY
  load_config         chunk_markdown       Store           (target: no
  resolve_for_file    scan_vault                            km imports)
                                              ▲
                                              │
                                          search.py  ← EMPTY
                                          (target: composes
                                           config + chunker
                                           + store + embedder)
                                              ▲
                                              │
                                            cli.py  ← STUB
```

The two empty files and the stub CLI are the only remaining production code surface in the package.

### Conventions observed

- Modules are flat in `src/km/` (no subdirectories at this size).
- Error messages embed the offending value (the dim, the unknown key) so `pytest.raises(..., match=...)` can pin them.
- Public API is what's in `__init__.__all__`; tests import freely from submodules for things not re-exported.

## Code References

Quick reference for files and key line ranges relevant to Phase 3:

- `src/km/__init__.py:8-38` — all dataclass definitions; export list at `:41`
- `src/km/config.py:7-10` — field-set constants used for validation
- `src/km/config.py:22-63` — `load_config`
- `src/km/config.py:66-86` — `resolve_for_file` (skips `"files"` and `"index"` at `:78`)
- `src/km/chunker.py:9-21` — `scan_vault` (returns absolute `Path` objects, sorted, dotdir-filtered)
- `src/km/chunker.py:35-83` — `chunk_markdown`
- `src/km/store.py:1-10` — module docstring stating the `chunks.id == vec_chunks.rowid` invariant
- `src/km/store.py:19-36` — schema DDL (note `embedding float[{dim}]` — default L2 distance)
- `src/km/store.py:41-51` — `__init__` (WAL mode, sqlite_vec.load, `dim=384` default)
- `src/km/store.py:53-57` — `_check_dim`
- `src/km/store.py:86-101` — `upsert_file` (the operation Phase 3 `update_files` will call per-file)
- `src/km/store.py:103-120` — `knn_search`
- `src/km/store.py:137-141` — context manager protocol
- `src/km/embedder.py` — empty (1 line)
- `src/km/search.py` — empty (1 line)
- `src/km/cli.py` — `def main() -> None: raise SystemExit(...)`
- `tests/conftest.py:1-13` — `store` fixture
- `tests/test_store.py:51-67` — pattern for distance-ordering test data
- `pyproject.toml:6` — current `dependencies = ["sqlite-vec"]` (Phase 3 will add `fastembed`)
- `pyproject.toml:33` — `markers = ["slow: ..."]`

## Similar Implementations

**Inside this codebase:** none. There is no prior `Embedder` or `Searcher` to mirror. Both target files are empty.

The closest precedent for the orchestration layer is `Store` itself — a class that wraps a single library (`sqlite-vec`), exposes a small set of methods, owns a context-manager lifecycle, and validates its inputs at the boundary. The pattern is reproducible for `Embedder` (wrap `fastembed.TextEmbedding`, expose `.embed(texts)`, validate dimension on output, document model name and dim).

The closest precedent for `index_vault` is the standalone E2E demo at `/tmp/claude/km_e2e_demo.py` (not committed) used to verify Phase 1+2 against the real vault. Its loop:

```python
files = scan_vault(VAULT, scan_cfg)            # absolute paths
for f in files:
    text = f.read_text(encoding="utf-8")
    rel = str(f.relative_to(VAULT))            # vault-relative for Chunk.file_path
    chunks = chunk_markdown(text, rel, chunk_cfg)
    for c in chunks:
        items.append((c, fake_vec()))
store.bulk_insert(items)
```

Phase 3's `index_vault` will follow the same shape, with `fake_vec()` replaced by an actual `Embedder.embed()` call and per-file config resolution via `resolve_for_file`.

**Outside this codebase:** the fastembed README's basic-use snippet (Section 10 above) is the canonical pattern:

```python
from fastembed import TextEmbedding
model = TextEmbedding()                              # downloads on first run
embeddings = list(model.embed(documents))            # generator → list of np.float32 arrays
vectors = [e.tolist() for e in embeddings]           # convert to Python lists for sqlite-vec
```

## Open Questions

These are decisions that belong in `design.md`, not facts to document here. They are surfaced for the design phase to resolve; capture in beads (`bd create -t task -p 2 ...`) once design starts if any need separate tracking.

1. **Where does `index = false` filtering live?** `resolve_for_file` discards the `index` key. Options: (a) `Searcher.index_vault` reads `config.overrides` directly and matches each file's relative path, (b) extend `resolve_for_file` to return `(ChunkConfig, indexed: bool)`, (c) add a sibling `should_index_file(config, file_path) -> bool` helper.

2. **Path conversion boundary.** `scan_vault` returns absolute `Path` objects; `Chunk.file_path` and `Store.upsert_file` expect vault-relative strings. Where does the conversion happen — inside `Searcher`, or by adding an option to `scan_vault`?

3. **Embedder mocking strategy for `test_search_end_to_end`.** Conventions say no `Mock`, no `monkeypatch`. The codebase uses real implementations + fake data. Options: (a) define a tiny duck-typed `FakeEmbedder` class in the test file, (b) inject the embed function as a callable, (c) introduce an `EmbedderProtocol` in `__init__.py` and pass the fake. PLAN.md mentions "(mock embedder)" but the existing convention is plain duck typing.

4. **Batching shape inside `index_vault`.** Embed per-file (small batches, more calls), embed per-vault (one big batch with `batch_size=256`, more memory), or embed per-chunk-stream (generator into `model.embed`). fastembed's `batch_size` defaults to 256.

5. **Query construction.** For `BAAI/bge-small-en-v1.5`, fastembed's `query_embed` and `embed` produce identical output. Pick one for the search path (probably `embed` for symmetry with indexing).

6. **`Embedder` constructor parameters to expose.** At minimum `model_name` and `cache_dir` (so the cache can live somewhere stable, possibly under `.km/`). Consider `lazy_load=True` so importing the module doesn't trigger a download.

7. **`SearchResult` dataclass shape.** PLAN.md says it lives in `search.py`. Options: `(chunk: Chunk, distance: float)`, or add `score: float` (1 - distance for unit vectors), or carry the resolved query string. The Store's `knn_search` already returns `list[tuple[Chunk, float]]` — `SearchResult` is mostly a typed wrapper.

8. **Vault-root parameter to `Searcher`.** `index_vault` and `update_files` both need to know the vault root to (a) call `load_config(vault_root)`, (b) compute relative paths from absolute scan results, (c) read file contents. Probably a constructor argument.

9. **Update path semantics.** PLAN.md says `update_files(paths)` accepts vault-relative paths. Confirm: what does it do if a path no longer exists on disk? (Delete its chunks via `upsert_file(path, [])` is the natural answer.)

## Next Steps

1. Review this research document.
2. Run `/wb:create_design docs/plans/2026-04-15-phase-3-embedding-and-search` to convert the open questions into design decisions (`index = false` location, mocking strategy, batching, `SearchResult` shape, etc.).
3. After design is approved, run `/wb:create_execution` to generate the TDD task list (steps 19-22).

## References

- Design: [design.md](design.md)
- Tasks: [tasks.md](tasks.md)
- Overall plan: [PLAN.md](../../../PLAN.md)
- Phase 1 docs: [../2026-04-14-phase-1-foundation/](../2026-04-14-phase-1-foundation/)
- Phase 2 docs: [../2026-04-14-phase-2-storage/](../2026-04-14-phase-2-storage/)
- fastembed PyPI: https://pypi.org/project/fastembed/
- fastembed GitHub: https://github.com/qdrant/fastembed
- fastembed source — TextEmbedding: https://github.com/qdrant/fastembed/blob/main/fastembed/text/text_embedding.py
- fastembed source — ONNX embedding (BGE): https://github.com/qdrant/fastembed/blob/main/fastembed/text/onnx_embedding.py
- fastembed source — cache util: https://github.com/qdrant/fastembed/blob/main/fastembed/common/utils.py
- BAAI/bge-small-en-v1.5 model card: https://huggingface.co/BAAI/bge-small-en-v1.5
- sqlite-vec KNN docs: https://alexgarcia.xyz/sqlite-vec/features/knn.html
- sqlite-vec API reference: https://alexgarcia.xyz/sqlite-vec/api-reference.html
