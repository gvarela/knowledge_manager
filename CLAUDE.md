# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

`km` — a local-first CLI tool for semantic search over an Obsidian vault (~600 markdown files). Consumed by the Main/ vault's Claude assistant skills (e.g., `/librarian find` shells out to `km search`). Runtime deps: `fastembed` (ONNX embeddings) and `sqlite-vec` (vector search in SQLite). No external services.

## Commands

```bash
uv run pytest -m "not slow"       # fast TDD loop (skips model-download tests)
uv run pytest                      # full suite including @pytest.mark.slow
uv run ruff check .                # lint
uv run ruff format .               # format
uv run pytest --tb=short -q -x     # single-test-at-a-time TDD (stop on first failure)
```

Install as CLI: `uv tool install .` then `km search "query"` works globally.

## Architecture

Flat `src/km/` package with strict import DAG — no circular dependencies by design:

```
__init__.py   → (nothing from km — defines Chunk, ChunkConfig, ScanConfig, VaultConfig, constants)
config.py     → __init__ (ChunkConfig, ScanConfig, VaultConfig)
chunker.py    → __init__ (Chunk, ChunkConfig, ScanConfig)
store.py      → __init__ (Chunk)
embedder.py   → (nothing from km — plain strings/floats in and out)
search.py     → config, chunker, store, embedder, __init__
cli.py        → search, config, store, __init__ (+ tomllib, tomli_w for config set)
__main__.py   → cli
```

`config.py` loads `.km/config.toml` and resolves per-file overrides into typed dataclasses (`VaultConfig` wraps `ChunkConfig` + `ScanConfig`). The chunker receives config as a parameter — it never reads config files. This keeps vault-specific rules (e.g., "Memory/ is atomic") in the vault's config, not in km's code. Glob matching uses `PurePosixPath.match()` (not `fnmatch`).

`embedder.py` deliberately has no `km` imports — it takes strings and returns float lists, keeping the fastembed adapter swappable without touching domain types.

`cli.py` is a thin argparse shell with 7 subcommands: `index`, `search` (`--top-k`, `--dir`), `update`, `sync`, `stats`, `prime`, `config` (show/set/get). All logic lives in `search.py` (orchestration) or below. `km prime` outputs markdown context for Claude Code hooks (SessionStart/PreCompact) — same pattern as `bd prime`. `km sync` diffs the vault filesystem against the store to handle adds/deletes/moves.

## .km/ Directory and Auto-Discovery

Everything km-related lives at `<vault-root>/.km/`: `config.toml` (chunking rules) + `index.db` (vectors). `km` walks parent directories to find `.km/` (same pattern as `.git/` and `.beads/`). Skills call `km search "query" --json` from the vault root. `km config show/set/get` lets LLMs manage config without parsing TOML. `--json` goes after the subcommand (e.g., `km stats --json`), not before.

## Development Methodology

Follow Kent Beck's TDD: red (failing test) → green (minimal passing code) → refactor. One test at a time. Separate structural changes (refactoring) from behavioral changes (features) in commits. Run all fast tests after every change. See PLAN.md for the step-by-step build sequence.

## Key Constraints

- Python >=3.12, target `ruff` version `py312`
- `__init__.py` must never import from `km.*` modules — exports via `__all__`
- Dependencies added per-phase: Phase 1 has `dependencies = []`, Phase 2 adds `sqlite-vec`, Phase 3 adds `fastembed`, Phase 4 adds `tomli-w`
- Introduce subdirectories only at 10+ modules — not before
- `@pytest.mark.slow` on any test that downloads models or takes >2s
- Glob matching uses `PurePosixPath.match()`, not `fnmatch` — `**` means recursive, `*` means single directory
- Frontmatter regex: `r'^---\n.*?\n---\n?'` with `re.DOTALL` — trailing newline optional
- CLI tests use `monkeypatch.setattr(sys, "argv", [...])` + `capsys` to test `main()` in-process. Inject `ConstantEmbedder` via `monkeypatch.setattr("km.search.Searcher.__init__", ...)` to avoid model downloads.
