---
project: phase-4-cli
ticket: null
created: 2026-04-16
created_timestamp: 2026-04-16T20:00:00Z
status: complete
last_updated: 2026-04-16
researcher: gvarela
git_commit: d385d73
git_branch: main
repository: knowledge-manager
tags: [research, codebase, phase-4-cli]
---

# Research: Phase 4 — CLI

**Created**: 2026-04-16
**Last Updated**: 2026-04-16
**Researcher**: gvarela
**Ticket**: N/A

## Research Question

How should we build the `km` CLI to expose the Searcher/Embedder/Store pipeline as a standalone command with `index`, `update`, `search`, `stats`, and `config` subcommands? What does the existing cli.py stub look like, what patterns does argparse need, how should `.km/` auto-discovery work, and how does the beads CLI (`bd`) inform our design? Additionally, how will Claude skills integrate with `km` as a plugin?

## Summary

The CLI is a thin argparse shell over three existing APIs: `Searcher` (index/update/search), `Store.stats()`, and `config.py` (load/resolve). The stub at `cli.py:1-2` raises `SystemExit("not yet implemented")`; `__main__.py` and `pyproject.toml` entry points are already wired. Auto-discovery of `.km/` requires a new parent-directory walk function (same pattern as `.git/` and `.beads/`). The `bd` CLI provides a proven ergonomic template: global `--json` flag, `--db` with auto-discovery default, and `config get/set/list` subcommands. Config writing needs `tomli-w` (v1.2.0) — a `tomllib` read + `tomli_w` write roundtrip, noting that comments are lost. Claude skills (`/librarian find`, `/process`) call `km search "query"` from the vault root with no flags; `--json` enables machine-parseable output.

## Detailed Findings

### 1. Current CLI State

**`src/km/cli.py:1-2`** — Stub:

```python
def main() -> None:
    raise SystemExit("km: not yet implemented")
```

**`src/km/__main__.py:1-4`** — Entry point wired:

```python
from km.cli import main
if __name__ == "__main__":
    main()
```

**`pyproject.toml:8-9`** — Console script registered:

```toml
[project.scripts]
km = "km.cli:main"
```

The entry points are complete. `uv tool install .` already puts `km` on PATH — the shell just needs a real implementation.

### 2. APIs That CLI Wraps

#### Searcher (`src/km/search.py:32-115`)

```python
class Searcher:
    def __init__(self, vault_root: Path, store=None, embedder=None)
    def __enter__(self) / __exit__(self, ...)  # context manager, closes owned store
    def search(self, query: str, k: int = 10) -> list[SearchResult]
    def index_vault(self) -> dict[str, int]     # returns {"files": N, "chunks": N}
    def update_files(self, paths: list[str]) -> dict[str, int]  # returns {"files": N, "chunks": N}
```

- `Searcher` creates `.km/` dir, `index.db`, and model cache on its own when no store/embedder injected (`search.py:42-51`)
- `SearchResult` is a frozen dataclass with `.chunk` (Chunk) and `.distance` (float) (`search.py:26-29`)
- `Chunk` has: `file_path`, `section_header`, `content`, `directory` (derived) (`__init__.py:29-38`)

#### Config (`src/km/config.py:22-86`)

```python
def load_config(vault_path: Path) -> VaultConfig  # reads .km/config.toml
def resolve_for_file(config: VaultConfig, file_path: str) -> ChunkConfig  # glob overrides
```

- `VaultConfig` wraps `ChunkConfig` + `ScanConfig` + `overrides: tuple[dict, ...]` (`__init__.py:22-26`)
- No write capability exists — `tomllib` is read-only. Writing needs `tomli-w`.

#### Store stats (`src/km/store.py:122-127`)

```python
def stats(self) -> dict[str, int]  # returns {"files": N, "chunks": N}
```

### 3. Auto-Discovery of `.km/`

**Current state**: No auto-discovery exists. `Searcher.__init__` takes `vault_root` as an explicit `Path` parameter (`search.py:35`). Config loading takes `vault_path` explicitly (`config.py:22`).

