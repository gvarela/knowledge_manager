---
project: phase-2-storage
ticket: null
created: 2026-04-14
created_timestamp: 2026-04-14T23:22:02Z
status: in-progress
last_updated: 2026-04-14
assignee: gvarela
current_phase: 1
total_tasks: 6
completed_tasks: 0
git_commit: 327cc07
git_branch: main
repository: knowledge-manager
tags: [tasks, tracking, phase-2-storage]
beads_epic: km-16w
beads_tasks:
  add_dep: km-5td
  store_insert: km-qdt
  bulk_stats: km-b6y
  knn_search: km-zwa
  upsert_file: km-q28
  clear: km-x87
---

# Execution Plan: Phase 2 Storage

## Overview

Implementing sqlite-vec backed Store class as specified in design.md.

**Design Approach**: Two-table schema (chunks + vec_chunks) with Store class
**Target State**: `Store` class supports insert, bulk_insert, knn_search, upsert_file, clear, stats with fake vectors in tests

## Implementation Strategy

### Dependency Graph

```
add_dep (add sqlite-vec to pyproject.toml)
  └── store_insert (schema + single insert)
        └── bulk_stats (batch insert + stats)
              └── knn_search (KNN via MATCH)
                    └── upsert_file (delete + re-insert by file_path)
                          └── clear (remove all data)
```

Linear chain — each step builds on the previous. No parallel work opportunities within Phase 2.

### Testing Strategy

TDD: write failing test first, implement minimum to pass, refactor. Run `uv run pytest -m "not slow"` after every change. All Phase 2 tests use fake embeddings (random `list[float]` of length 384) and `tmp_path` databases. No `@pytest.mark.slow` needed.

---

## Step 0: Add sqlite-vec Dependency

**Beads**: `km-5td` | **Priority**: P1 | **Blocks**: everything

### What to Build

Add `sqlite-vec` to `pyproject.toml` dependencies and verify it loads.

**pyproject.toml change**: `dependencies = []` → `dependencies = ["sqlite-vec"]`

**Verification**:

```bash
uv sync
uv run python -c "import sqlite3, sqlite_vec; db = sqlite3.connect(':memory:'); db.enable_load_extension(True); sqlite_vec.load(db); print(db.execute('select vec_version()').fetchone())"
```

**Commit**: `chore: add sqlite-vec dependency`

---

## Steps 1-5: Store Module

### Step 1: Schema Creation and Single Insert

**Beads**: `km-qdt` | **Depends on**: `km-5td`

**Test** (`tests/test_store.py`):

```python
from km import Chunk
from km.store import Store


def test_create_store_and_insert_chunk(tmp_path):
    db_path = tmp_path / "index.db"
    store = Store(db_path)
    chunk = Chunk(file_path="People/alice.md", section_header="## Notes", content="Alice is kind.")
    embedding = [0.1] * 384
    chunk_id = store.insert(chunk, embedding)
    assert chunk_id == 1
    assert store.stats() == {"files": 1, "chunks": 1}
    store.close()
```

**Implementation**: `Store.__init__` creates connection, loads sqlite-vec, creates schema. `Store.insert` inserts into chunks table (gets lastrowid), then into vec_chunks. `Store.stats` queries chunk counts. `Store.close` closes connection.

**Commit**: `feat: Store class with schema creation and single insert`

### Step 2: Bulk Insert and Stats

**Beads**: `km-b6y` | **Depends on**: `km-qdt`

**Test**:

```python
def test_bulk_insert_and_stats(tmp_path):
    db_path = tmp_path / "index.db"
    store = Store(db_path)
    items = [
        (Chunk(file_path="People/alice.md", section_header="## Notes", content="Alice."), [0.1] * 384),
        (Chunk(file_path="People/alice.md", section_header="## Actions", content="Follow up."), [0.2] * 384),
        (Chunk(file_path="Meetings/standup.md", section_header="", content="Daily standup."), [0.3] * 384),
    ]
    store.bulk_insert(items)
    stats = store.stats()
    assert stats["files"] == 2
    assert stats["chunks"] == 3
    store.close()
```

**Implementation**: `Store.bulk_insert` wraps multiple inserts in a single transaction.

**Commit**: `feat: bulk insert and stats reporting`

### Step 3: KNN Search Returns Nearest

**Beads**: `km-zwa` | **Depends on**: `km-b6y`

**Test**:

