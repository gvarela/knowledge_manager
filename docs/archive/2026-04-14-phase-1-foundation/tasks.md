---
project: phase-1-foundation
ticket: null
created: 2026-04-14
created_timestamp: 2026-04-14T19:58:34Z
status: in-progress
last_updated: 2026-04-14
assignee: gvarela
current_phase: 1
total_tasks: 14
completed_tasks: 0
git_commit: not-in-git
git_branch: main
repository: knowledge-manager
tags: [tasks, tracking, phase-1-foundation]
beads_epic: km-nlb
beads_tasks:
  skeleton: km-hw6
  config_defaults: km-5zy
  config_toml: km-o7u
  config_overrides: km-i1o
  chunk_single: km-8qh
  chunk_h2: km-jp3
  chunk_mixed: km-cvq
  chunk_preamble: km-0oj
  chunk_frontmatter: km-9nz
  chunk_frontmatter_only: km-kut
  chunk_empty: km-dk6
  chunk_min_chars: km-qmm
  chunk_atomic: km-brk
  scan_vault: km-ncl
---

# Execution Plan: Phase 1 Foundation

## Overview

Implementing project skeleton + config-driven chunker as specified in design.md.

**Design Approach**: Config-driven chunking with vault-scoped .km/ directory
**Target State**: `chunk_markdown()` and `scan_vault()` work with config from `.km/config.toml`

## Implementation Strategy

### Dependency Graph

```
km-hw6 skeleton
  ├── km-5zy config defaults ─── km-o7u load TOML ─── km-i1o glob overrides ──────────────┐
  ├── km-8qh single chunk ── km-jp3 H2 ── km-cvq mixed ── km-0oj preamble                 │
  │                                              ├── km-qmm min_chunk_chars ───────────────┤
  │                          km-cvq ── km-9nz frontmatter ── km-kut frontmatter-only       ├── km-brk atomic
  │   km-8qh ── km-dk6 empty file                                                         │
  └── km-ncl scan vault (needs ScanConfig from km-5zy)                                    │
```

### Testing Strategy

TDD: write failing test first, implement minimum to pass, refactor. Run `uv run pytest -m "not slow"` after every change. All Phase 1 tests are fast (pure Python, no external deps). Phase 1 pyproject.toml has `dependencies = []`.

---

## Step 0: Project Skeleton

**Beads**: `km-hw6` | **Priority**: P1 | **Blocks**: everything

### What to Build

**pyproject.toml** — note `dependencies = []` for Phase 1:

```toml
[project]
name = "knowledge-manager"
version = "0.1.0"
description = "Semantic search for Obsidian vaults"
requires-python = ">=3.12"
dependencies = []

[project.scripts]
km = "km.cli:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/km"]

[dependency-groups]
dev = ["pytest>=8", "ruff"]

[tool.ruff]
target-version = "py312"
src = ["src"]

[tool.ruff.lint]
select = ["E", "F", "I", "N", "UP", "B", "SIM", "RUF"]

[tool.ruff.format]
quote-style = "double"

[tool.pytest.ini_options]
testpaths = ["tests"]
markers = ["slow: tests that download models or hit disk heavily"]
```

**`src/km/__init__.py`** — shared types with `__all__`:

```python
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Literal

__version__ = "0.1.0"

@dataclass(frozen=True, slots=True)
class ChunkConfig:
    split_on: tuple[str, ...] = ("h1", "h2")
    strip_frontmatter: bool = True
    min_chunk_chars: int = 200
    strategy: Literal["default", "atomic"] = "default"

@dataclass(frozen=True, slots=True)
class ScanConfig:
    include: tuple[str, ...] = ("**/*.md",)
    exclude_dotdirs: bool = True

@dataclass(frozen=True, slots=True)
class VaultConfig:
    chunk: ChunkConfig = field(default_factory=ChunkConfig)
    scan: ScanConfig = field(default_factory=ScanConfig)
    overrides: tuple[dict, ...] = ()

@dataclass(frozen=True, slots=True)
class Chunk:
    file_path: str
    section_header: str
    content: str
    directory: str = field(init=False)

    def __post_init__(self) -> None:
        parts = PurePosixPath(self.file_path).parts
        object.__setattr__(self, "directory", parts[0] if len(parts) > 1 else "")

__all__ = ["Chunk", "ChunkConfig", "ScanConfig", "VaultConfig", "__version__"]
```