**Required behavior** (from PLAN.md:113 and CLAUDE.md:44): Walk parent directories from `cwd` upward until `.km/` is found — same pattern as `.git/` and `.beads/`.

**Implementation pattern**:

```python
def discover_km_root(start: Path | None = None) -> Path:
    """Walk parent directories to find .km/, like .git/ discovery."""
    current = (start or Path.cwd()).resolve()
    while True:
        if (current / ".km").is_dir():
            return current
        parent = current.parent
        if parent == current:  # filesystem root
            raise SystemExit("km: no .km/ directory found (run 'km index <path>' first)")
        current = parent
```

**Where it lives**: In `cli.py` — auto-discovery is a CLI concern. `Searcher` and `config.py` continue to accept explicit paths. This keeps the library layer testable without filesystem side effects.

### 4. Beads CLI Design Patterns

`bd` (v0.49.3, Go/Cobra) provides the ergonomic template `km` should mirror:

| Pattern | `bd` implementation | `km` equivalent |
|---------|-------------------|----------------|
| **Auto-discovery** | `--db` flag, default auto-discovers `.beads/*.db` | `--vault` flag (optional), default auto-discovers `.km/` from cwd |
| **JSON output** | Global `--json` flag on all commands | `--json` flag on `search`, `stats`, `config show`, `config get` |
| **Config subcommand** | `bd config get/set/list/unset/validate` | `km config show/set/get` (show=list equivalent) |
| **Quiet mode** | `-q, --quiet` suppresses non-essential output | Not needed for v1 (5 subcommands, minimal output) |
| **Verbose mode** | `-v, --verbose` for debug output | Not needed for v1 |
| **Create + scripting** | `bd create --silent` outputs only ID | `km index` outputs stats; `--json` for scripting |

**Key `bd config` ergonomics** (`bd config --help`):

```
bd config set jira.url "https://company.atlassian.net"
bd config get jira.url
bd config list
bd config unset jira.url
```

`km config` differs: it manages TOML sections (defaults, overrides with glob patterns), not flat key-value pairs. The three subcommands from PLAN.md:

```bash
km config show                                    # dump resolved VaultConfig
km config set "Memory/**" strategy=atomic         # add/update an override
km config get "Daily/2026-04-14.md"               # show resolved ChunkConfig for a file
```

### 5. tomli-w for Config Writing

**Package**: `tomli-w` v1.2.0 (Jan 2025)
**API**:

```python
import tomli_w

tomli_w.dumps(data: dict) -> str          # serialize to string
tomli_w.dump(data: dict, fp) -> None      # write to binary file (wb mode)

# Optional params: indent=4, multiline_strings=False
```

**Roundtrip pattern** for `km config set`:

```python
import tomllib
import tomli_w

# Read
with open(config_path, "rb") as f:
    data = tomllib.load(f)

# Modify
data.setdefault("overrides", [])
# ... find or create override entry ...

# Write back
with open(config_path, "wb") as f:
    tomli_w.dump(data, f)
```

**Critical gotcha**: `tomli-w` does NOT preserve comments. The sample `config.toml` from PLAN.md has comments (`# km configuration for this vault`, etc.). After a `km config set`, all comments are lost. This is an acceptable trade-off — `km config set` is designed for LLM callers that don't read comments.

**Arrays of tables**: Python `list[dict]` serializes to TOML `[[overrides]]`:

```python
{"overrides": [
    {"files": "Memory/**", "strategy": "atomic"},
    {"files": "Daily/**", "strategy": "atomic"},
]}
```

Produces:

```toml
[[overrides]]
files = "Memory/**"
strategy = "atomic"

[[overrides]]
files = "Daily/**"
strategy = "atomic"
```

### 6. Claude Skill Integration (Plugin Pattern)

Claude skills in the Main/ vault call `km` as an external CLI tool — the same pattern as skills calling `bd`:

