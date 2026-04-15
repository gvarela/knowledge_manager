---
project: phase-2-storage
ticket: null
created: 2026-04-14
created_timestamp: 2026-04-14T23:22:02Z
status: complete
last_updated: 2026-04-14
researcher: gvarela
git_commit: 327cc07
git_branch: main
repository: knowledge-manager
tags: [research, codebase, phase-2-storage]
---

# Research: Phase 2 Storage

**Created**: 2026-04-14 23:22 UTC
**Last Updated**: 2026-04-14
**Ticket**: N/A

## Research Question

What does the km codebase currently provide from Phase 1, what does sqlite-vec require for integration, and what are the concrete API patterns for building the Store class (schema, insert, bulk insert, KNN search, upsert by file_path, clear, stats)?

## Summary

Phase 1 is complete with 13 passing tests, a `Chunk` frozen dataclass, config-driven chunking, and vault scanning. `src/km/store.py` is an empty file — the first runtime dependency (`sqlite-vec`) needs to be added to `pyproject.toml`. sqlite-vec v0.1.9 provides a `vec0` virtual table extension for SQLite with brute-force exact KNN search via the `MATCH` operator. It loads as a Python extension via `sqlite_vec.load(db)` and stores vectors as compact float32 BLOBs. The recommended pattern is a regular `chunks` table (metadata + content) joined to a `vec_chunks` virtual table (vectors only) via `rowid`. For ~1500 chunks at 384 dimensions, brute-force KNN is adequate (~2.3MB of vectors).

## Detailed Findings

### Current Codebase State (Phase 1 Complete)

**`src/km/__init__.py:29-38`** — `Chunk` dataclass (frozen, slots):

```python
@dataclass(frozen=True, slots=True)
class Chunk:
    file_path: str        # vault-relative path
    section_header: str   # "## Section" or "" for preamble/atomic
    content: str          # full text including header
    directory: str        # derived from file_path via PurePosixPath
```

`directory` is computed in `__post_init__` — `parts[0]` for nested files, `""` for root files.

**`src/km/store.py`** — completely empty (0 bytes). Per the import DAG in CLAUDE.md, it imports only `Chunk` from `km.__init__`.

**`pyproject.toml:6`** — `dependencies = []`. No runtime deps yet.

**Tests** — 13 total: 10 in `tests/test_chunker.py`, 3 in `tests/test_config.py`. No `@pytest.mark.slow` markers. `tests/conftest.py` is empty (0 bytes).

**Import DAG position for store.py**:
```
store.py  → __init__ (Chunk)
search.py → config, chunker, store, embedder, __init__
```

### sqlite-vec Package

**Version**: 0.1.9 (2026-03-31). MIT/Apache-2.0 dual-licensed.

**Installation**: `pip install sqlite-vec` (pre-built wheels for Linux x86-64/ARM64, macOS ARM64/x86-64, Windows x86-64).

**Loading the extension**:

```python
import sqlite3
import sqlite_vec

db = sqlite3.connect(".km/index.db")
db.enable_load_extension(True)
sqlite_vec.load(db)
db.enable_load_extension(False)
```

`sqlite_vec.load(db)` handles locating and loading the correct platform-specific shared library.

**macOS gotcha**: The system Python's sqlite3 may not support `enable_load_extension`. This project uses uv-managed Python 3.13 which should have extension loading compiled in. PLAN.md notes: verify with `python3 -c "import sqlite3; c = sqlite3.connect(':memory:'); c.enable_load_extension(True)"`.

### sqlite-vec Schema Patterns

**Two-table pattern (recommended for this project)**:

```sql
-- Metadata + content
CREATE TABLE IF NOT EXISTS chunks (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path  TEXT NOT NULL,
    heading    TEXT,
    content    TEXT NOT NULL
);

-- Vector index: rowid matches chunks.id
CREATE VIRTUAL TABLE IF NOT EXISTS vec_chunks USING vec0(
    embedding float[384]
);
```

`chunks.id` and `vec_chunks.rowid` are the foreign key. Insert into `chunks` first to get the `lastrowid`, then insert into `vec_chunks` with that same rowid.

**Alternative: auxiliary columns** (v0.1.6+) — prefix columns with `+` to store alongside vectors without indexing:

```sql
CREATE VIRTUAL TABLE IF NOT EXISTS vec_chunks USING vec0(
    chunk_id  INTEGER PRIMARY KEY,
    embedding float[384],
    +file_path TEXT,
    +heading   TEXT,
    +content   TEXT
);
```

Eliminates JOINs at the cost of denormalization. Auxiliary columns cannot appear in WHERE clauses.

**Distance metrics**: Default is L2 (Euclidean). Cosine distance is set at table creation: `embedding float[384] distance_metric=cosine`. Cannot be changed after creation without rebuilding.

### Vector Serialization

**`sqlite_vec.serialize_float32()`** — converts a Python list of floats to a compact binary BLOB:

```python
from sqlite_vec import serialize_float32

blob = serialize_float32([0.1, 0.2, 0.3, ...])  # returns bytes
```

Equivalent manual approach:

```python
import struct
def serialize_f32(vector: list[float]) -> bytes:
    return struct.pack("%sf" % len(vector), *vector)
```

JSON float arrays also work as strings for ad-hoc SQL, but the binary form is faster for bulk loads.

### KNN Query Pattern

```python
query_blob = serialize_float32(query_embedding)

rows = db.execute("""
    SELECT c.id, c.file_path, c.heading, c.content, v.distance
    FROM vec_chunks v
    JOIN chunks c ON c.id = v.rowid
    WHERE v.embedding MATCH ?
      AND v.k = ?
    ORDER BY v.distance
""", [query_blob, k]).fetchall()
```

