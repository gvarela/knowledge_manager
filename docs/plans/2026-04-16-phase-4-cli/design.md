---
project: phase-4-cli
ticket: null
created: 2026-04-16
created_timestamp: 2026-04-16T20:00:00Z
status: draft
last_updated: 2026-04-16
designer: gvarela
git_commit: d385d73
git_branch: main
repository: knowledge-manager
tags: [design, architecture, phase-4-cli]
depends_on: research.md
design_approach: thin-argparse-shell
---

# Design: Phase 4 — CLI

**Created**: 2026-04-16
**Designer**: gvarela
**Ticket**: N/A
**Status**: Draft

## Problem Statement

The `km` pipeline (chunk, embed, store, search) works end-to-end through Python API calls, but has no user-facing interface. `cli.py` raises `SystemExit("km: not yet implemented")`. Claude skills (`/librarian find`, `/process`, `/dream`) need to shell out to `km search`, `km update`, and `km config` from the vault root with no flags. The CLI must auto-discover `.km/` (like `.git/`), support JSON output for machine callers, and expose config management so LLMs can adjust chunking rules without parsing TOML.

### Success Metrics

- [ ] `km index .` from a vault root creates `.km/config.toml` + `index.db` and reports stats
- [ ] `km search "query"` auto-discovers `.km/` and returns ranked results
- [ ] `km search "query" --json` returns machine-parseable JSON for skill consumption
- [ ] `km update file1.md file2.md` incrementally updates the index
- [ ] `km stats` reports file/chunk counts
- [ ] `km config show` dumps resolved config; `km config set` modifies overrides; `km config get` resolves per-file
- [ ] `uv tool install .` puts `km` on PATH; all subcommands work without `uv run`
- [ ] All fast tests pass in <1s

## Design Approach

A thin argparse shell in `cli.py` that parses arguments, discovers the vault root, delegates to existing APIs (`Searcher`, `load_config`, `resolve_for_file`), and formats output in two modes (human-readable and JSON). No business logic in the CLI layer — it is purely parse, dispatch, format.

### Why This Approach

- **Matches PLAN.md steps 23-24**: Two test files cover all subcommands
- **Follows existing architecture**: `cli.py` is already the leaf of the import DAG (`cli.py -> search, config`)
- **Mirrors beads CLI ergonomics**: `bd` uses the same auto-discover + `--json` + `config get/set` pattern, proven with Claude skills
- **Keeps library testable**: `Searcher` and config functions accept explicit paths; auto-discovery is a CLI-only concern
- **Single new dependency**: `tomli-w` for config writing — stdlib `tomllib` is read-only

## Technical Decisions

### Auto-Discovery

`discover_km_root()` walks parent directories from `cwd` upward until `.km/` is found. Returns the vault root `Path` (parent of `.km/`). Raises `SystemExit` if filesystem root reached.

- **Rationale**: Same pattern as `.git/` discovery and `bd`'s `.beads/` discovery. Skills call `km` from the vault root, so the walk is typically zero levels deep.
- **Trade-off**: No `--vault` flag in v1 — auto-discovery covers all use cases. Add `--vault` later if needed.
- **Lives in**: `cli.py` only. `Searcher` and `config.py` continue accepting explicit paths.

### Subcommand Structure

Five top-level subcommands, one with sub-subcommands:

| Command | Args | Discovers `.km/`? | Uses Searcher? |
|---------|------|-------------------|----------------|
| `km index [path]` | Optional vault path | Only when no path given | Yes |
| `km search <query>` | Query string, `--top-k N` | Yes | Yes |
| `km update <paths...>` | Vault-relative file paths | Yes | Yes |
| `km stats` | None | Yes | No (Store directly) |
| `km config show` | None | Yes | No |
| `km config set <pattern> <key=val...>` | Glob + settings | Yes | No |
| `km config get <file>` | Vault-relative path | Yes | No |

- **Rationale**: Matches PLAN.md's ergonomics section. `index` takes an optional path (like `git init [path]`); all other commands auto-discover.
- **`km index` dual behavior**: With path arg, creates `.km/` and indexes (first run). Without path arg, auto-discovers `.km/` and re-indexes (rebuild). This avoids forcing users to specify the path they're already standing in.

### Output Modes

**Global `--json` flag** on the top-level parser. Affects all subcommands.

**Human-readable format** (default):

- `search`: `[{distance:.2f}] {file_path}` + optional ` :: {section_header}`, newline, `  > {content_preview}` (first line of content, max 80 chars, ellipsis if truncated)
- `index`/`update`: `Indexed {files} files ({chunks} chunks)`
- `stats`: `{files} files, {chunks} chunks`
- `config show`: TOML-formatted dump
- `config get`: Key-value lines
- `config set`: Confirmation message

**JSON format** (`--json`):

- `search`: `{"results": [{"file_path": ..., "section_header": ..., "content": ..., "directory": ..., "distance": ...}]}`
- `index`/`update`/`stats`: `{"files": N, "chunks": N}`
- `config show`: Serialized VaultConfig dict
- `config get`: Serialized ChunkConfig dict
- `config set`: `{"status": "ok", "pattern": "...", "settings": {...}}`

- **Rationale**: `--json` is a global flag (not per-subcommand) matching `bd --json`. Skills always pass `--json`; humans never do.

### Config Management

**`config show`**: Reads `.km/config.toml` via `load_config()`, formats as TOML (human) or dict (JSON). Shows the full resolved `VaultConfig` including defaults.

**`config set <pattern> key=value...`**: Roundtrip through `tomllib.load()` -> modify dict -> `tomli_w.dump()`. Finds existing override with matching `files` pattern; updates it if found, appends new override if not. For default settings (no pattern), uses a sentinel like `"defaults"` as the pattern arg.