**Other files**: empty stubs for all modules and test files (see PLAN.md Package Structure).

**Verification**:

```bash
uv sync
uv run pytest          # 0 tests collected, passes
uv run ruff check .    # clean
uv run ruff format --check .  # clean
```

**Commit**: `chore: project skeleton with pyproject.toml and src/km/ layout`

---

## Steps 1-3: Config Module

### Step 1: Config Defaults Without File

**Beads**: `km-5zy` | **Depends on**: `km-hw6`

**Test** (`tests/test_config.py`):

```python
def test_default_config_without_file(tmp_path):
    config = load_config(tmp_path)  # no .km/config.toml exists
    assert config.chunk.split_on == ("h1", "h2")
    assert config.chunk.strip_frontmatter is True
    assert config.chunk.min_chunk_chars == 200
    assert config.chunk.strategy == "default"
    assert "**/*.md" in config.scan.include
    assert config.scan.exclude_dotdirs is True
```

**Implementation**: `load_config(vault_path) -> VaultConfig` returns defaults when no file exists.

**Commit**: `feat: config defaults work without config file`

### Step 2: Load Config from TOML

**Beads**: `km-o7u` | **Depends on**: `km-5zy`

**Test**:

```python
def test_load_config_from_toml(tmp_path):
    km_dir = tmp_path / ".km"
    km_dir.mkdir()
    (km_dir / "config.toml").write_text('[defaults]\nmin_chunk_chars = 500\n')
    config = load_config(tmp_path)
    assert config.chunk.min_chunk_chars == 500
    assert config.chunk.split_on == ("h1", "h2")  # other defaults preserved
```

**Implementation**: Parse `.km/config.toml` with `tomllib`, merge with defaults.

**Commit**: `feat: load chunking config from .km/config.toml`

### Step 3: Override Resolution with Globs

**Beads**: `km-i1o` | **Depends on**: `km-o7u`

**Test**:

```python
def test_override_resolution(tmp_path):
    km_dir = tmp_path / ".km"
    km_dir.mkdir()
    (km_dir / "config.toml").write_text(
        '[defaults]\nsplit_on = ["h1", "h2"]\n\n'
        '[[overrides]]\nfiles = "Memory/**"\nstrategy = "atomic"\n'
    )
    config = load_config(tmp_path)
    resolved = resolve_for_file(config, "Memory/2026-04-04-insight.md")
    assert resolved.strategy == "atomic"

    default = resolve_for_file(config, "People/Nick/README.md")
    assert default.strategy == "default"
```

**Implementation**: `resolve_for_file(config, file_path) -> ChunkConfig` applies matching overrides using `PurePosixPath.match()`.

**Commit**: `feat: glob-based per-file config overrides`

---

## Steps 4-11: Chunker

### Step 4: Single Paragraph Returns One Chunk

**Beads**: `km-8qh` | **Depends on**: `km-5zy`

**Test** (`tests/test_chunker.py`):

```python
def test_single_paragraph_returns_one_chunk():
    config = ChunkConfig()
    text = "This is a simple note with no headers."
    chunks = chunk_markdown(text, "Memory/insight.md", config)
    assert len(chunks) == 1
    assert chunks[0].content == text
    assert chunks[0].file_path == "Memory/insight.md"
    assert chunks[0].directory == "Memory"
    assert chunks[0].section_header == ""
```