```python
def test_knn_search_returns_nearest(tmp_path):
    db_path = tmp_path / "index.db"
    store = Store(db_path)
    # Insert chunks with distinct embeddings
    items = [
        (Chunk(file_path="a.md", section_header="", content="Alpha"), [1.0] + [0.0] * 383),
        (Chunk(file_path="b.md", section_header="", content="Beta"), [0.0] + [1.0] + [0.0] * 382),
        (Chunk(file_path="c.md", section_header="", content="Gamma"), [0.9] + [0.1] + [0.0] * 382),
    ]
    store.bulk_insert(items)
    # Query near Alpha's embedding
    results = store.knn_search([1.0] + [0.0] * 383, k=2)
    assert len(results) == 2
    assert results[0][0].content == "Alpha"  # nearest
    assert results[1][0].content == "Gamma"  # second nearest
    # Each result is (Chunk, distance)
    assert results[0][1] < results[1][1]  # distances are ordered
    store.close()
```

**Implementation**: `Store.knn_search` serializes query vector, runs `MATCH` query with JOIN, reconstructs `Chunk` objects from rows.

**Commit**: `feat: KNN search via sqlite-vec MATCH`

### Step 4: Upsert Replaces Chunks for File

**Beads**: `km-q28` | **Depends on**: `km-zwa`

**Test**:

```python
def test_upsert_replaces_chunks_for_file(tmp_path):
    db_path = tmp_path / "index.db"
    store = Store(db_path)
    # Insert initial chunks
    store.bulk_insert([
        (Chunk(file_path="People/alice.md", section_header="## v1", content="Old content."), [0.1] * 384),
        (Chunk(file_path="Meetings/standup.md", section_header="", content="Standup."), [0.2] * 384),
    ])
    assert store.stats() == {"files": 2, "chunks": 2}
    # Upsert: replace alice.md with new chunks
    new_items = [
        (Chunk(file_path="People/alice.md", section_header="## v2", content="New content."), [0.3] * 384),
        (Chunk(file_path="People/alice.md", section_header="## Added", content="Extra section."), [0.4] * 384),
    ]
    store.upsert_file("People/alice.md", new_items)
    stats = store.stats()
    assert stats["files"] == 2   # still 2 files
    assert stats["chunks"] == 3  # 1 standup + 2 new alice
    # Verify old content is gone
    results = store.knn_search([0.1] * 384, k=10)
    contents = [r[0].content for r in results]
    assert "Old content." not in contents
    assert "New content." in contents
    store.close()
```

**Implementation**: `Store.upsert_file` finds chunk IDs for file_path, deletes from vec_chunks and chunks, then bulk-inserts new items. Single transaction.

**Commit**: `feat: upsert replaces chunks for a file_path`

### Step 5: Clear Removes All Data

**Beads**: `km-x87` | **Depends on**: `km-q28`

**Test**:

```python
def test_clear_removes_all_data(tmp_path):
    db_path = tmp_path / "index.db"
    store = Store(db_path)
    store.bulk_insert([
        (Chunk(file_path="a.md", section_header="", content="Alpha"), [0.1] * 384),
        (Chunk(file_path="b.md", section_header="", content="Beta"), [0.2] * 384),
    ])
    assert store.stats()["chunks"] == 2
    store.clear()
    assert store.stats() == {"files": 0, "chunks": 0}
    store.close()
```

**Implementation**: `Store.clear` deletes all rows from both tables.

**Commit**: `feat: Store.clear removes all data for full rebuild`

---

## Verification

After all steps:

```bash
uv run pytest -m "not slow" -v    # all 18+ tests pass (13 Phase 1 + 5 Phase 2)
uv run ruff check .               # clean
uv run ruff format --check .      # clean
```

---

## Beads Issue Tracking

**Epic**: `km-16w` — Phase 2: Storage

| Step | Beads ID | Title |
|------|----------|-------|
| 0 | `km-5td` | Add sqlite-vec dependency |
| 1 | `km-qdt` | Schema creation and single insert |
| 2 | `km-b6y` | Bulk insert and stats |
| 3 | `km-zwa` | KNN search returns nearest |
| 4 | `km-q28` | Upsert replaces chunks for file |
| 5 | `km-x87` | Clear removes all data |

**Commands**:

```bash
bd ready                # see what's unblocked
bd show [id]            # view task details
bd close [id]           # complete a task
bd blocked              # see what's waiting
bd list --status=open   # all open work
```

---

## Quick Reference

### Key Files

- **Research**: [research.md](research.md)
- **Design**: [design.md](design.md)
- **PLAN.md**: [../../PLAN.md](../../PLAN.md)

### Design Decisions Reference

- Two-table schema: `chunks` (metadata) + `vec_chunks` (vectors), linked by rowid
- L2 distance (default) — equivalent to cosine for normalized embeddings
- Store serializes vectors internally via `sqlite_vec.serialize_float32()`
- Upsert = delete all chunks for file_path + re-insert
- WAL mode for concurrent read safety
- store.py imports only `Chunk` from `km.__init__`
