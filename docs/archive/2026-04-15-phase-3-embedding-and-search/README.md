# Phase 3: Embedding + Search

**Created**: 2026-04-15
**Ticket**: N/A
**Status**: Planning

## Overview

Phase 3 of the `km` build: fastembed wrapper and orchestration layer. Delivers the Embedder class, Searcher class, SearchResult dataclass, full index pipeline, and incremental update. Composes the Phase 1 chunker/config with the Phase 2 store to enable real semantic search over a markdown vault.

See [PLAN.md](../../../PLAN.md) for the overall project plan (Phase 3 covers steps 19-22).

## Documentation Structure

- **[research.md](research.md)** - Codebase research and findings
- **[design.md](design.md)** - Architectural design decisions
- **[tasks.md](tasks.md)** - Execution plan and task tracking

## Workflow

1. [x] Project structure created
2. [ ] Research phase (`/create_research [directory]`)
3. [ ] Design phase (`/create_design [directory]`)
4. [ ] Execution planning (`/create_execution [directory]`)
5. [ ] Implementation (`/implement_tasks [directory]`)
6. [ ] Testing & Verification

## Quick Commands

```bash
# Continue with research (analyzes codebase)
/create_research docs/plans/2026-04-15-phase-3-embedding-and-search

# Create design decisions
/create_design docs/plans/2026-04-15-phase-3-embedding-and-search

# Generate execution plan with tasks
/create_execution docs/plans/2026-04-15-phase-3-embedding-and-search

# Implement tasks with TDD
/implement_tasks docs/plans/2026-04-15-phase-3-embedding-and-search
```

## Scope (per PLAN.md Phase 3)

- Step 19: `Embedder` wrapping fastembed (`BAAI/bge-small-en-v1.5`, 384 dims)
- Step 20: `Searcher` orchestrates embed → store → results; `SearchResult` dataclass
- Step 21: `index_vault()` full pipeline (scan → chunk → embed → store), honors `index = false`
- Step 22: `update_files()` incremental upsert by file path

Adds `fastembed` to `pyproject.toml` dependencies at start of phase.

## Git Information

- **Branch**: main
- **Commit**: d385d73b0c7364eae8641442b6690e3f263158ab
- **Repository**: knowledge-manager (local-only)
