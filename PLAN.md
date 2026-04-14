# km — Embedding Search for Main/ Vault

## Problem

Main/ has 603 markdown files (~530K words) across People/ (197), Meetings/ (126), Daily/ (53), Thinking/ (48), etc. The `/librarian find` skill does keyword search (grep/glob) which misses semantic matches — "struggling with scope creep" won't surface on a search for "requirements discipline." This repo builds a CLI tool that Main/ skills shell out to for embedding-based retrieval.

## Stack

- **Python >=3.12** with `argparse` (stdlib)
- **fastembed** — ONNX-based embeddings, no PyTorch (~200MB install), model: `BAAI/bge-small-en-v1.5` (384 dims, ~45MB)
- **sqlite-vec** — SQLite extension for vector search, single-file DB
- **uv** — package/project manager (venv, deps, lockfile, `uv run`)
- **hatchling** — build backend (for `uv tool install` to put `km` on PATH)
- **ruff** — linting + formatting
- **pytest** — testing, with `@pytest.mark.slow` for model-download tests
- No external services. Everything local.

### Tooling Details

**Development:** `uv run pytest -m "not slow"` (fast TDD loop), `uv run pytest` (full suite), `uv run ruff check .`, `uv run ruff format .`

**Installation for Main/:** `uv tool install /path/to/knowledge-manager` puts `km` on PATH. Main/ skills call `km search "query"` directly — no venv activation, no `uv run`.

**Ruff config:**

```toml
[tool.ruff]
target-version = "py312"
src = ["src"]

[tool.ruff.lint]
select = ["E", "F", "I", "N", "UP", "B", "SIM", "RUF"]

[tool.ruff.format]
quote-style = "double"
```

**Pytest config:**

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
markers = ["slow: tests that download models or hit disk heavily"]
```

## Package Structure

```
knowledge-manager/
├── pyproject.toml
├── PLAN.md
├── src/
│   └── km/
│       ├── __init__.py      # Chunk, ChunkConfig, ScanConfig, VaultConfig, __version__
│       ├── __main__.py      # python -m km → cli.main()
│       ├── config.py        # load_config(), resolve_for_file(), defaults
│       ├── chunker.py       # chunk_markdown(text, file_path, config), scan_vault()
│       ├── embedder.py      # Embedder class (plain types in/out, no km imports)
│       ├── store.py         # Store class: schema, upsert, knn_search, stats, clear
│       ├── search.py        # Searcher class, SearchResult dataclass
│       └── cli.py           # thin argparse shell → Searcher methods
└── tests/
    ├── __init__.py
    ├── conftest.py          # shared fixtures (tmp_path DB, sample markdown)
    ├── test_config.py
    ├── test_chunker.py
    ├── test_embedder.py
    ├── test_store.py
    ├── test_search.py
    └── test_cli.py
```

### Architecture Principles

**Flat modules, strict import DAG.** At ~400 lines and 6 modules, subdirectories add ceremony without navigational benefit. The hexagonal pattern is honored through import discipline, not directory hierarchy.

```
__init__.py   → (nothing from km — root of the DAG, never creates cycles)
config.py     → __init__ (ChunkConfig, ScanConfig, VaultConfig)
chunker.py    → __init__ (Chunk, ChunkConfig, ScanConfig)
store.py      → __init__ (Chunk)
embedder.py   → (nothing from km — takes/returns plain strings and float lists)
search.py     → config, chunker, store, embedder, __init__ (Chunk)
cli.py        → search, config
__main__.py   → cli
```

**Key rules:**
- `__init__.py` never imports from `km.*` — it defines shared types (`Chunk`, `ChunkConfig`, `ScanConfig`, `VaultConfig`) and constants. Exports via `__all__`.
- `config.py` loads `.km/config.toml`, returns `VaultConfig` (wraps `ChunkConfig` + `ScanConfig`). `resolve_for_file()` returns a resolved `ChunkConfig` per file. Only `search.py` and `cli.py` call it.
- `chunker.py` receives `ChunkConfig` as a parameter — it never loads config itself
- `embedder.py` is infrastructure-agnostic to km types — takes strings, returns float lists
- `SearchResult` lives in `search.py` (its only producer)
- `cli.py` is a thin shell: parse args, load config, construct Searcher, call methods, format output

**When to evolve:**
| Trigger | Action |
|---------|--------|
| Multiple embedding models | Constructor param on `Embedder` (already supports this); add `EmbedderProtocol` to `__init__` if needed |
| Complex ranking/filtering | Extract `km/ranking.py`, imported by `search.py` |
| 10+ modules, unclear navigation | Introduce `km/core/` and `km/adapters/` subdirectories. Not before. |

## The .km/ Directory

Everything km-related lives at `<vault-root>/.km/` — same pattern as `.beads/` and `.git/`.

```
.km/
├── config.toml    # chunking rules, scan filters, per-directory overrides
└── index.db       # sqlite-vec database (chunks + embeddings)
```

Created by `km index`. Auto-discovered by walking parent directories.

### config.toml

Generated with comments on first `km index`. Vault-specific chunking rules live here, not in km's code.

```toml
# km configuration for this vault
# Overrides apply in order — later entries win for matching files

