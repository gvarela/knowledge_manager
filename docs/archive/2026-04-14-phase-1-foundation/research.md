---
project: phase-1-foundation
ticket: null
created: 2026-04-14
created_timestamp: 2026-04-14T19:58:34Z
status: complete
last_updated: 2026-04-14
researcher: gvarela
git_commit: not-in-git
git_branch: main
repository: knowledge-manager
tags: [research, codebase, phase-1-foundation]
---

# Research: Phase 1 Foundation

**Created**: 2026-04-14 19:58 UTC
**Last Updated**: 2026-04-14
**Ticket**: N/A

## Research Question

What tooling setup and chunking logic does km need for Phase 1? What are the concrete conventions for pyproject.toml with uv + hatchling, what markdown structures in Main/ inform the chunker design, and what Python dataclass patterns apply to the Chunk type?

## Summary

Phase 1 is greenfield — no existing code. The research covers three areas: (1) how to wire up pyproject.toml with uv + hatchling for a src/ layout CLI package, (2) the actual markdown patterns across 603 files in Main/ that the chunker must handle, and (3) Python 3.12 dataclass conventions for the Chunk value object. Key findings: hatchling requires explicit `packages = ["src/km"]` for src layout discovery; uv uses `[dependency-groups]` (PEP 735) for dev deps, not optional-dependencies; Main/ vault files have inconsistent frontmatter (Meetings/Memory have it, People files don't); and the Chunk dataclass should be `frozen=True, slots=True` with `directory` derived in `__post_init__`.

## Detailed Findings

### pyproject.toml: uv + hatchling + src/ layout

The correct `[build-system]` block for hatchling:

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```

Hatchling does not auto-detect src layouts. You must declare package location explicitly:

```toml
[tool.hatch.build.targets.wheel]
packages = ["src/km"]
```

This tells hatchling: find the package at `src/km/`, install it as `km`.

CLI entry point uses `[project.scripts]`:

```toml
[project.scripts]
km = "km.cli:main"
```

`uv tool install .` reads `[project.scripts]` and places each entry point binary on PATH.

Dev dependencies use `[dependency-groups]` (PEP 735), not `[project.optional-dependencies]`:

```bash
uv add --dev pytest
uv add --group lint ruff
```

Produces:

```toml
[dependency-groups]
dev = ["pytest>=8.1.1,<9"]
lint = ["ruff"]
```

The `dev` group is special-cased by uv — it syncs by default.

Full pyproject.toml structure:

```toml
[project]
name = "knowledge-manager"
version = "0.1.0"
description = "Semantic search for Obsidian vaults"
requires-python = ">=3.12"
dependencies = [
    "fastembed",
    "sqlite-vec",
]

[project.scripts]
km = "km.cli:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/km"]

[dependency-groups]
dev = ["pytest>=8.1.1,<9", "ruff"]

[tool.ruff]
target-version = "py312"
src = ["src"]

[tool.ruff.lint]
select = ["E", "F", "I", "N", "UP", "B", "SIM", "RUF"]

[tool.ruff.format]
quote-style = "double"

[tool.pytest.ini_options]
markers = ["slow: tests that download models or hit disk heavily"]
```

Note: for Phase 1, `fastembed` and `sqlite-vec` are declared but not used yet. The chunker has zero runtime deps.

### Vault Markdown Patterns (from 10 sampled files)

Patterns by file category, documented from actual Main/ vault files:

**People READMEs** (e.g., `People/Noel Miller/README.md`, `People/Vicki Mar/README.md`):
- No YAML frontmatter
- H1 title + role/context line
- H2 sections: Relationship, Current Context, Open Threads, Pending Items, Conversation Log
- Conversation Log is always a table (Date | Topic | Link)
- Heavy wikilink density (`[[People/...]]`, `[[Meetings/...]]`)
- 100-545 words
- Optional metadata line at bottom (`*Last updated: 2026-03-09*`)

**People Dated Notes** (e.g., `People/Jack Schuss/2026-03-26.md`, `People/Noel Miller/2026-02-19.md`):
- No YAML frontmatter
- H1 title with date, H2-H3 hierarchy for topics
- "My Read" section with personal interpretation
- "Action Items" section with assignments
- Heavy wikilinks to related files
- Source/transcript links at end (`*Source: [Granola transcript](...)*`)
- 550-800+ words

**Meetings** (e.g., `Meetings/2026/March/2026-03-30 ELT Offsite - Kari Intro.md`):
- YAML frontmatter: `date`, `type`, `attendees`, `location`, `source`
- H1 title, H2 sections for topics
- Problem-Solution-Decision structure common
- "Action Items" and "My Read" sections
- 400-500 words

**Memory** (e.g., `Memory/2026-04-04-departure-budget-capacity-paradox.md`):
- YAML frontmatter: `type` (pattern|insight|context|signal|reflection), `date`, `source`
- H1 title or no header (just prose)
- Single focused paragraph — 80-110 words
- No wikilinks, no tables
- Already atomic — never needs splitting

**Daily Briefs** (e.g., `Daily/archive/2026-03/2026-03-27.md`):
- No YAML frontmatter
- H1 title with date
- Multiple H2 sections: Focus, Meetings & 1:1s, Tasks Ready, People to Check In, Decisions Pending, Key Dates
- Heavy table usage (Pending Reviews, Key Dates, People tables)
- Emoji in headers
- Inline task IDs (Main-xxxxx)
- Wikilinks throughout
- 900-1000+ words

**Thinking/Research** (e.g., `Thinking/Research/phenoml.md`):
- YAML frontmatter: `type`, `vendor`, `category`, `date`, `depth`
- Multiple H2 sections, some H3
- Heavy tables (specs, pricing, comparisons)
- Code blocks, footnotes, verification indicators
- 2500+ words (longest category)

### Chunking Implications

| Pattern | Chunker Rule |
|---------|-------------|
| YAML frontmatter exists on some files | Strip with regex `r'^---\n.*?\n---\n'` (`re.DOTALL`) before chunking |
| H2 is the universal section boundary | Split on `^#{1,2} ` (H1 and H2). H3 stays within parent chunk. |
| Memory files are 80-110 words, atomic | Short-content rule (<200 chars) keeps these as single chunks automatically |
| People READMEs are 100-545 words | Many will stay as single chunks; longer ones split at H2 |
| Daily briefs have cross-referencing sections | At 900-1000 words with H2 sections, these will split. Cross-references survive via wikilinks in content. |
| Tables span multiple lines but belong to their H2 section | Section-based splitting naturally keeps tables with their header |
| Wikilinks are in content, not stripped | Embedded in chunk text — may help embedding model capture relationships |

