---
project: phase-2-storage
ticket: null
created: 2026-04-14
created_timestamp: 2026-04-14T23:22:02Z
status: approved
last_updated: 2026-04-14
designer: gvarela
git_commit: 327cc07
git_branch: main
repository: knowledge-manager
tags: [design, architecture, phase-2-storage]
depends_on: research.md
design_approach: two-table schema with Store class
---

# Design: Phase 2 Storage

**Created**: 2026-04-14 23:22 UTC
**Last Updated**: 2026-04-14
**Designer**: gvarela
**Status**: Approved

## Problem Statement

Phase 1 produces `Chunk` objects from markdown files. These chunks need to be stored alongside their vector embeddings in a local database so that KNN search can retrieve the most semantically similar chunks for a given query. The store must support incremental updates (upsert by file_path) as the steady-state operation, since the vault changes ~15% per week through daily `/process` sessions.

### Success Metrics

- Store class creates schema automatically on instantiation
- Single and bulk insert of chunks with vectors works
- KNN search returns nearest neighbors ranked by distance
- Upsert deletes all existing chunks for a file_path, then inserts new ones
- Clear removes all data for full rebuild
- Stats returns file count and chunk count
- All operations use `Chunk` from `km.__init__` — store never imports from other km modules

## Design Approach

**Two-table schema with a `Store` class that wraps sqlite3 + sqlite-vec.** A regular `chunks` table holds metadata and content (queryable with standard SQL). A `vec_chunks` virtual table holds vectors only, linked by rowid. The `Store` class owns the connection, creates the schema, and exposes methods matching the five TDD steps.

### Why This Approach

- **Upsert requires queryable file_path.** The steady-state operation is `km update <files>` which deletes all chunks for those file paths and re-inserts. This requires `WHERE file_path = ?` on the metadata table — auxiliary columns on vec0 cannot appear in WHERE clauses.
- **Stats require COUNT DISTINCT.** `stats()` needs distinct file_path count and total chunk count — standard SQL on a regular table.
- **Matches PLAN.md specification.** PLAN.md:314 specifies "Query vectors via `sqlite_vec.serialize_float32()`. Virtual table handles storage vectors on insert." The two-table pattern is the canonical sqlite-vec example.
- **Clean separation.** Metadata/content in one place, vectors in another. If the embedding model changes, only vectors need rebuilding.

## Technical Decisions

### Schema

Two tables, linked by rowid:

```sql
CREATE TABLE IF NOT EXISTS chunks (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path      TEXT NOT NULL,
    section_header TEXT NOT NULL,
    content        TEXT NOT NULL,
    directory      TEXT NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS vec_chunks USING vec0(
    embedding float[384]
);
```

`chunks.id` is the rowid for `vec_chunks`. All four `Chunk` fields are stored (including `directory`, which is derived but useful for filtering).

An index on `file_path` for fast upsert lookups:

```sql
CREATE INDEX IF NOT EXISTS idx_chunks_file_path ON chunks(file_path);
```

### Store Class API

```python
class Store:
    def __init__(self, db_path: Path) -> None: ...
    def insert(self, chunk: Chunk, embedding: list[float]) -> int: ...
    def bulk_insert(self, items: list[tuple[Chunk, list[float]]]) -> None: ...
    def knn_search(self, query_embedding: list[float], k: int = 10) -> list[tuple[Chunk, float]]: ...
    def upsert_file(self, file_path: str, items: list[tuple[Chunk, list[float]]]) -> None: ...
    def clear(self) -> None: ...
    def stats(self) -> dict[str, int]: ...
    def close(self) -> None: ...
```

- **`__init__`** — Opens connection, loads sqlite-vec extension, creates schema if not exists. Takes `db_path: Path` (the `.km/index.db` file).
- **`insert`** — Inserts one chunk + embedding. Returns the chunk ID. Inserts into `chunks` first (gets lastrowid), then into `vec_chunks`.
- **`bulk_insert`** — Inserts multiple (chunk, embedding) pairs in a single transaction.
- **`knn_search`** — Takes a query embedding and k, returns list of `(Chunk, distance)` tuples ordered by distance. Uses `MATCH` + `k =` on vec_chunks, JOINs to chunks.
- **`upsert_file`** — Deletes all existing chunks for a file_path (from both tables), then bulk-inserts new ones. Single transaction.
- **`clear`** — Deletes all rows from both tables. For full rebuild.
- **`stats`** — Returns `{"files": N, "chunks": M}` from `COUNT(DISTINCT file_path)` and `COUNT(*)` on the chunks table.
- **`close`** — Closes the database connection.

### Vector Serialization

