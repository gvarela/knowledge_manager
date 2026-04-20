# km — Semantic Search for Obsidian Vaults

Local-first CLI tool for embedding-based retrieval over markdown vaults. No external services — everything runs on-device using ONNX embeddings and SQLite vector search.

## Quick Start

```bash
# Install
uv tool install /path/to/knowledge-manager

# Index a vault
km index /path/to/vault

# Search
km search "billing roadmap impact"
km search "burnout risk" --top-k 5
km search "who handles infrastructure" --json

# Incremental update after editing files
km update People/Nick/README.md Meetings/2026-04-08.md

# Stats
km stats
```

## What It Does

`km` chunks markdown files, embeds them with `BAAI/bge-small-en-v1.5` (384 dimensions), stores vectors in SQLite via `sqlite-vec`, and retrieves by cosine similarity. Designed for Obsidian vaults consumed by Claude Code skills — `/librarian find` shells out to `km search --json` for semantic matches that keyword search misses.

## CLI Reference

| Command | Description |
|---------|-------------|
| `km index [path]` | Full index (with path = first run; without = re-index) |
| `km search <query> [--top-k N] [--dir DIR]` | Semantic search, ranked by distance |
| `km update <paths...>` | Re-index specific files (~2s per file) |
| `km stats` | File and chunk counts |
| `km config show` | Dump resolved config |
| `km config get <file>` | Show resolved config for a specific file |
| `km config set <pattern> k=v...` | Add/update config override |
| `km prime` | Output context for Claude Code hooks |

`--json` flag on all commands for machine-parseable output. Place after the subcommand: `km search "query" --json`.

## The `.km/` Directory

Everything lives at `<vault-root>/.km/` — auto-discovered by walking parent directories (same pattern as `.git/`).

```
.km/
├── config.toml    # chunking rules, scan filters, per-directory overrides
├── index.db       # sqlite-vec database (chunks + embeddings)
└── models/        # cached embedding model (~45MB, downloaded on first run)
```

### Configuration

Generated on first `km index`. Vault-specific chunking rules:

```toml
[defaults]
split_on = ["h1", "h2"]
strip_frontmatter = true
min_chunk_chars = 200

[scan]
include = ["**/*.md"]
exclude_dotdirs = true

[[overrides]]
files = "Memory/**"
strategy = "atomic"       # never split — already distilled

[[overrides]]
files = "Templates/**"
index = false             # skip entirely
```

Manage without editing TOML:

```bash
km config set "Memory/**" strategy=atomic
km config set defaults min_chunk_chars=200
km config get "Daily/2026-04-14.md"
```

## Claude Code Integration

`km prime` outputs a markdown context block for Claude Code hooks, following the same pattern as `bd prime` from beads. Add to SessionStart and PreCompact hooks so Claude always knows `km` is available.

See `.km/SETUP.md` in your vault for the full integration checklist (permissions, hooks, skill updates).

## Architecture

826 lines of source across 8 modules. Flat package, strict import DAG:

```
__init__.py   → defines Chunk, ChunkConfig, ScanConfig, VaultConfig
config.py     → loads .km/config.toml, resolves per-file overrides
chunker.py    → markdown splitting driven by ChunkConfig
store.py      → sqlite-vec storage (insert, upsert, KNN search, stats)
embedder.py   → fastembed adapter (no km imports — plain strings in/out)
search.py     → orchestration (Searcher: index_vault, update_files, search)
cli.py        → thin argparse shell (parse, dispatch, format)
__main__.py   → python -m km entry point
```

## Development

```bash
uv run pytest -m "not slow" --tb=short -q -x   # fast TDD loop (70 tests, <1s)
uv run pytest                                    # full suite (72 tests, includes slow)
uv run ruff check . && uv run ruff format .      # lint + format
```

Built with Kent Beck's TDD across 4 phases, 12 commits. See `PLAN.md` for the full build sequence.

## Stack

- **Python >=3.12** with `argparse` (stdlib)
- **fastembed** — ONNX embeddings, no PyTorch (~200MB install)
- **sqlite-vec** — SQLite extension for vector KNN search
- **tomli-w** — TOML writing for `km config set`
- **uv** + **hatchling** — packaging (`uv tool install .` puts `km` on PATH)
- **ruff** — linting + formatting
- **pytest** — testing with `@pytest.mark.slow` for model-download tests