### Chunk Dataclass: Python 3.12 Conventions

The Chunk type is a write-once value object (created by chunker, never modified). Python 3.12 best practices:

**Use `frozen=True` + `slots=True`:**
- `frozen=True`: immutable, enables hashing, prevents accidental mutations
- `slots=True`: 30-40% memory reduction across ~1500 instances

**Keep `file_path` as `str`, not `Path`:**
- Always relative, used in string comparisons and DB storage
- `pathlib.Path` has serialization gotchas with most frameworks

**Derive `directory` from `file_path` in `__post_init__`:**
- Single source of truth — callers don't pass redundant data
- With `frozen=True`, must use `object.__setattr__()` in `__post_init__`

```python
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class Chunk:
    file_path: str
    section_header: str
    content: str
    directory: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "directory", self.file_path.split("/")[0])
```

## Architecture Documentation

### Phase 1 Scope

Phase 1 produces two deliverables:

1. **Project skeleton** — pyproject.toml, directory structure, tooling (uv, ruff, pytest)
2. **Chunker module** — `chunk_markdown()` and `scan_vault()` in `src/km/chunker.py`, plus `Chunk` dataclass in `src/km/__init__.py`

No runtime dependencies are exercised in Phase 1. fastembed and sqlite-vec are declared in pyproject.toml but tested in Phases 2-3.

### File Responsibilities

| File | What it contains | Dependencies |
|------|-----------------|-------------|
| `src/km/__init__.py` | `Chunk` dataclass, `__version__ = "0.1.0"` | none |
| `src/km/chunker.py` | `chunk_markdown(text, file_path) -> list[Chunk]`, `scan_vault(vault_path) -> list[Path]` | `km.Chunk`, `re`, `pathlib` |
| `src/km/__main__.py` | `from km.cli import main; main()` (stub for Phase 1) | `km.cli` |
| `tests/conftest.py` | Shared fixtures for sample markdown content | `pytest` |
| `tests/test_chunker.py` | 6 tests covering the chunker | `km.chunker`, `km.Chunk` |

### Conventions Observed

- `uv init --package --build-backend hatchling` generates the base scaffold
- `uv add --dev` for test/lint deps puts them in `[dependency-groups]`
- `[tool.hatch.build.targets.wheel] packages = ["src/km"]` is required for hatchling to find src layout
- ruff and pytest config lives in pyproject.toml (no separate config files)

## Code References

Since this is greenfield, references are to the plan and external docs:

- `PLAN.md:148-202` — Phase 1 definition and TDD steps 1-6
- `PLAN.md:70-88` — Architecture principles and import DAG
- `PLAN.md:114-124` — Chunking strategy
- uv docs: `docs.astral.sh/uv/concepts/projects/layout/` — src layout
- uv docs: `docs.astral.sh/uv/guides/tools/` — uv tool install
- hatch docs: `hatch.pypa.io/latest/config/build/#build-system` — build config

## Similar Implementations

No existing code in this repo. The pattern being followed is standard Python CLI packaging:

- `src/` layout per PEP 517/518
- `[project.scripts]` entry point per PEP 621
- `[dependency-groups]` per PEP 735
- `frozen=True, slots=True` dataclass per Python 3.12 stdlib

## Open Questions

None blocking Phase 1. All tooling and design decisions have been resolved in earlier conversation.

## Next Steps

1. Review this research
2. Run `/create_design docs/plans/2026-04-14-phase-1-foundation` to finalize design
3. Begin TDD implementation (steps 1-6)

## References

- Design: [design.md](design.md)
- Tasks: [tasks.md](tasks.md)
- Plan: [../../PLAN.md](../../PLAN.md)
