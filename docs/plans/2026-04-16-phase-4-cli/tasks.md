---
project: phase-4-cli
ticket: null
created: 2026-04-16
created_timestamp: 2026-04-16T20:00:00Z
status: complete
last_updated: 2026-04-16
assignee: gvarela
current_phase: 3
total_tasks: 5
completed_tasks: 5
git_commit: e867c4f
git_branch: main
repository: knowledge-manager
tags: [tasks, tracking, phase-4-cli]
depends_on: [research.md, design.md]
beads_epic: km-8mx
beads_phases:
  phase1_milestone: km-uei
  phase2_milestone: km-51q
  phase3_milestone: km-bjn
beads_tasks:
  phase1_discover: km-skv
  phase2_index: km-402
  phase2_search_update_stats: km-eyo
  phase3_config_show_get: km-pwy
  phase3_config_set: km-7dt
---

# Execution Plan: Phase 4 — CLI

## Overview

Implementing the `km` CLI with argparse subcommands (`index`, `update`, `search`, `stats`, `config`), `.km/` auto-discovery, JSON output, and LLM-friendly config management per [design.md](design.md) and PLAN.md steps 23-24.

## Implementation Strategy

### Phase Rationale

Three phases ordered by dependency chain (from agent analysis):

1. **Foundation first**: Auto-discovery (`discover_km_root`) is required by every subcommand. `tomli-w` dep needed before config writing. These have zero downstream blockers.
2. **Core subcommands second**: argparse skeleton + index/search/update/stats cover PLAN.md step 23. Index must come first (creates the store), then search/update/stats can build on it.
3. **Config subcommands last**: config show/get/set cover PLAN.md step 24. Depends on argparse skeleton from Phase 2. `config set` needs tomli-w from Phase 1.

### Testing Strategy

- **monkeypatch `sys.argv`** + `capsys` to test `main()` directly — no subprocess
- **monkeypatch `km.cli.Searcher`** with a factory that injects `ConstantEmbedder()` — avoids model downloads in CLI tests
- One test function per behavior (flat, descriptive names — matches existing test style)
- All CLI tests are fast (<1s, no `@pytest.mark.slow`)

### Embedder Injection Pattern

```python
class ConstantEmbedder:
    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.1] * 384 for _ in texts]

def _make_searcher_with_fake(vault_root, **kwargs):
    return Searcher(vault_root, embedder=ConstantEmbedder())

monkeypatch.setattr("km.cli.Searcher", _make_searcher_with_fake)
```

## Beads Issue Tracking

**Epic**: km-8mx — Phase 4: CLI Implementation

**Phase Milestones**:
- Phase 1: km-uei — Foundation (auto-discovery + deps)
- Phase 2: km-51q — Core CLI subcommands (step 23)
- Phase 3: km-bjn — Config subcommands (step 24)

**Task Chain** (strict sequential):
```
km-skv → km-402 → km-eyo → km-pwy → km-7dt
```

**Commands**:
```bash
bd ready                         # See what's available
bd show <id>                     # View task details
bd update <id> --status in_progress  # Claim task
bd close <id>                    # Complete task
bd blocked                       # See blocked tasks
```

---

## Phase 1: Foundation (auto-discovery + deps)

### Objective
Add `tomli-w` dependency and implement `.km/` auto-discovery function with tests.

### Task: km-skv — Add tomli-w dep + discover_km_root() + test

**TDD Cycle**:

1. **RED**: Write `tests/test_cli.py` with tests:
   - `test_discover_km_root_finds_km_dir` — `.km/` in cwd, returns cwd
   - `test_discover_km_root_walks_parents` — `.km/` two levels up, finds it
   - `test_discover_km_root_raises_when_not_found` — no `.km/` anywhere, raises `SystemExit`

2. **GREEN**: 
   - Add `"tomli-w"` to `pyproject.toml` dependencies (line 6)
   - Implement `discover_km_root(start: Path | None = None) -> Path` in `cli.py`
   - Walk parent directories from `start` (or `Path.cwd()`) until `.km/` is found
   - Raise `SystemExit("km: no .km/ directory found (run 'km index <path>' first)")` at filesystem root

3. **REFACTOR**: Ensure function is clean, no unnecessary complexity

**Files**:
- `pyproject.toml:6` — add `"tomli-w"` to dependencies list
- `src/km/cli.py` — replace stub with `discover_km_root()` + keep `main()` as minimal placeholder
- `tests/test_cli.py` — new file with auto-discovery tests

### Success Criteria
- [ ] `tomli-w` in dependencies, `uv sync` succeeds
- [ ] `discover_km_root()` finds `.km/` walking parents
- [ ] `SystemExit` when no `.km/` found
- [ ] All tests pass: `uv run pytest tests/test_cli.py -x`

### CHECKPOINT: Phase 1 Complete
Verify: `bd show km-uei` — all blockers closed. Close milestone.

---

## Phase 2: Core CLI Subcommands (PLAN.md step 23)