- `MATCH` triggers the KNN search on the virtual table
- `k = N` sets the result count (use this instead of `LIMIT` for SQLite < 3.41 compatibility)
- `ORDER BY distance` is required for deterministic ordering
- `distance` is a virtual column exposed by vec0

### Insert Pattern

```python
def insert_chunk(db, file_path, heading, content, embedding):
    cur = db.execute(
        "INSERT INTO chunks(file_path, heading, content) VALUES (?, ?, ?)",
        [file_path, heading, content]
    )
    chunk_id = cur.lastrowid
    db.execute(
        "INSERT INTO vec_chunks(rowid, embedding) VALUES (?, ?)",
        [chunk_id, serialize_float32(embedding)]
    )
    return chunk_id
```

Insert order matters: content table first (to get rowid), then vector table.

### Upsert Pattern (delete + re-insert by file_path)

sqlite-vec does not support UPDATE on vec0 virtual tables. The upsert pattern for `km update` is:

1. Find all chunk IDs for the file: `SELECT id FROM chunks WHERE file_path = ?`
2. Delete from vec_chunks: `DELETE FROM vec_chunks WHERE rowid IN (...)`
3. Delete from chunks: `DELETE FROM chunks WHERE file_path = ?`
4. Re-insert new chunks and vectors

This is the pattern PLAN.md specifies: "Store supports upsert by file_path: delete all chunks for that path, then insert new ones."

### Utility Functions

| Function | Purpose |
|---|---|
| `vec_version()` | Returns extension version string |
| `vec_length(blob)` | Returns dimension count of a vector |
| `vec_to_json(blob)` | Converts binary vector to JSON array string |
| `vec_distance_L2(a, b)` | Euclidean distance (manual, no index) |
| `vec_distance_cosine(a, b)` | Cosine distance (manual, no index) |

### Performance Characteristics

- vec0 is **brute-force exact KNN** — no approximate nearest neighbor index
- For ~1500 chunks at 384 dims: ~2.3MB of vectors, queries are fast
- All queries are exact — no accuracy tradeoffs
- Good for the scale of Main/ vault (603 files, ~1500 expected chunks)

## Architecture Documentation

**Current patterns**:

- All dataclasses in `__init__.py` are `frozen=True, slots=True`
- Config types are separate from domain types (ChunkConfig vs Chunk)
- Functions receive resolved config as parameters, never load config themselves
- Import DAG is strictly enforced: `store.py → __init__` only

**The Store's position in the DAG**:

```
__init__.py   (Chunk — store needs this)
store.py      (sqlite3 + sqlite_vec — receives Chunk, returns Chunk)
search.py     (composes store + embedder + chunker)
```

Store is a leaf in the DAG — it depends only on `__init__.py` types. It does not know about config, chunker, or embedder. It receives `Chunk` objects and float vectors; it returns `Chunk` objects and distances.

**Testing patterns established in Phase 1**:

- Tests use `tmp_path` fixture for filesystem isolation
- No fixtures in conftest.py yet (empty)
- Each test constructs its own config/input — no shared state
- All tests are fast (<1s total, no `@pytest.mark.slow`)

## Code References

- `src/km/__init__.py:29-38` — Chunk dataclass definition
- `src/km/__init__.py:8-13` — ChunkConfig definition (min_chunk_chars default=0)
- `src/km/store.py` — empty, target file for Phase 2
- `src/km/chunker.py:39` — `chunk_markdown()` signature
- `src/km/config.py:8` — `load_config()` signature
- `src/km/config.py:44` — `resolve_for_file()` signature
- `pyproject.toml:6` — `dependencies = []`
- `CLAUDE.md:14-21` — import DAG specification
- `PLAN.md:268-278` — Phase 2 TDD steps 14-18
- `PLAN.md:314` — "sqlite-vec serialization: Query vectors via sqlite_vec.serialize_float32()"

## PLAN.md Phase 2 Specification

From `PLAN.md:211-216`:

> ### Phase 2: Storage (steps 14-18)
> sqlite-vec store with full CRUD + vector search.
> - Schema, insert, bulk insert, KNN search, upsert by file_path, clear, stats
> - **Milestone:** can store fake vectors and get nearest-neighbor results back

TDD steps from `PLAN.md:272-278`:

| Step | Test | What it proves |
|------|------|---------------|
| 14 | `test_create_store_and_insert_chunk` | Schema creation, single insert |
| 15 | `test_bulk_insert_and_stats` | Batch insert, file/chunk counts |
| 16 | `test_knn_search_returns_nearest` | Vector search via sqlite-vec MATCH |
| 17 | `test_upsert_replaces_chunks_for_file` | Delete old chunks for a file_path, insert new ones |
| 18 | `test_clear_removes_all_data` | Full rebuild support |

Design decisions from `PLAN.md:310-314`:
- 384 dimensions (bge-small-en-v1.5)
- sqlite-vec serialization via `sqlite_vec.serialize_float32()`
- Incremental-first: upsert by file_path is the steady-state operation

## Open Questions

None blocking. All sqlite-vec API patterns are well-documented and straightforward for this scale.

## Next Steps

1. Review this research
2. Run `/wb:create_design docs/plans/2026-04-14-phase-2-storage` to finalize design decisions
3. Begin TDD implementation (steps 14-18)

## References

- Design: [design.md](design.md)
- Tasks: [tasks.md](tasks.md)
- Phase 1: [../2026-04-14-phase-1-foundation/](../2026-04-14-phase-1-foundation/)
- Plan: [../../PLAN.md](../../PLAN.md)
- sqlite-vec docs: alexgarcia.xyz/sqlite-vec/python.html
- sqlite-vec PyPI: pypi.org/project/sqlite-vec/
- sqlite-vec GitHub: github.com/asg017/sqlite-vec
