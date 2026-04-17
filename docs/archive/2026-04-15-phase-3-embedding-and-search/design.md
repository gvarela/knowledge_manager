---
project: phase-3-embedding-and-search
ticket: null
created: 2026-04-15
created_timestamp: 2026-04-15T18:50:17Z
status: complete
last_updated: 2026-04-16
designer: gvarela
git_commit: d385d73b0c7364eae8641442b6690e3f263158ab
git_branch: main
repository: knowledge-manager
tags: [design, architecture, phase-3-embedding-and-search]
depends_on: research.md
design_approach: thin-adapter-plus-orchestrator
---

# Design: Phase 3 — Embedding + Search

**Created**: 2026-04-15
**Last Updated**: 2026-04-15
**Designer**: gvarela
**Ticket**: N/A
**Status**: Draft

## Problem Statement

The `km` package can chunk a vault and store/retrieve vectors via SQLite, but it has no real embeddings and no orchestration layer. Phase 3 closes that gap: we need a class that turns text into 384-dim float vectors and a class that drives the full pipeline (scan → chunk → embed → store → search) and supports incremental updates after a single file changes.

Without this phase, the pipeline cannot run end-to-end on real data — `embedder.py` and `search.py` are empty files, `cli.py` raises `SystemExit("not yet implemented")`, and the only proof Phase 1 + 2 compose is a scratch script using fake vectors.

### Success Metrics

- Indexing the Main/ vault end-to-end with real embeddings completes without manual intervention.
- A semantic query returns ranked chunks whose ordering matches what a human would call "most relevant" for non-trivial test queries (manual eval — formal eval is Phase 5).
- Updating 6-7 files (typical State Update Rule output) takes <2 seconds wall time on warm cache.
- The fast TDD loop (`uv run pytest -m "not slow"`) stays under 2 seconds and never downloads a model.
- Phase 3 lands behind the existing import DAG and dataclass conventions with zero changes to Phase 1 / Phase 2 modules.

## Design Approach

**Two layers, one orchestrator.**

The first layer is a thin adapter (`Embedder`) over `fastembed.TextEmbedding`. Plain Python types in and out — strings on the way in, native `list[list[float]]` on the way out — with no `km` imports. This isolates the third-party library so it can be swapped (or mocked in tests) without touching domain types.

The second layer is an orchestrator (`Searcher`) that owns the vault root, holds a `Store`, accepts an `Embedder` (injectable for tests), and composes the existing chunker + config + store APIs into three operations: `search(query, k)`, `index_vault()`, `update_files(paths)`. A `SearchResult` dataclass is the typed return shape.

Per file, the orchestrator does what the e2e demo already proved correct: read text → resolve `ChunkConfig` for that file → `chunk_markdown(...)` → batch into the embedder once per `index_vault` → bulk-insert. For incremental updates, the same pipeline runs per file but writes via `Store.upsert_file`.

### Why This Approach

- **The Store template already exists.** `Store` is a single-library wrapper with a small public surface, context-manager lifecycle, and dimension validation at the boundary. `Embedder` is the same shape against `fastembed`. We are reproducing a pattern, not inventing one.
- **No new abstractions for a single caller.** `Searcher` is the sole consumer of `index = false`, the sole place where absolute scan paths convert to vault-relative chunk paths, and the sole orchestrator of embed → store. Keeping all three responsibilities in one class avoids helper modules with one user.
- **Duck typing matches the codebase precedent.** The repo has zero `Mock`, `monkeypatch`, or `Protocol` declarations. Tests use real implementations with fake data. The mocking story for Searcher is "pass a small fake class to the constructor" — same idiom, no new ceremony.
- **The cache lives where the rest of the vault state lives.** `.km/` already holds `config.toml` and `index.db`. Putting model weights at `.km/models/` makes the vault self-contained and persistent across reboots (the OS may wipe `/tmp`).
- **L2 distance is correct without schema changes.** BGE outputs are L2-normalized and sqlite-vec's default L2 distance is monotonic in cosine similarity for unit vectors (research §"Distance metric compatibility"). Phase 2's `vec0` schema needs no modifier; the existing Store works as-is.

## Technical Decisions

### Architecture