### Objective
Build argparse parser with `index`, `search`, `update`, `stats` subcommands and `--json` output.

### Task: km-402 — argparse skeleton + km index [path] + test

**TDD Cycle**:

1. **RED**: Write `test_cli_index` in `tests/test_cli.py`:
   - `test_cli_index_with_path` — `km index <tmp_path>` creates `.km/`, indexes vault, prints stats
   - `test_cli_index_without_path` — `km index` (no arg) auto-discovers `.km/`, re-indexes
   - `test_cli_no_subcommand_prints_usage` — bare `km` prints help/usage

2. **GREEN**:
   - Build argparse parser in `cli.py` with `add_subparsers(dest="command")`
   - Add `--json` global flag
   - Add `index` subparser with optional `vault_path` positional arg
   - Implement `_cmd_index(args, vault_root)`:
     - If `args.vault_path` provided, use it as vault_root
     - Otherwise, use `discover_km_root()`
     - Create `Searcher(vault_root)`, call `index_vault()`
     - Print stats (human or JSON based on `args.json`)
   - Generate commented `config.toml` on first index if `.km/config.toml` doesn't exist
   - Wire `main()` to parse args and dispatch

3. **REFACTOR**: Extract output formatting helpers

**Files**:
- `src/km/cli.py` — argparse parser + index handler + main()
- `tests/test_cli.py` — index tests with monkeypatch + capsys

### Task: km-eyo — search + update + stats subcommands + --json + tests

**TDD Cycle**:

1. **RED**: Write tests in `tests/test_cli.py`:
   - `test_cli_search` — `km search "query"` returns human-readable results
   - `test_cli_search_json` — `km search "query" --json` returns JSON array
   - `test_cli_search_top_k` — `km search "query" --top-k 2` limits results
   - `test_cli_update` — `km update file.md` re-indexes, prints stats
   - `test_cli_stats` — `km stats` reports file/chunk counts
   - `test_cli_stats_json` — `km stats --json` returns JSON dict

2. **GREEN**:
   - Add `search` subparser: positional `query`, `--top-k` (int, default 10)
   - Add `update` subparser: positional `paths` (nargs="+")
   - Add `stats` subparser: no args
   - Implement handlers:
     - `_cmd_search`: `Searcher.search(query, k)`, format results
     - `_cmd_update`: `Searcher.update_files(paths)`, print stats
     - `_cmd_stats`: `Store(km_dir / "index.db").stats()`, print counts
   - Human output for search: `[{dist:.2f}] {path}` + optional ` :: {header}`, then `  > {preview}`
   - JSON output: structured dicts with all fields

3. **REFACTOR**: DRY up output formatting, ensure consistent error messages

**Files**:
- `src/km/cli.py` — add search/update/stats subparsers + handlers
- `tests/test_cli.py` — add search/update/stats tests

### Success Criteria (Phase 2)
- [ ] `km index .` creates `.km/` and indexes
- [ ] `km search "query"` returns ranked results
- [ ] `km search "query" --json` returns valid JSON
- [ ] `km update file.md` re-indexes specific files
- [ ] `km stats` / `km stats --json` reports counts
- [ ] All tests pass: `uv run pytest tests/test_cli.py -x`
- [ ] `uv run ruff check .` clean

### CHECKPOINT: Phase 2 Complete
Verify: `bd show km-51q` — all blockers closed. Close milestone.

---

## Phase 3: Config Subcommands (PLAN.md step 24)

### Objective
Implement `config show`, `config get`, `config set` subcommands with TOML writing.

### Task: km-pwy — config show + config get + tests

**TDD Cycle**:

1. **RED**: Write tests in `tests/test_cli.py`:
   - `test_cli_config_show` — `km config show` dumps VaultConfig as readable output
   - `test_cli_config_show_json` — `km config show --json` returns JSON dict
   - `test_cli_config_get` — `km config get "Memory/note.md"` shows resolved ChunkConfig
   - `test_cli_config_get_json` — `km config get "Memory/note.md" --json` returns JSON

2. **GREEN**:
   - Add `config` subparser with sub-subparsers (`config_command`)
   - Add `show` sub-subparser (no args)
   - Add `get` sub-subparser with positional `file_path`
   - Implement handlers:
     - `_cmd_config_show`: `load_config(vault_root)`, format VaultConfig
     - `_cmd_config_get`: `load_config()` + `resolve_for_file()`, format ChunkConfig
   - Human output: key-value lines for config fields
   - JSON output: dataclass → dict serialization

3. **REFACTOR**: Clean up config formatting

**Files**:
- `src/km/cli.py` — add config show/get subparsers + handlers
- `tests/test_cli.py` — add config show/get tests

### Task: km-7dt — config set subcommand (tomli-w) + test

**TDD Cycle**:

1. **RED**: Write tests in `tests/test_cli.py`:
   - `test_cli_config_set_new_override` — `km config set "Memory/**" strategy=atomic` adds override to config.toml
   - `test_cli_config_set_update_existing` — second `config set` with same pattern updates (not duplicates)
   - `test_cli_config_set_defaults` — `km config set defaults min_chunk_chars=500` updates [defaults] section