**Commit**: `feat: chunk_markdown returns single chunk for plain text`

### Step 5: Split on H2 Headers

**Beads**: `km-jp3` | **Depends on**: `km-8qh`

**Test**:

```python
def test_splits_on_h2_headers():
    config = ChunkConfig()
    text = "## Notes\nSome notes here.\n\n## Actions\nDo stuff."
    chunks = chunk_markdown(text, "Meetings/standup.md", config)
    assert len(chunks) == 2
    assert chunks[0].section_header == "## Notes"
    assert chunks[1].section_header == "## Actions"
```

**Commit**: `feat: chunk_markdown splits on H2 headers`

### Step 6: Split on Mixed H1 and H2

**Beads**: `km-cvq` | **Depends on**: `km-jp3`

**Test**:

```python
def test_splits_on_h1_and_h2():
    config = ChunkConfig()
    text = "# Title\nIntro paragraph.\n\n## Section\nBody content."
    chunks = chunk_markdown(text, "Thinking/idea.md", config)
    assert len(chunks) == 2
    assert chunks[0].section_header == "# Title"
    assert chunks[1].section_header == "## Section"
```

**Commit**: `feat: chunk_markdown handles mixed H1 and H2 headers`

### Step 7: Preamble Before First Header

**Beads**: `km-0oj` | **Depends on**: `km-cvq`

**Test**:

```python
def test_preamble_before_first_header():
    config = ChunkConfig()
    text = "Some intro text.\n\n## Section\nBody content."
    chunks = chunk_markdown(text, "People/Nick/README.md", config)
    assert len(chunks) == 2
    assert chunks[0].section_header == ""
    assert "Some intro text." in chunks[0].content
    assert chunks[1].section_header == "## Section"
```

**Commit**: `feat: text before first header becomes its own chunk`

### Step 8: Strip YAML Frontmatter

**Beads**: `km-9nz` | **Depends on**: `km-cvq`

**Test**:

```python
def test_strips_yaml_frontmatter():
    config = ChunkConfig(strip_frontmatter=True)
    text = "---\ntype: pattern\ndate: 2026-04-04\n---\n\n## Notes\nContent here."
    chunks = chunk_markdown(text, "Memory/insight.md", config)
    assert len(chunks) == 1
    assert "---" not in chunks[0].content
    assert "Content here." in chunks[0].content
```

**Implementation**: Regex `r'^---\n.*?\n---\n?'` with `re.DOTALL` — trailing newline optional.

**Commit**: `feat: strip YAML frontmatter from markdown before chunking`

### Step 9: Frontmatter-Only File Returns Empty

**Beads**: `km-kut` | **Depends on**: `km-9nz`

**Test**:

```python
def test_frontmatter_only_returns_empty():
    config = ChunkConfig(strip_frontmatter=True)
    text = "---\ntype: stub\ndate: 2026-04-04\n---\n"
    chunks = chunk_markdown(text, "Memory/stub.md", config)
    assert chunks == []
```

**Commit**: `feat: frontmatter-only files return empty chunk list`

### Step 10: Empty File Returns Empty

**Beads**: `km-dk6` | **Depends on**: `km-8qh`

**Test**:

```python
def test_empty_file_returns_empty():
    config = ChunkConfig()
    assert chunk_markdown("", "empty.md", config) == []
    assert chunk_markdown("   \n\n  ", "blank.md", config) == []
```

**Commit**: `feat: empty or whitespace-only input returns empty list`

### Step 11: Short Sections Stay as Single Chunk

**Beads**: `km-qmm` | **Depends on**: `km-cvq`

**Test**:

```python
def test_short_sections_stay_as_single_chunk():
    config = ChunkConfig(min_chunk_chars=200)
    # Total content is short even though it has headers
    text = "# Title\nShort.\n\n## Section\nAlso short."
    chunks = chunk_markdown(text, "Memory/brief.md", config)
    assert len(chunks) == 1  # below threshold, stays as one chunk
```

