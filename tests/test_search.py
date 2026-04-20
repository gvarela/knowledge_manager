import sqlite3
from pathlib import Path

import pytest

from km import Chunk, VaultConfig
from km.search import Searcher, SearchResult, _should_index
from km.store import Store


class FakeEmbedder:
    def __init__(self, table: dict[str, list[float]]):
        self._table = table

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._table[t] for t in texts]


def test_search_returns_results_ordered_by_distance(tmp_path: Path) -> None:
    km_dir = tmp_path / ".km"
    km_dir.mkdir()
    db_path = km_dir / "index.db"

    with Store(db_path) as store:
        store.bulk_insert(
            [
                (Chunk("a.md", "", "alpha content"), [1.0] + [0.0] * 383),
                (Chunk("b.md", "", "beta content"), [0.0, 1.0] + [0.0] * 382),
                (Chunk("c.md", "", "gamma content"), [0.0, 0.0, 1.0] + [0.0] * 381),
            ]
        )

        fake_embedder = FakeEmbedder({"alpha query": [1.0] + [0.0] * 383})
        searcher = Searcher(tmp_path, store=store, embedder=fake_embedder)
        results = searcher.search("alpha query", k=2)

        assert len(results) == 2
        assert all(isinstance(r, SearchResult) for r in results)
        assert results[0].chunk.file_path == "a.md"
        assert results[0].distance <= results[1].distance


def test_search_returns_empty_on_empty_store(tmp_path: Path) -> None:
    km_dir = tmp_path / ".km"
    km_dir.mkdir()
    db_path = km_dir / "index.db"

    with Store(db_path) as store:
        fake_embedder = FakeEmbedder({"anything": [0.0] * 384})
        searcher = Searcher(tmp_path, store=store, embedder=fake_embedder)
        results = searcher.search("anything")

        assert results == []


def test_searcher_context_manager_closes_owned_store(tmp_path: Path) -> None:
    km_dir = tmp_path / ".km"
    km_dir.mkdir()

    fake_embedder = FakeEmbedder({})

    # Owned store: should be closed after exiting context manager
    with Searcher(tmp_path, embedder=fake_embedder) as searcher:
        searcher._store.stats()  # should work inside the block

    with pytest.raises(sqlite3.ProgrammingError):
        searcher._store.stats()  # should fail after close

    # External store: should NOT be closed after exiting context manager
    db_path = km_dir / "external.db"
    external_store = Store(db_path)
    with Searcher(tmp_path, store=external_store, embedder=fake_embedder) as searcher:
        pass

    # External store should still be open
    external_store.stats()
    external_store.close()


class ConstantEmbedder:
    """Returns a fixed vector for any text. For index_vault tests."""

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.1] * 384 for _ in texts]