**How it works**:

1. Skill runs in the vault root directory (`/Users/gvarela/Obsidian/Main/`)
2. `.km/` is at the vault root (created by `km index`)
3. Skill shells out: `km search "billing roadmap" --json`
4. `km` auto-discovers `.km/` from cwd, runs search, returns JSON
5. Skill parses JSON results

**Specific integration points** (from PLAN.md):

- `/librarian find` — shells out to `km search "query" --json` for semantic search (currently grep/glob only)
- `/process` — after writing state updates, calls `km update People/Nick/README.md ...` to keep index current
- `/reindex` — calls `km index` alongside YAML index regeneration
- `/dream` — calls `km update` on extracted Memory/ notes

**What skills need from `--json` output**:

```json
{
  "results": [
    {
      "file_path": "People/Bob/README.md",
      "section_header": "",
      "content": "Bob leads the infrastructure team...",
      "directory": "People",
      "distance": 0.82
    }
  ]
}
```

For `km stats --json`:

```json
{"files": 599, "chunks": 4739}
```

**Config management by skills**: `km config show --json` lets a skill inspect current config, `km config set "Memory/**" strategy=atomic` lets a skill adjust chunking without parsing TOML.

### 7. argparse Subcommand Structure

Using stdlib `argparse` with `add_subparsers()`:

```python
parser = argparse.ArgumentParser(prog="km", description="Semantic search for Obsidian vaults")
parser.add_argument("--json", action="store_true", help="Output in JSON format")

sub = parser.add_subparsers(dest="command")

# km index <vault-path>
p_index = sub.add_parser("index", help="Build search index")
p_index.add_argument("vault_path", nargs="?", help="Path to vault (default: auto-discover)")

# km search <query>
p_search = sub.add_parser("search", help="Semantic search")
p_search.add_argument("query", help="Search query")
p_search.add_argument("--top-k", type=int, default=10, help="Number of results")

# km update <paths...>
p_update = sub.add_parser("update", help="Re-index specific files")
p_update.add_argument("paths", nargs="+", help="Vault-relative file paths")

# km stats
sub.add_parser("stats", help="Show index statistics")

# km config show|set|get
p_config = sub.add_parser("config", help="Manage configuration")
config_sub = p_config.add_subparsers(dest="config_command")
config_sub.add_parser("show", help="Show resolved config")
p_set = config_sub.add_parser("set", help="Set an override")
p_set.add_argument("pattern", help="Glob pattern (e.g., Memory/**)")
p_set.add_argument("settings", nargs="+", help="key=value pairs")
p_get = config_sub.add_parser("get", help="Show config for a file")
p_get.add_argument("file_path", help="Vault-relative file path")
```

**Target**: Python 3.12 (no `suggest_on_error` or `color` from 3.14).

### 8. Search Output Format

**Human-readable** (default, from PLAN.md):

```
[0.82] People/Bob/README.md
  > Bob leads the infrastructure team and manages cloud deployments.

[0.79] Meetings/2024-03-15-infra-review.md :: ## Decisions
  > Decided to migrate DNS to new provider. Bob to lead.
```

Format: `[{distance:.2f}] {file_path}` + optional ` :: {section_header}`, then `  > {content_preview}` (first ~80 chars of content, or configurable).

**JSON** (`--json`): Full SearchResult data as shown in Section 6.

### 9. Test Patterns for test_cli.py

**Existing conventions** (from `tests/test_search.py`, `tests/test_config.py`):

- `tmp_path` fixture for vault setup, write `.md` files directly
- `FakeEmbedder`/`ConstantEmbedder` injection — no mocking framework
- Direct assertions (`assert value == expected`)
- `pytest.raises(ValueError, match="pattern")` for errors

**CLI testing approach**: Test `main()` directly by monkeypatching `sys.argv` and using `capsys` to capture output. No subprocess needed — keeps tests fast.

