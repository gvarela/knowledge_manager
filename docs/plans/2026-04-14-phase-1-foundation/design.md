---
project: phase-1-foundation
ticket: null
created: 2026-04-14
created_timestamp: 2026-04-14T19:58:34Z
status: approved
last_updated: 2026-04-14
designer: gvarela
git_commit: not-in-git
git_branch: main
repository: knowledge-manager
tags: [design, architecture, phase-1-foundation]
depends_on: research.md
design_approach: config-driven chunking with vault-scoped .km directory
---

# Design: Phase 1 Foundation

**Created**: 2026-04-14 19:58 UTC
**Last Updated**: 2026-04-14
**Designer**: gvarela
**Status**: Approved

## Problem Statement

km is a generic semantic search tool. Main/ is one vault with specific chunking needs (Memory/ is atomic, Daily/ shouldn't split, some directories shouldn't be indexed). These vault-specific rules must not be baked into km's code. The chunker needs to accept configuration that the vault defines, so km stays reusable and the vault stays in control.

### Success Metrics

- km ships sensible defaults that work without any config file
- A vault can override chunking behavior per-directory via `.km/config.toml`
- The chunker API accepts resolved config, never references vault-specific knowledge
- `uv run pytest` passes, `uv run ruff check .` is clean
- `chunk_markdown()` correctly applies config-driven rules
- `scan_vault()` respects include/exclude patterns from config

## Design Approach

**Config-driven chunking with vault-scoped `.km/` directory.** km defines sensible defaults. Each vault optionally overrides them via `.km/config.toml` using glob-based per-directory rules. The chunker receives resolved config per file — it never reads config itself.

### Why This Approach

- **Matches existing vault conventions.** `.beads/config.yaml` already establishes the pattern of tool config inside a dotfile directory at vault root. `.km/config.toml` follows the same pattern.
- **Keeps km generic.** No vault-specific logic in the codebase. The "Memory/ is atomic" rule lives in Main's `.km/config.toml`, not in `chunker.py`.
- **Declarative, not code.** Main/ is managed by Claude skills via shell, not Python. TOML is readable and editable by both humans and LLMs.
- **Single-file glob overrides (Prettier model).** One config file, auditable in one place. Per-directory rules expressed as glob patterns, not cascading config files.
- **TOML format.** Python stdlib `tomllib` (3.11+), no extra dependency. Consistent with ruff, hatch, mise.

## Technical Decisions

### Config Location and Discovery

Config lives at `.km/config.toml` alongside `.km/index.db`. Both are discovered together by walking parent directories looking for `.km/`. `km index <path>` creates `.km/` and optionally seeds `config.toml` with defaults.

### Config Schema

```toml
[defaults]
split_on = ["h1", "h2"]       # header levels that trigger splits
strip_frontmatter = true       # remove YAML frontmatter before chunking
min_chunk_chars = 200          # below this, keep as single chunk regardless of headers

[scan]
include = ["**/*.md"]
exclude_dotdirs = true            # exclude all directories starting with "."

[[overrides]]
files = "Memory/**"
strategy = "atomic"            # never split, entire file is one chunk

[[overrides]]
files = "Daily/**"
strategy = "atomic"

[[overrides]]
files = ["Workflows/**", ".obsidian/**"]
index = false                  # skip these files entirely
```

### Defaults (when no config.toml exists)

km works without a config file. Built-in defaults:

- `split_on = ["h1", "h2"]`
- `strip_frontmatter = true`
- `min_chunk_chars = 200`
- `include = ["**/*.md"]`
- `exclude_dotdirs = true` — all directories starting with `.` are excluded
- No overrides

### Config Resolution

Config is loaded once at the start of `index` or `update`, then resolved per-file before passing to the chunker.

Resolution order for a given file:
1. Start with `[defaults]`
2. Apply each matching `[[overrides]]` entry (glob match against relative file path)
3. Later overrides win over earlier ones

The resolved config for a file is a plain dict/dataclass — the chunker receives it as a parameter.

### Chunker API

```python
chunk_markdown(text: str, file_path: str, config: ChunkConfig) -> list[Chunk]
```

`ChunkConfig` is the resolved rules for a specific file:

```python
from typing import Literal

@dataclass(frozen=True, slots=True)
class ChunkConfig:
    split_on: tuple[str, ...] = ("h1", "h2")
    strip_frontmatter: bool = True
    min_chunk_chars: int = 200
    strategy: Literal["default", "atomic"] = "default"
```

All fields have defaults so `ChunkConfig()` works with zero args.

- `strategy = "atomic"`: return entire file as one chunk, skip splitting
- `strategy = "default"`: apply split_on rules, frontmatter stripping, min_chunk_chars threshold

The chunker only knows about `ChunkConfig`. It does not read files, load config, or know about `.km/`.

### ScanConfig

```python
@dataclass(frozen=True, slots=True)
class ScanConfig:
    include: tuple[str, ...] = ("**/*.md",)
    exclude_dotdirs: bool = True
```

### VaultConfig (composite)

`load_config()` returns this. Wraps both config types plus any overrides.

```python
@dataclass(frozen=True, slots=True)
class VaultConfig:
    chunk: ChunkConfig
    scan: ScanConfig
    overrides: tuple[dict, ...] = ()  # raw override entries from TOML
```