def test_index_vault_runs_full_pipeline(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text("# Hello\nworld", encoding="utf-8")
    (tmp_path / "b.md").write_text("# Goodbye\nuniverse", encoding="utf-8")

    with Searcher(tmp_path, embedder=ConstantEmbedder()) as searcher:
        result = searcher.index_vault()

    assert result["files"] == 2
    assert result["chunks"] >= 2


def test_index_vault_skips_files_with_index_false_override(tmp_path: Path) -> None:
    (tmp_path / "keep.md").write_text("# Keep\nimportant stuff", encoding="utf-8")
    inbox = tmp_path / "Inbox" / "processed"
    inbox.mkdir(parents=True)
    (inbox / "skip.md").write_text("# Skip\nthis should be excluded", encoding="utf-8")

    km_dir = tmp_path / ".km"
    km_dir.mkdir()
    (km_dir / "config.toml").write_text(
        '[[overrides]]\nfiles = "Inbox/processed/**"\nindex = false\n',
        encoding="utf-8",
    )

    with Searcher(tmp_path, embedder=ConstantEmbedder()) as searcher:
        result = searcher.index_vault()

    assert result["files"] == 1
    assert result["chunks"] >= 1


def test_index_vault_clears_existing_chunks_first(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text("# First\noriginal content", encoding="utf-8")

    with Searcher(tmp_path, embedder=ConstantEmbedder()) as searcher:
        searcher.index_vault()

        (tmp_path / "a.md").write_text("# Second\nnew content", encoding="utf-8")
        result = searcher.index_vault()

        stats = searcher._store.stats()

    assert result["chunks"] == stats["chunks"]
    assert stats["files"] == 1


def test_update_files_replaces_existing_chunks(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text("# Alpha\noriginal alpha", encoding="utf-8")
    (tmp_path / "b.md").write_text("# Beta\noriginal beta", encoding="utf-8")

    with Searcher(tmp_path, embedder=ConstantEmbedder()) as searcher:
        searcher.index_vault()
        stats_before = searcher._store.stats()
        assert stats_before["files"] == 2

        # Modify one file to have more chunks
        (tmp_path / "a.md").write_text(
            "# Alpha\nrevised alpha\n\n# Part Two\nmore content here",
            encoding="utf-8",
        )
        result = searcher.update_files(["a.md"])

        assert result["files"] == 1
        stats_after = searcher._store.stats()
        assert stats_after["files"] == 2  # both files still present
        # a.md now has more chunks
        assert stats_after["chunks"] >= stats_before["chunks"]


def test_update_files_deletes_missing_files(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text("# Alpha\nalpha content", encoding="utf-8")
    (tmp_path / "b.md").write_text("# Beta\nbeta content", encoding="utf-8")

    with Searcher(tmp_path, embedder=ConstantEmbedder()) as searcher:
        searcher.index_vault()
        assert searcher._store.stats()["files"] == 2

        (tmp_path / "b.md").unlink()
        result = searcher.update_files(["b.md"])

        assert result["files"] == 1
        assert result["chunks"] == 0
        assert searcher._store.stats()["files"] == 1


def test_update_files_skips_index_false_paths(tmp_path: Path) -> None:
    km_dir = tmp_path / ".km"
    km_dir.mkdir()
    (km_dir / "config.toml").write_text(
        '[[overrides]]\nfiles = "Inbox/**"\nindex = false\n',
        encoding="utf-8",
    )
    inbox = tmp_path / "Inbox"
    inbox.mkdir()
    (inbox / "skip.md").write_text("# Skip\nskip this", encoding="utf-8")
    (tmp_path / "keep.md").write_text("# Keep\nkeep this", encoding="utf-8")

    with Searcher(tmp_path, embedder=ConstantEmbedder()) as searcher:
        searcher.index_vault()
        stats_before = searcher._store.stats()
        assert stats_before["files"] == 1  # only keep.md indexed

        result = searcher.update_files(["Inbox/skip.md"])

        assert result["files"] == 0  # skipped, not processed
        assert result["chunks"] == 0
        assert searcher._store.stats() == stats_before  # unchanged


def test_update_files_on_never_indexed_path_inserts(tmp_path: Path) -> None:
    (tmp_path / "new.md").write_text("# New\nbrand new content", encoding="utf-8")

    with Searcher(tmp_path, embedder=ConstantEmbedder()) as searcher:
        assert searcher._store.stats() == {"files": 0, "chunks": 0}

        result = searcher.update_files(["new.md"])

        assert result["files"] == 1
        assert result["chunks"] >= 1
        stats = searcher._store.stats()
        assert stats["files"] == 1
        assert stats["chunks"] >= 1


def test_should_index_helper_first_match_wins() -> None:
    config = VaultConfig(
        overrides=(
            {"files": "Inbox/*", "index": False},
            {"files": "Inbox/*.md"},
        ),
    )

    # Both overrides match Inbox/note.md, first one wins → index=False
    assert _should_index(config, "Inbox/note.md") is False
    # No override matches Other/note.md → default True
    assert _should_index(config, "Other/note.md") is True


def test_sync_detects_new_deleted_and_unchanged(tmp_path: Path) -> None:
    """sync() adds new files, removes deleted files, skips unchanged."""
    (tmp_path / "keep.md").write_text("# Keep\nkeep this", encoding="utf-8")
    (tmp_path / "delete_me.md").write_text("# Delete\ndelete this", encoding="utf-8")

    with Searcher(tmp_path, embedder=ConstantEmbedder()) as searcher:
        searcher.index_vault()
        assert searcher._store.stats()["files"] == 2

        # Simulate move: delete one file, add a new one
        (tmp_path / "delete_me.md").unlink()
        (tmp_path / "new.md").write_text("# New\nnew content", encoding="utf-8")

        result = searcher.sync()

        assert result["added"] == 1
        assert result["removed"] == 1
        stats = searcher._store.stats()
        assert stats["files"] == 2  # keep.md + new.md
        paths = searcher._store.file_paths()
        assert "keep.md" in paths
        assert "new.md" in paths
        assert "delete_me.md" not in paths