[defaults]
split_on = ["h1", "h2"]       # header levels that trigger chunk splits
strip_frontmatter = true       # remove YAML --- blocks before chunking
min_chunk_chars = 200          # sections shorter than this stay as one chunk

[scan]
include = ["**/*.md"]
exclude_dotdirs = true            # exclude all directories starting with "." (.obsidian, .beads, .km, etc.)

# Per-directory overrides using glob patterns:
# [[overrides]]
# files = "Memory/**"
# strategy = "atomic"          # "atomic" = never split, "default" = apply split rules
#
# [[overrides]]
# files = "Daily/**"
# strategy = "atomic"
#
# [[overrides]]
# files = ["Inbox/processed/**"]
# index = false                # skip these files entirely
```

### Ergonomics for LLM callers (matching `bd` pattern)

```bash
km index .                              # first run, creates .km/ with config.toml
km search "billing roadmap"             # auto-discovers .km/ from cwd
km update People/Nick/README.md         # paths relative to vault root
km stats                                # no flags needed
km config show                          # print resolved config
km config set "Memory/**" strategy=atomic   # add/update an override
km config get "Daily/2026-04-14.md"     # show resolved config for a file
```

The `config` subcommand lets Claude skills inspect and modify chunking rules without parsing TOML directly.

## Chunking Strategy

Config-driven. km ships defaults; vaults override via `.km/config.toml`.

**Built-in defaults (no config file needed):**
- Split on H1 and H2 headers
- Strip YAML frontmatter
- Content <200 chars stays as single chunk
- Include `**/*.md`, exclude all directories starting with `.` (covers .obsidian, .beads, .km, .git, .claude, .trash)

**Strategies:**
- `"default"` — apply split_on rules, frontmatter stripping, min_chunk_chars threshold
- `"atomic"` — entire file is one chunk, no splitting

**Chunker API:** `chunk_markdown(text, file_path, config: ChunkConfig) -> list[Chunk]`

The chunker receives resolved config per-file. It never reads config files or knows about `.km/`.

## Incremental Updates

The vault changes ~15% per week (91/603 files). Content enters through `/capture` → `/process`, `/notes`, `/inbox` — all converging on the State Update Rule which writes 6-7 files per conversation. The embedding index must stay current within a session.

`km update` takes file paths (relative to vault root), deletes their existing chunks, re-chunks, re-embeds, and upserts. `/process` and other skills call this after writing state updates — same pattern as inline YAML index updates. ~1-2 seconds for 6-7 files.

`km index` is for first run or full rebuild. `km update` is the steady-state operation.

## Search Output

```
[0.82] People/Bob/README.md
  > Bob leads the infrastructure team and manages cloud deployments.

[0.79] Meetings/2024-03-15-infra-review.md :: ## Decisions
  > Decided to migrate DNS to new provider. Bob to lead.
```

`--json` for machine-readable output when `/librarian find` parses it.

## Development Phases

### Phase 1: Foundation (steps 0-13)

Project skeleton + tooling + config + chunker. Pure Python, zero runtime deps. `dependencies = []` in pyproject.toml — fastembed and sqlite-vec added in their respective phases.

- pyproject.toml, uv, ruff, pytest all wired up
- Config loading from `.km/config.toml` with defaults and glob overrides
- VaultConfig, ChunkConfig, ScanConfig, Chunk dataclasses
- `chunk_markdown()` driven by ChunkConfig, `scan_vault()` driven by ScanConfig
- Edge cases: empty files, frontmatter-only, preamble before headers, min_chunk_chars
- **Milestone:** can chunk any vault directory with config-driven rules

### Phase 2: Storage (steps 14-18)

sqlite-vec store with full CRUD + vector search.

- Schema, insert, bulk insert, KNN search, upsert by file_path, clear, stats
- **Milestone:** can store fake vectors and get nearest-neighbor results back

### Phase 3: Embedding + Search (steps 19-22)

fastembed wrapper and orchestration layer.

- Embedder class, Searcher class, SearchResult dataclass
- Full index pipeline and incremental update
- **Milestone:** can index a directory of markdown files and search semantically

### Phase 4: CLI (steps 23-24)

Usable standalone tool.

- argparse with `index`, `update`, `search`, `stats`, `config` subcommands
- Auto-discovery of `.km/`
- `config show/set/get` for LLM-friendly config management
- JSON output mode
- **Milestone:** `km` works as a standalone command, installable via `uv tool install`

### Phase 5: Real-world validation (no TDD steps — manual)

Index Main/, test against actual queries.

- `km index /Users/gvarela/Obsidian/Main`
- Run searches that `/librarian find` currently misses
- Tune chunking or search params based on results
- **Milestone:** ready for skill integration

## TDD Build Sequence

Each step = one red/green/refactor cycle, one commit.

### Phase 1 — Steps 0-13: Config + Chunker (pure Python, zero deps)

| Step | Test | What it proves |
|------|------|---------------|
| 0 | (no test — project skeleton) | pyproject.toml, uv sync, ruff, pytest all working |
| 1 | `test_default_config_without_file` | VaultConfig with ChunkConfig/ScanConfig defaults, no config.toml needed |
| 2 | `test_load_config_from_toml` | Parses .km/config.toml into typed VaultConfig |
| 3 | `test_override_resolution` | Glob overrides merge correctly per-file (PurePosixPath.match) |
| 4 | `test_single_paragraph_returns_one_chunk` | Chunk dataclass, frozen+slots, directory derived from file_path |
| 5 | `test_splits_on_h2_headers` | Section-based splitting with default config |
| 6 | `test_splits_on_h1_and_h2` | Mixed header levels handled |
| 7 | `test_preamble_before_first_header` | Text before any header becomes its own chunk |
| 8 | `test_strips_yaml_frontmatter` | Frontmatter removed from content (regex handles optional trailing newline) |
| 9 | `test_frontmatter_only_returns_empty` | File with only frontmatter and no body returns [] |
| 10 | `test_empty_file_returns_empty` | Empty or whitespace-only input returns [] |
| 11 | `test_short_sections_stay_as_single_chunk` | min_chunk_chars threshold keeps short content as one chunk |
| 12 | `test_atomic_strategy_returns_single_chunk` | Config strategy="atomic" skips splitting |
| 13 | `test_scan_vault_finds_markdown_files` | Vault scanner respects ScanConfig, excludes dotdirs |

### Phase 2 — Steps 14-18: Store (sqlite-vec)

Add `sqlite-vec` to dependencies at start of Phase 2.

| Step | Test | What it proves |
|------|------|---------------|
| 14 | `test_create_store_and_insert_chunk` | Schema creation, single insert |
| 15 | `test_bulk_insert_and_stats` | Batch insert, file/chunk counts |
| 16 | `test_knn_search_returns_nearest` | Vector search via sqlite-vec MATCH |
| 17 | `test_upsert_replaces_chunks_for_file` | Delete old chunks for a file_path, insert new ones |
| 18 | `test_clear_removes_all_data` | Full rebuild support |

### Phase 3 — Step 19: Embedder (fastembed)

Add `fastembed` to dependencies at start of Phase 3.

| Step | Test | What it proves |
|------|------|---------------|
| 19 | `test_embed_single_text` | fastembed wrapper works, correct dimensions |

Mark `@pytest.mark.slow` — downloads model on first run.

### Phase 3 — Steps 20-22: Search (composition)

| Step | Test | What it proves |
|------|------|---------------|
| 20 | `test_search_end_to_end` | Searcher orchestrates embed → store → results (mock embedder) |
| 21 | `test_index_vault` | Full pipeline: scan → chunk → embed → store (loads config, filters index=false) |
| 22 | `test_update_files` | Incremental: update specific files without full re-index |

### Phase 4 — Steps 23-24: CLI

Add `tomli-w` to dependencies for `km config set` (TOML writing).

| Step | Test | What it proves |
|------|------|---------------|
| 23 | `test_cli_index_search_update` | index/search/update/stats subcommands work end-to-end |
| 24 | `test_cli_config` | config show/set/get subcommands work |

## Design Decisions

1. **Config-driven chunking.** Vault-specific rules live in `.km/config.toml`, not in km's code. Defaults + glob-based overrides (Prettier model). The chunker receives resolved config as a parameter — it never reads config files.
2. **Incremental-first.** `km update` (upsert specific files) is the steady-state operation; `km index` (full rebuild) is for first run or recovery. Store supports upsert by file_path: delete all chunks for that path, then insert new ones.
3. **384 dimensions.** `bge-small-en-v1.5` is the smallest good-quality English model. 1500 chunks x 384 x 4 bytes = ~2.3MB of vectors.
4. **Everything in `.km/`.** Config + DB together at vault root, alongside `.beads/` and `.git/`. Auto-discovered by walking parent directories. Skills need no path flags.
5. **LLM-friendly config CLI.** `km config show/set/get` lets Claude skills manage chunking rules without parsing TOML.
6. **sqlite-vec serialization.** Query vectors via `sqlite_vec.serialize_float32()`. Virtual table handles storage vectors on insert.
7. **Flat modules, strict DAG.** Subdirectories at ~10+ modules, not before. Hexagonal architecture via import discipline.

## Gotchas

- **sqlite-vec + Python**: needs `ENABLE_LOAD_EXTENSION` in Python's sqlite3 module. Verify: `python3 -c "import sqlite3; c = sqlite3.connect(':memory:'); c.enable_load_extension(True)"`
- **fastembed first-run**: downloads ~45MB model on first `embed()` call.
- **Frontmatter parsing**: regex `r'^---\n.*?\n---\n?'` with `re.DOTALL` — trailing newline optional to handle frontmatter-only files. No extra dependency.
- **Config writing**: `tomllib` (stdlib) is read-only. `km config set` (Phase 4) will need `tomli-w` as a dependency for TOML writing.
- **Glob semantics**: Config uses `PurePosixPath.match()` (Python 3.12+), which handles `**` for recursive matching and `*` for single-directory matching. Not `fnmatch`.
- **Symlinks**: Not followed. `scan_vault` uses `Path.rglob()` default behavior. Circular symlinks would cause infinite loops otherwise.
- **`index = false` overrides**: Filtered post-scan by the Searcher, not by `scan_vault`. scan returns all .md candidates; the indexing loop skips files where resolved config has `index = false`.

## Verification

After all steps:

```bash
# Fast TDD loop
uv run pytest -m "not slow"

# Full suite
uv run pytest

# First index
km index /Users/gvarela/Obsidian/Main

# Search
km search "who handles infrastructure"
km search "burnout risk" --top-k 5
km search "billing roadmap impact from departures" --json

# Incremental update after a session
km update People/Nick/README.md People/Nick/2026-04-14.md
km search "Nick billing work"

# Stats
km stats
```

## Future (not in scope)

- Golden dataset evaluation (measure where keyword search fails, benchmark embedding search)
- Integration into `/librarian find` (modify SKILL.md to shell out to `km search`)
- Integration into `/process` State Update Rule (call `km update` on written files)
- `/reindex` calling `km index` alongside YAML index regeneration
- `/dream` calling `km update` on extracted Memory/ notes