2. **GREEN**:
   - Add `set` sub-subparser with positional `pattern` and `settings` (nargs="+")
   - Implement `_cmd_config_set`:
     - Read existing config.toml with `tomllib.load()`
     - Parse `key=value` pairs from args
     - If pattern is `"defaults"`: update `data["defaults"]`
     - Otherwise: find override where `files == pattern`, update or append
     - Write with `tomli_w.dump(data, f)`
     - Re-validate with `load_config()` — restore original on failure
   - Print confirmation (human or JSON)

3. **REFACTOR**: Error handling for invalid key=value syntax, unknown keys

**Files**:
- `src/km/cli.py` — add config set subparser + handler
- `tests/test_cli.py` — add config set tests

### Success Criteria (Phase 3)
- [ ] `km config show` dumps config as TOML-like output
- [ ] `km config show --json` returns JSON
- [ ] `km config get "Memory/note.md"` shows resolved config
- [ ] `km config set "Memory/**" strategy=atomic` modifies config.toml
- [ ] `km config set` with existing pattern updates (not duplicates)
- [ ] All tests pass: `uv run pytest tests/test_cli.py -x`
- [ ] `uv run ruff check .` clean

### CHECKPOINT: Phase 3 Complete
Verify: `bd show km-bjn` — all blockers closed. Close milestone.

---

## Implementation Discoveries

### Resolved during implementation

- **`config show` format**: TOML-like sections (`[defaults]`, `[scan]`, `[[overrides]]`) for human output, nested dict for JSON. Works well.
- **`config set defaults` sentinel**: Ergonomic enough — `km config set defaults min_chunk_chars=500` is clear.
- **Content preview**: First line of chunk content, max 80 chars with `...` truncation. Adequate for terminal.
- **tomli-w inline tables**: `tomli_w.dump()` uses inline table syntax for arrays of tables (`overrides = [{files = "..."}]`). Valid TOML, parses correctly, slightly different visual style than hand-written `[[overrides]]` blocks.
- **Searcher injection in tests**: Patching `km.search.Searcher.__init__` (not `km.cli.Searcher`) with `ConstantEmbedder` is the cleanest pattern. Workers discovered this independently.
- **`uv tool install --reinstall`**: Needed after code changes — `--force` alone uses cached wheel. `--reinstall` forces rebuild.

### `km prime` — Plugin pattern for Claude Code integration

Added `km prime` subcommand (not in original PLAN.md) to mirror `bd prime` from beads. Outputs markdown context for Claude Code hooks (SessionStart, PreCompact). This is the mechanism that makes Claude "know" about `km` across sessions — same pattern that makes beads effective.

**Integration recipe for any vault**:
1. `uv tool install /path/to/knowledge-manager` — puts `km` on PATH
2. `km index /path/to/vault` — creates `.km/` with config + index
3. Add `.km/.gitignore` — ignore `index.db` and `models/`, track `config.toml`
4. Add `"Bash(km:*)"` to vault's `.claude/settings.local.json` permissions
5. Add `km prime` to vault's SessionStart and PreCompact hooks
6. Add `km update` to PostToolUse hooks on Write/Edit for `.md` files
7. Update retrieval skills to use `km search --json` instead of grep/glob

---

## Completed Tasks Archive

- [x] Create project structure (2026-04-16)
- [x] Complete research (2026-04-16)
- [x] Create design document (2026-04-16)
- [x] Create execution plan (2026-04-16)

---

## Blockers & Notes

### Current blockers
None. First task (`km-skv`) is ready to work.

---

## Quick Reference

### Key files
- **Research**: [research.md](research.md)
- **Design**: [design.md](design.md)
- **Overall plan**: [PLAN.md](../../../PLAN.md)
- **Phase 3 (Search)**: [../2026-04-15-phase-3-embedding-and-search/](../2026-04-15-phase-3-embedding-and-search/)
- **CLI stub**: `src/km/cli.py`
- **Searcher API**: `src/km/search.py`
- **Config API**: `src/km/config.py`

### Common commands
```bash
bd ready                                    # Find available work
uv run pytest tests/test_cli.py -x          # Run CLI tests (stop on first failure)
uv run pytest -m "not slow" --tb=short -q -x  # All fast tests
uv run ruff check .                         # Lint
uv run ruff format .                        # Format
```

### Design decisions reference
- **Auto-discovery**: Walk parent dirs for `.km/`, CLI-only concern (`discover_km_root()`)
- **Output modes**: Human-readable default, `--json` global flag
- **`km index` dual mode**: With path = create `.km/`; without = auto-discover + re-index
- **Config writing**: `tomllib` read + `tomli_w` write; comments lost (acceptable)
- **Test injection**: monkeypatch `km.cli.Searcher` with `ConstantEmbedder`

### Next action
Run `/wb:implement_coordinated docs/plans/2026-04-16-phase-4-cli/ 1` to begin implementation.