**Commit**: `feat: min_chunk_chars threshold keeps short content as one chunk`

---

## Step 12: Atomic Strategy

**Beads**: `km-brk` | **Depends on**: `km-i1o`, `km-9nz`, `km-qmm`

**Test**:

```python
def test_atomic_strategy_returns_single_chunk():
    config = ChunkConfig(strategy="atomic")
    text = "# Title\nIntro.\n\n## Section One\nContent.\n\n## Section Two\nMore."
    chunks = chunk_markdown(text, "Daily/2026-04-14.md", config)
    assert len(chunks) == 1
    assert "Section One" in chunks[0].content
    assert "Section Two" in chunks[0].content
```

**Commit**: `feat: atomic chunking strategy skips splitting`

---

## Step 13: Scan Vault

**Beads**: `km-ncl` | **Depends on**: `km-5zy`

**Test**:

```python
def test_scan_vault_finds_markdown_files(tmp_path):
    (tmp_path / "People").mkdir()
    (tmp_path / "People" / "alice.md").write_text("# Alice")
    (tmp_path / "People" / "notes.txt").write_text("ignore")
    (tmp_path / ".obsidian").mkdir()
    (tmp_path / ".obsidian" / "config.md").write_text("ignore")
    (tmp_path / ".km").mkdir()
    (tmp_path / ".km" / "index.db").write_text("ignore")

    config = ScanConfig()  # defaults: include *.md, exclude dotdirs
    files = scan_vault(tmp_path, config)
    assert len(files) == 1
    assert files[0].name == "alice.md"
```

**Commit**: `feat: scan_vault filters markdown files with ScanConfig`

---

## Verification

After all steps:

```bash
uv run pytest -m "not slow" -v    # all 13+ tests pass
uv run ruff check .               # clean
uv run ruff format --check .      # clean
bd list --status=open              # should show 0 open Phase 1 tasks
```

---

## Beads Issue Tracking

**Epic**: `km-nlb` — Phase 1: Foundation

| Step | Beads ID | Title |
|------|----------|-------|
| 0 | `km-hw6` | Project skeleton |
| 1 | `km-5zy` | Config defaults without file |
| 2 | `km-o7u` | Load config from TOML |
| 3 | `km-i1o` | Override resolution with globs |
| 4 | `km-8qh` | Single paragraph returns one chunk |
| 5 | `km-jp3` | Split on H2 headers |
| 6 | `km-cvq` | Split on mixed H1 and H2 |
| 7 | `km-0oj` | Preamble before first header |
| 8 | `km-9nz` | Strip YAML frontmatter |
| 9 | `km-kut` | Frontmatter-only returns empty |
| 10 | `km-dk6` | Empty file returns empty |
| 11 | `km-qmm` | Short sections stay as single chunk |
| 12 | `km-brk` | Atomic strategy returns single chunk |
| 13 | `km-ncl` | Scan vault with config filters |

**Commands**:

```bash
bd ready                # see what's unblocked
bd show km-hw6          # view task details
bd close km-hw6         # complete a task
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

- Config at `.km/config.toml` — not baked into km code
- `VaultConfig` wraps `ChunkConfig` + `ScanConfig` — `load_config()` returns it
- `ChunkConfig` passed to chunker — chunker never reads config files
- `frozen=True, slots=True` on all dataclasses, `__all__` in `__init__.py`
- `directory` derived from `file_path` via `PurePosixPath.parts` — `""` for root files
- Glob matching via `PurePosixPath.match()` — not `fnmatch`
- Frontmatter regex: `r'^---\n.*?\n---\n?'` — trailing newline optional
- `exclude_dotdirs = true` as default — covers all `.` directories in one rule
- `index = false` filtered post-scan by Searcher, not by `scan_vault`
- Phase 1 has `dependencies = []` — fastembed/sqlite-vec added in later phases