Embeddings are passed to Store methods as `list[float]`. The Store serializes them internally using `sqlite_vec.serialize_float32()` before INSERT. Query vectors are also serialized before the MATCH query. The caller never handles serialization.

### Distance Metric

L2 (Euclidean) — the vec0 default. `bge-small-en-v1.5` embeddings are normalized, so L2 and cosine produce equivalent rankings. L2 avoids specifying `distance_metric=cosine` at DDL time, keeping the schema simpler.

### Connection Management

Store owns the sqlite3 connection. `enable_load_extension(True)` is called once in `__init__`, `sqlite_vec.load(db)` loads the extension, then `enable_load_extension(False)` re-disables it. WAL mode is enabled for concurrent read safety: `PRAGMA journal_mode=WAL`.

### Import Constraints

`store.py` imports only from `km.__init__` (the `Chunk` type). It also imports `sqlite3`, `sqlite_vec`, and stdlib modules. It never imports from `config.py`, `chunker.py`, `embedder.py`, or `search.py`.

## Scope Definition

### In Scope

- `Store` class in `src/km/store.py` with schema creation, insert, bulk_insert, knn_search, upsert_file, clear, stats, close
- Adding `sqlite-vec` to `pyproject.toml` dependencies
- Tests in `tests/test_store.py` using fake embeddings (random float vectors)
- Schema with `chunks` table + `vec_chunks` virtual table + file_path index

### Out of Scope

- Real embeddings (Phase 3 — fastembed)
- Searcher orchestration (Phase 3 — search.py)
- CLI integration (Phase 4)
- Config-based DB path discovery (Phase 4 — `.km/` auto-discovery)
- Migration support (schema is new, no existing data)

## Success Criteria

### Functional Requirements

- [ ] `Store(db_path)` creates schema on first use, reuses on subsequent opens
- [ ] `insert(chunk, embedding)` stores chunk metadata + vector, returns chunk ID
- [ ] `bulk_insert(items)` inserts multiple chunks in a single transaction
- [ ] `knn_search(query_embedding, k)` returns k nearest `(Chunk, distance)` tuples
- [ ] `upsert_file(file_path, items)` replaces all chunks for a file_path atomically
- [ ] `clear()` removes all data from both tables
- [ ] `stats()` returns `{"files": N, "chunks": M}`
- [ ] Chunks round-trip correctly: insert → search → Chunk fields match

### Non-Functional Requirements

- [ ] All Phase 2 tests run in <1s (fake embeddings, in-memory or tmp_path DB)
- [ ] ruff check and format pass clean
- [ ] Import DAG respected: store.py depends only on `__init__`
- [ ] Store works with `:memory:` databases for testing

## Risk Analysis

### Technical Risks

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| macOS system Python lacks extension loading | High | Low | Project uses uv-managed Python 3.13; verify in step 14 |
| sqlite-vec API changes between versions | Low | Low | Pin to `sqlite-vec>=0.1.9,<0.2` |
| rowid synchronization between tables | Medium | Low | Always insert chunks table first, use lastrowid; single transaction |
| vec0 doesn't support UPDATE | Low | N/A | Design already uses delete+re-insert pattern |

## Rejected Alternatives

### Auxiliary Columns on vec0

Using `+file_path`, `+content` etc. as auxiliary columns on the virtual table to avoid JOINs.

- **Rejected because**: Auxiliary columns cannot appear in WHERE clauses. Upsert needs `WHERE file_path = ?` to find chunks to delete. Stats needs `COUNT(DISTINCT file_path)`. Both require a regular table.

### Cosine Distance Metric

Setting `distance_metric=cosine` at table creation.

- **Rejected because**: `bge-small-en-v1.5` produces L2-normalized embeddings. For normalized vectors, L2 distance ranking is equivalent to cosine distance ranking. L2 is the vec0 default, avoiding an extra DDL parameter. If a future model produces non-normalized embeddings, the table would need rebuilding regardless.

### Store as a Protocol/ABC

Defining a `StoreProtocol` in `__init__.py` and implementing it in `store.py`.

- **Rejected because**: There's only one implementation. Adding a protocol adds ceremony without benefit. If a second backend is needed (e.g., Chroma, Pinecone), extract the protocol then. "Don't design for hypothetical future requirements."

## References

- Research: [research.md](research.md)
- Tasks: [tasks.md](tasks.md)
- Phase 1: [../2026-04-14-phase-1-foundation/](../2026-04-14-phase-1-foundation/)
- Plan: [../../PLAN.md](../../PLAN.md)
- sqlite-vec Python docs: alexgarcia.xyz/sqlite-vec/python.html