### scan_vault API

```python
scan_vault(vault_path: Path, config: ScanConfig) -> list[Path]
```

`scan_vault` returns all matching files. `index = false` filtering happens post-scan in the Searcher, not here.

### Chunk Dataclass

```python
@dataclass(frozen=True, slots=True)
class Chunk:
    file_path: str              # relative to vault root
    section_header: str         # "## Action Items" or "" for atomic/whole-file
    content: str
    directory: str = field(init=False)  # derived from file_path

    def __post_init__(self) -> None:
        parts = PurePosixPath(self.file_path).parts
        object.__setattr__(self, "directory", parts[0] if len(parts) > 1 else "")
```

`directory` is `""` for root-level files (e.g., `README.md`), first path component for nested files (e.g., `"People"` for `People/Nick/README.md`).

### Import DAG

```
__init__.py   -> (nothing from km)     # Chunk, ChunkConfig, ScanConfig, VaultConfig
config.py     -> __init__              # ChunkConfig, ScanConfig, VaultConfig
chunker.py    -> __init__              # Chunk, ChunkConfig, ScanConfig
store.py      -> __init__              # Chunk (Phase 2)
embedder.py   -> (nothing from km)     # (Phase 3)
search.py     -> config, chunker, store, embedder, __init__  # (Phase 3)
cli.py        -> search, config        # (Phase 4)
```

Config loading (TOML parsing, glob resolution via `PurePosixPath.match()`) lives in `config.py`. The chunker is a pure function that takes text + config and returns chunks.

## Scope Definition

### In Scope

- Project skeleton: pyproject.toml, uv, ruff, pytest
- `Chunk`, `ChunkConfig`, `ScanConfig`, `VaultConfig` dataclasses in `__init__.py`
- `chunk_markdown()` accepting `ChunkConfig` parameter
- `scan_vault()` accepting `ScanConfig` parameter
- Config loading from `.km/config.toml` with fallback to built-in defaults
- Tests for chunker with various config combinations

### Out of Scope

- sqlite-vec store (Phase 2)
- Embedding (Phase 3)
- CLI and `km index` creating `.km/` directory (Phase 4)
- Config file generation/seeding (Phase 4)

## Success Criteria

### Functional Requirements

- [ ] `chunk_markdown()` with default config splits on H1/H2 headers
- [ ] `chunk_markdown()` with `strategy="atomic"` returns single chunk
- [ ] `chunk_markdown()` strips YAML frontmatter when configured
- [ ] `chunk_markdown()` keeps short content as single chunk per `min_chunk_chars`
- [ ] `chunk_markdown()` handles preamble text before first header
- [ ] `chunk_markdown()` returns empty list for empty/whitespace-only input
- [ ] `chunk_markdown()` returns empty list for frontmatter-only files (no body)
- [ ] `scan_vault()` respects include patterns and excludes dotdirs
- [ ] Config loads from TOML file with glob override resolution via `PurePosixPath.match()`
- [ ] Missing config file falls back to built-in defaults
- [ ] `VaultConfig` wraps `ChunkConfig` + `ScanConfig`
- [ ] `directory` field is `""` for root-level files, first path component for nested

### Non-Functional Requirements

- [ ] All Phase 1 tests run in <1s
- [ ] ruff check and format pass clean
- [ ] Import DAG respected: chunker depends only on `__init__`
- [ ] Config loading depends only on stdlib `tomllib` and `pathlib`

## Risk Analysis

### Technical Risks

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| Glob matching edge cases (nested dirs, symlinks) | Low | Medium | Use `pathlib.PurePosixPath.match()` or `fnmatch`; test with real vault paths |
| Config schema evolution (adding new fields later) | Low | High | Defaults for everything; unknown keys ignored; forward-compatible |
| TOML arrays-of-tables (`[[overrides]]`) unfamiliar to users | Low | Low | Config is generated/seeded by `km index`; rarely hand-edited |

## Rejected Alternatives

### Python plugin/strategy pattern

Defining a `ChunkingStrategy` protocol and having client projects provide Python modules. Rejected because Main/ is an Obsidian vault managed by Claude skills via shell, not a Python project. Requiring Python code from the client defeats the purpose.

### Config at vault root (`km.toml`)

A standalone `km.toml` at the vault root, separate from `.km/`. Rejected because the vault already uses the dotfile-directory pattern (`.beads/`, `.claude/`). Keeping config alongside the DB in `.km/` is consistent and groups all km state in one place.

### YAML config format

Matching `.beads/config.yaml`. Rejected because TOML is the Python ecosystem standard (ruff, hatch, mise), Python 3.11+ includes `tomllib` in stdlib (no extra dep), and YAML has ambiguous type coercion edge cases.

### Per-directory config files (cascading)

Separate `km.toml` in each vault subdirectory, merged by walking up. Rejected because the vault is content, not code. Scattering config files across content directories adds noise. Single-file glob overrides (Prettier model) is simpler and auditable.

## References

- Research: [research.md](research.md)
- Tasks: [tasks.md](tasks.md)
- Plan: [../../PLAN.md](../../PLAN.md)
- Precedent: `.beads/config.yaml` in Main/ vault
- Pattern source: Prettier glob overrides, ruff config discovery