**`src/km/embedder.py` — `Embedder` class wrapping `fastembed.TextEmbedding`.**
- Plain string input, plain `list[list[float]]` output.
- No imports from `km.*`. Owns the model name, dimension, and cache directory as constructor parameters.
- Validates output dimension matches the declared `dim` to fail fast on misconfiguration (mirrors `Store._check_dim` at `store.py:53-57`).
- Defers model download until first use so that `import km` does not pull ~68 MB across the network.
- *Trade-off:* eager construction surfaces download errors at startup, lazy construction surfaces them at first query. Lazy is the right default for a CLI that may be invoked just to print `--help` or `stats`.

**`src/km/search.py` — `Searcher` class composing config + chunker + store + embedder.**
- Constructor accepts the vault root and optionally accepts the `Store` and `Embedder` (defaults construct them from `.km/index.db` and `.km/models/`).
- Owns the `Store` lifecycle through the context-manager protocol so callers can use it the same way they use `Store` today.
- Three public methods: `search`, `index_vault`, `update_files`. Stats and clear pass through to `Store` if needed (or stay on `Store` directly — Searcher is not a god class).
- The orchestrator is also where `index = false` filtering lives; it walks `VaultConfig.overrides` directly. *Rationale:* `resolve_for_file` returns a `ChunkConfig` and `ChunkConfig` has no `index` field; adding one would force every dataclass consumer to deal with a field they do not care about. The override list is already a `tuple[dict, ...]` in `VaultConfig` — Searcher reads it.

**`SearchResult` dataclass in `search.py`.**
- Frozen, slots, two fields: `chunk: Chunk`, `distance: float`. A typed wrapper over what `Store.knn_search` already returns as `list[tuple[Chunk, float]]`.
- *Rationale:* the public API of `Searcher.search` should not leak tuples — callers (CLI, future skill integrations) read `.chunk.file_path` and `.distance` more legibly than `result[0].file_path` and `result[1]`.

**Import DAG addition.**

```
embedder.py → (nothing from km)                        ← unchanged target from PLAN.md
search.py   → __init__, config, chunker, store, embedder
cli.py      → search, config (Phase 4)
```

No existing module imports change.

### Data Model

**`SearchResult`** — single new type:

```
SearchResult
├── chunk:    Chunk     (file_path, section_header, content, directory)
└── distance: float     (lower = closer; sqlite-vec's L2 distance)
```

No new persistent schema. `Store`'s two tables and `vec0` virtual table are unchanged.

**Embeddings on the wire** — fastembed returns numpy `float32` arrays from a generator. Embedder materializes the generator and converts each row via `.tolist()` so that everything downstream (Store, JSON output in Phase 4, tests) deals only in native Python lists.

**Batching shape** — `index_vault` collects all `(chunk, text)` pairs into a single list, calls `embedder.embed(texts)` once, and zips the results back. fastembed's default `batch_size=256` does the actual ONNX batching internally. This means peak memory holds all chunks for the vault at once. For the target vault (~5K chunks of ~500 chars = ~2.5 MB of strings + ~7.5 MB of float vectors), this is negligible. If a future vault gets large enough to matter, `index_vault` can stream by passing a generator to `embedder.embed` — the API does not change.

### Integration Points

- **Reads** `.km/config.toml` via `load_config(vault_root)` and per-file `ChunkConfig` via `resolve_for_file(config, relative_path)`.
- **Reads** the vault filesystem via `scan_vault(vault_root, config.scan)` and `Path.read_text()` per file.
- **Writes** to `.km/index.db` via `Store.bulk_insert` (full index) and `Store.upsert_file` (incremental update).
- **Reads** from `.km/index.db` via `Store.knn_search`.
- **Writes** model weights to `.km/models/` via fastembed's `cache_dir` parameter.
- **Will be consumed** by `cli.py` in Phase 4 — `cli.py` parses args, constructs `Searcher(vault_root)`, calls one of three methods, formats output. No other consumer in this phase.

### Behavioral contracts

- **`Searcher.index_vault()`** — full rebuild. Calls `Store.clear()` first, then scans + chunks + embeds + bulk-inserts every indexable file. Returns a small stats dict (files indexed, chunks produced) for the CLI to report. Files where the resolved override has `index = false` are skipped silently.
- **`Searcher.update_files(paths)`** — incremental upsert. For each vault-relative path: if the file exists on disk and is indexable, re-chunk + re-embed + `upsert_file(path, items)`. If the file no longer exists, call `upsert_file(path, [])` to delete its chunks. Returns the same stats shape as `index_vault`. Same `index = false` filter applies.
- **`Searcher.search(query, k=10)`** — embed the query, call `Store.knn_search`, wrap each `(chunk, distance)` in a `SearchResult`. No re-ranking, no filtering — `cli.py` and downstream skills do that.