- **Comment loss**: `tomli-w` does not preserve comments. This is acceptable — `config set` is designed for LLM callers that don't read comments. Initial `config.toml` (generated by `km index`) has comments; after first `config set`, they're gone.
- **Validation**: After writing, re-read with `load_config()` to validate the result. If invalid, restore the original file and report the error.

**`config get <file>`**: Calls `load_config()` + `resolve_for_file()` for the given path. Shows the resolved `ChunkConfig` for that specific file.

### Error Handling

- **User-facing errors**: `SystemExit("km: <message>")` — same prefix as current stub
- **No subcommand given**: Print usage and exit with code 2 (argparse default)
- **No `.km/` found**: `SystemExit("km: no .km/ directory found (run 'km index <path>' first)")`
- **Internal errors** (ValueError from config/store): Let propagate as tracebacks — these indicate bugs, not user errors
- **Exit codes**: 0 success, 1 for km errors (SystemExit), 2 for usage errors (argparse)

### Dependencies

Add `tomli-w` to `pyproject.toml` dependencies. Current: `["sqlite-vec", "fastembed"]`. After: `["sqlite-vec", "fastembed", "tomli-w"]`.

No other new dependencies. `argparse`, `json`, `tomllib` are all stdlib.

## Scope Definition

### In Scope

- argparse with `index`, `update`, `search`, `stats`, `config` (show/set/get) subcommands
- Auto-discovery of `.km/` by walking parent directories from cwd
- `--json` global flag for machine-parseable output
- `tomli-w` for `config set` TOML writing
- Human-readable search output format (`[score] path :: header` + content preview)
- `km index` generates commented `config.toml` on first run (if none exists)
- Tests: `test_cli_index_search_update` and `test_cli_config` (PLAN.md steps 23-24)

### Out of Scope

- Real-world quality evaluation (Phase 5)
- Skill integration with Main/ vault (Phase 5+)
- `--vault` override flag (add later if needed)
- `--verbose` / `--quiet` flags (5 subcommands, minimal output — not needed yet)
- `config unset` / `config validate` (add later if needed)
- Colored output / progress bars
- Shell completion

## Success Criteria

### Functional Requirements

- [ ] `km index /path/to/vault` creates `.km/config.toml` (if missing) and `index.db`, prints stats
- [ ] `km index` (no args) auto-discovers `.km/` and re-indexes
- [ ] `km search "query"` returns results sorted by distance, human-readable
- [ ] `km search "query" --json --top-k 5` returns JSON with top 5 results
- [ ] `km update file1.md file2.md` re-indexes specific files
- [ ] `km stats` / `km stats --json` reports file/chunk counts
- [ ] `km config show` dumps resolved config
- [ ] `km config set "Memory/**" strategy=atomic` adds/updates override
- [ ] `km config get "Memory/insight.md"` shows resolved config for that file
- [ ] No subcommand prints usage help

### Non-Functional Requirements

- [ ] All fast tests pass in <1s (no model downloads in CLI tests)
- [ ] CLI tests use `monkeypatch` + `capsys`, not subprocess (fast, in-process)
- [ ] `cli.py` contains no business logic — only parse, dispatch, format
- [ ] Import DAG preserved: `cli.py` imports from `search`, `config`, `store`, `__init__` only

## Risk Analysis

### Technical Risks

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| `tomli-w` comment loss confuses users | Low | Low | Document in `config.toml` header; `config set` is for LLM callers |
| `config set` produces invalid TOML | Medium | Low | Re-validate with `load_config()` after write; restore on failure |
| Auto-discovery too slow (deep directory trees) | Low | Very Low | Walk is O(depth), max ~20 levels; `.km/` is always near vault root |

### Assumptions

| Assumption | Validated? |
|------------|------------|
| `Searcher.__init__` creates `.km/` dir idempotently | Yes (search.py:43 uses `mkdir(parents=True, exist_ok=True)`) |
| `load_config` returns defaults when no config.toml exists | Yes (config.py:26 returns `VaultConfig()`) |
| `Store.stats()` works on empty store | Yes (returns `{"files": 0, "chunks": 0}`) |
| `search()` on empty store returns `[]` | Yes (verified by test_search.py:43-53) |

## Rejected Alternatives

### Option: Click / Typer instead of argparse

- **Approach**: Use Click or Typer for richer CLI framework
- **Rejected because**: PLAN.md specifies argparse (stdlib). Adding Click/Typer adds a dependency for a 5-subcommand CLI. argparse is sufficient and keeps the dependency count minimal.

### Option: tomlkit instead of tomli-w

- **Approach**: Use `tomlkit` for comment-preserving TOML roundtrips
- **Rejected because**: `tomlkit` is a larger dependency with a different data model (returns `TOMLDocument`, not plain dicts). Comment preservation is nice-to-have but not essential — `config set` is for LLM callers. `tomli-w` pairs naturally with stdlib `tomllib`.

### Option: Store index.db outside vault (~/.km/)

- **Approach**: Central `~/.km/index.db` instead of per-vault `.km/index.db`
- **Rejected because**: PLAN.md decided `.km/` at vault root. Co-locating config and DB simplifies auto-discovery (one directory to find, not two). Multiple vaults work naturally (each has its own `.km/`).

## References

- Research: [research.md](research.md)
- Tasks: [tasks.md](tasks.md)
- Overall plan: [PLAN.md](../../../PLAN.md)
- Phase 3 (Search): [../2026-04-15-phase-3-embedding-and-search/](../2026-04-15-phase-3-embedding-and-search/)