```python
def test_cli_search(tmp_path, monkeypatch, capsys):
    # Setup vault, index it
    monkeypatch.setattr("sys.argv", ["km", "search", "query", "--json"])
    monkeypatch.chdir(tmp_path)
    main()
    captured = capsys.readouterr()
    result = json.loads(captured.out)
    assert "results" in result
```

**PLAN.md steps 23-24**:
- Step 23: `test_cli_index_search_update` — index/search/update/stats subcommands e2e
- Step 24: `test_cli_config` — config show/set/get subcommands

## Architecture Documentation

### Component Connections

```
CLI (cli.py)
├── discover_km_root()          → new function, walks parent dirs
├── argparse                    → stdlib, defines subcommands
├── Searcher (search.py)        → index_vault(), update_files(), search()
├── Store (store.py)            → stats() (direct for km stats)
├── load_config (config.py)     → config show, config get
├── resolve_for_file (config.py)→ config get <file>
├── tomli_w                     → config set (TOML writing)
└── json (stdlib)               → --json output formatting
```

### Import DAG Extension

Current:
```
cli.py → search, config
```

Phase 4 adds:
```
cli.py → search, config, store, __init__ (for __version__), json, tomli_w, argparse
```

This stays within the DAG constraint: `cli.py` is a leaf node that imports from lower layers.

### Patterns Found

**Output formatting**: Two modes everywhere — human-readable (default) and JSON (`--json`). Human format designed for terminal reading. JSON format designed for skill parsing.

**Error handling**: `SystemExit` for user-facing errors (no `.km/` found, no query provided). Python exceptions for programming errors (let them propagate with traceback).

**Vault path resolution**: `km index <path>` takes an explicit path (creates `.km/`). All other commands auto-discover from cwd. This mirrors `git init <path>` vs `git status` (auto-discovers `.git/`).

## Code References

- `src/km/cli.py:1-2` — Current stub (`raise SystemExit`)
- `src/km/__main__.py:1-4` — Entry point (`from km.cli import main`)
- `src/km/search.py:32-65` — Searcher class, search(), context manager
- `src/km/search.py:78-93` — `index_vault()` full pipeline
- `src/km/search.py:95-115` — `update_files()` incremental update
- `src/km/config.py:22-63` — `load_config()` reads `.km/config.toml`
- `src/km/config.py:66-86` — `resolve_for_file()` applies overrides
- `src/km/store.py:122-127` — `stats()` returns `{files, chunks}`
- `src/km/__init__.py:5` — `__version__ = "0.1.0"`
- `pyproject.toml:8-9` — `[project.scripts] km = "km.cli:main"`

## Similar Implementations

### Beads CLI (`bd`) — Go/Cobra

`bd` (v0.49.3) provides the proven ergonomic model:

- Auto-discovers `.beads/` by walking parent directories
- Global `--json` flag for machine-parseable output
- `config get/set/list/unset` subcommands with namespace-based keys
- `--db` flag to override auto-discovered path
- `--quiet` and `--verbose` global flags

### Git CLI

- `git init <path>` creates `.git/` at explicit path
- All other commands auto-discover `.git/` from cwd
- `km index <path>` parallels `git init`; `km search` parallels `git status`

## Open Questions

No blocking questions. All design decisions are specified in PLAN.md.

## Next Steps

1. Review research findings
2. Run `/wb:create_design` to formalize CLI design decisions
3. Run `/wb:create_execution` to generate tasks for steps 23-24

## References

- Design: [design.md](design.md)
- Tasks: [tasks.md](tasks.md)
- Overall plan: [PLAN.md](../../../PLAN.md)
- Phase 3 docs: [../2026-04-15-phase-3-embedding-and-search/](../2026-04-15-phase-3-embedding-and-search/)
- [tomli-w PyPI](https://pypi.org/project/tomli-w/) — TOML writing library (v1.2.0)
- [Python argparse docs](https://docs.python.org/3/library/argparse.html) — subcommand patterns
- [Real Python TOML guide](https://realpython.com/python-toml/) — roundtrip read/write patterns