## Scope Definition

### In Scope

- `Embedder` class wrapping `fastembed.TextEmbedding` with `model_name`, `cache_dir`, `dim` parameters and an `embed(texts)` method.
- `Searcher` class with `search`, `index_vault`, `update_files` methods and context-manager protocol.
- `SearchResult` dataclass.
- `index = false` filtering inside `Searcher`.
- One `@pytest.mark.slow` integration test that exercises `Embedder` against the real model (downloads on first run).
- Searcher tests that use a small in-test `FakeEmbedder` class (no `Mock`, no `Protocol`).
- Adding `fastembed` to `pyproject.toml` dependencies.

### Out of Scope

- The `km` CLI itself (Phase 4).
- `.km/` auto-discovery from `cwd` (Phase 4).
- `km config show/set/get` subcommands (Phase 4).
- JSON output formatting (Phase 4).
- Real-world quality evaluation against Main/ with a golden dataset (Phase 5).
- Multi-model support beyond the constructor parameter — no model registry, no automatic dim detection.
- Re-ranking, filtering, score normalization (cosine vs L2 vs dot product as a user-facing knob).
- Embedding cache invalidation by file hash — `update_files` always re-embeds the files it is given.
- Concurrency / async — Searcher is single-threaded.
- GPU acceleration — CPU-only via the standard `fastembed` package; `fastembed-gpu` is not pulled in.

## Success Criteria

### Functional Requirements

- [ ] `Embedder().embed(["hello"])` returns `[[float]]` with the inner list of length 384.
- [ ] `Embedder` rejects (or is constructed with) a `dim` mismatch loudly — no silent dimension drift.
- [ ] `Searcher(vault_root).index_vault()` runs scan → chunk → embed → store with one bulk embed call.
- [ ] `Searcher.update_files(["People/Bob.md"])` deletes existing chunks for that path and inserts new ones in one transaction (via `Store.upsert_file`).
- [ ] `Searcher.update_files(["deleted.md"])` removes that file's chunks when the file is missing on disk.
- [ ] `Searcher.search("query", k=5)` returns a list of `SearchResult` ordered by ascending `distance`.
- [ ] Files with a matching override containing `index = false` are skipped during `index_vault` and `update_files`.

### Non-Functional Requirements

- [ ] **Test isolation.** `uv run pytest -m "not slow"` runs without downloading any model and finishes in <2s on a warm cache.
- [ ] **Slow test marker.** Exactly one test exercises real `fastembed` and is gated by `@pytest.mark.slow`.
- [ ] **Import hygiene.** `embedder.py` has zero `from km` imports. `search.py` imports only from `km` modules listed in the DAG.
- [ ] **Vault-local cache.** Model weights land under `.km/models/` by default, not `/tmp`.
- [ ] **No regressions.** All Phase 1 + Phase 2 tests still pass unchanged.
- [ ] **Lint clean.** `uv run ruff check .` passes.

## Risk Analysis

### Technical Risks

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| fastembed model download fails or is slow on first run | Medium — blocks first index, not the dev loop | Medium | `lazy_load=True` so import never blocks; cache to `.km/models/` so subsequent runs are offline; document the first-run cost in README/CLAUDE.md |
| Tests accidentally trigger model download | High — breaks fast TDD loop | Medium | Single `@pytest.mark.slow` test for real fastembed; all `Searcher` tests inject `FakeEmbedder`; CI pinned to `pytest -m "not slow"` for the fast lane |
| L2 distance ranking diverges from semantic intent | High — silent quality regression | Low | BGE outputs are normalized (verified in fastembed source); L2 ranking equals cosine ranking for unit vectors (math verified in research); golden-dataset eval in Phase 5 catches drift |
| Memory footprint of single-batch embedding grows past tolerable | Low at current vault size | Low | Vault is ~5K chunks; if it grows 10x we switch `index_vault` to stream a generator into `embed()` — same Embedder API |
| `index = false` filtering has subtle glob mismatches | Medium — wrong files get indexed/skipped | Low | Reuse `PurePosixPath.match` (the same matcher `resolve_for_file` already uses); explicit test for the filter |
| fastembed major version bump breaks the wrapper | Medium | Medium over time | Pin to a major version range in `pyproject.toml`; the adapter surface is small (one `embed` call) so any break is contained |

### Assumptions

| Assumption | Validation strategy |
|------------|---------------------|
| `BAAI/bge-small-en-v1.5` produces semantically reasonable rankings on Obsidian markdown | Phase 5 manual evaluation with real queries (`/librarian find` misses) |
| One bulk `embed()` call per index is faster than per-file calls due to model warmup amortization | Measure during Phase 5; if false, switch to streaming with negligible code change |
| `.km/models/` is an acceptable place to put a 68 MB binary in the vault directory | User has explicitly chosen the `.km/` pattern in PLAN.md; reversible by passing `cache_dir=None` to fall back to the system temp |
| `.gitignore` / vault-sync tools tolerate `.km/` (existing pattern from Phase 1+2) | Already true — `.km/` is the established convention |

## Rejected Alternatives

### Option: `EmbedderProtocol` in `__init__.py` for Searcher injection

- **Approach**: Define a `Protocol` with `embed(texts: list[str]) -> list[list[float]]`; have `Searcher` declare `embedder: EmbedderProtocol`.
- **Rejected because**: The codebase has zero existing `Protocol` declarations and zero existing mocks. Adding a typing layer for one consumer (Searcher tests) is ceremony without payoff. Duck typing — pass a `FakeEmbedder` class with the right method — gives the same testability with less code.
- **Trade-off given up**: Static type-checker coverage for the embedder argument. Acceptable given current tooling (ruff only — no mypy in `pyproject.toml`).

### Option: Extend `resolve_for_file` to return `(ChunkConfig, indexed: bool)`

- **Approach**: Make the config layer the authority on whether a file is indexable.
- **Rejected because**: `ChunkConfig` is the natural typed result of `resolve_for_file` and is consumed by `chunk_markdown` (which has no business knowing about indexing). Returning a tuple forces `chunker.py` and any future caller to either deconstruct it or ignore half of it. Indexing is a Searcher concern, not a chunker concern.
- **Trade-off given up**: Centralization of "what does this file's config mean" in one function. Acceptable — the override dicts in `VaultConfig.overrides` are a perfectly fine source of truth for the one consumer that needs the `index` key.

### Option: Per-file embedding inside `index_vault`

- **Approach**: Loop over files, call `embedder.embed(chunks_of_this_file)` per file.
- **Rejected because**: Pays the model warmup cost once per file instead of once per index. fastembed's internal `batch_size=256` already handles the actual GPU/CPU batching — the wrapper's job is to hand it as much work as possible per call. At target vault size, all chunks fit in memory comfortably.
- **Trade-off given up**: Lower peak memory. Reversible without API change if needed.

### Option: Use `query_embed()` for the search path

- **Approach**: Distinguish query embedding from passage embedding via different methods.
- **Rejected because**: For `BAAI/bge-small-en-v1.5`, fastembed's `query_embed` and `embed` produce identical output (verified in `fastembed/text/text_embedding_base.py` — both methods fall through to `embed` for this model). Using `embed([query])[0]` keeps the wrapper symmetric and avoids implying behavior that does not exist for the chosen model.
- **Trade-off given up**: Future-proofing against a model that does need query/passage prefixes. If we switch models, we add a `embed_query` method then — explicit change, not silent.

### Option: System-default `/tmp/fastembed_cache` (no `cache_dir` override)

- **Approach**: Trust fastembed's default cache path.
- **Rejected because**: macOS may purge `/tmp` on reboot (and `tempfile.gettempdir()` resolves to `/var/folders/.../T/...` which is also subject to cleanup). Re-downloading 68 MB on every reboot is a poor default. Vault-local cache survives reboots and follows the `.km/` pattern.
- **Trade-off given up**: 68 MB lives in the vault directory tree (not synced if `.km/` is in `.gitignore`/Obsidian sync excludes — which it should be).

## Pending Decisions

None blocking execution. All architectural calls in this document are made. If something should change, it can be revisited during the execution phase by amending this document — research findings stay valid either way.

## References

- Research: [research.md](research.md)
- Tasks: [tasks.md](tasks.md)
- Overall plan: [PLAN.md](../../../PLAN.md)
- Phase 1 design: [../2026-04-14-phase-1-foundation/design.md](../2026-04-14-phase-1-foundation/design.md)
- Phase 2 design: [../2026-04-14-phase-2-storage/design.md](../2026-04-14-phase-2-storage/design.md)
- fastembed source (TextEmbedding): https://github.com/qdrant/fastembed/blob/main/fastembed/text/text_embedding.py
- BGE model card: https://huggingface.co/BAAI/bge-small-en-v1.5
- sqlite-vec KNN: https://alexgarcia.xyz/sqlite-vec/features/knn.html
