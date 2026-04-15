import pytest

from km import Chunk


def test_create_store_and_insert_chunk(store):
    chunk = Chunk(
        file_path="People/alice.md", section_header="## Notes", content="Alice is kind."
    )
    embedding = [0.1] * 384
    chunk_id = store.insert(chunk, embedding)
    assert chunk_id == 1
    assert store.stats() == {"files": 1, "chunks": 1}


def test_bulk_insert_and_stats(store):
    items = [
        (
            Chunk(
                file_path="People/alice.md",
                section_header="## Notes",
                content="Alice.",
            ),
            [0.1] * 384,
        ),
        (
            Chunk(
                file_path="People/alice.md",
                section_header="## Actions",
                content="Follow up.",
            ),
            [0.2] * 384,
        ),
        (
            Chunk(
                file_path="Meetings/standup.md",
                section_header="",
                content="Daily standup.",
            ),
            [0.3] * 384,
        ),
    ]
    store.bulk_insert(items)
    stats = store.stats()
    assert stats["files"] == 2
    assert stats["chunks"] == 3


def test_knn_search_returns_nearest(store):
    # Insert chunks with distinct embeddings
    items = [
        (
            Chunk(file_path="a.md", section_header="", content="Alpha"),
            [1.0] + [0.0] * 383,
        ),
        (
            Chunk(file_path="b.md", section_header="", content="Beta"),
            [0.0] + [1.0] + [0.0] * 382,
        ),
        (
            Chunk(file_path="c.md", section_header="", content="Gamma"),
            [0.9] + [0.1] + [0.0] * 382,
        ),
    ]
    store.bulk_insert(items)
    # Query near Alpha's embedding
    results = store.knn_search([1.0] + [0.0] * 383, k=2)
    assert len(results) == 2
    assert results[0][0].content == "Alpha"  # nearest
    assert results[1][0].content == "Gamma"  # second nearest
    # Each result is (Chunk, distance)
    assert results[0][1] < results[1][1]  # distances are ordered


def test_upsert_replaces_chunks_for_file(store):
    # Insert initial chunks
    store.bulk_insert(
        [
            (
                Chunk(
                    file_path="People/alice.md",
                    section_header="## v1",
                    content="Old content.",
                ),
                [0.1] * 384,
            ),
            (
                Chunk(
                    file_path="Meetings/standup.md",
                    section_header="",
                    content="Standup.",
                ),
                [0.2] * 384,
            ),
        ]
    )
    assert store.stats() == {"files": 2, "chunks": 2}
    # Upsert: replace alice.md with new chunks
    new_items = [
        (
            Chunk(
                file_path="People/alice.md",
                section_header="## v2",
                content="New content.",
            ),
            [0.3] * 384,
        ),
        (
            Chunk(
                file_path="People/alice.md",
                section_header="## Added",
                content="Extra section.",
            ),
            [0.4] * 384,
        ),
    ]
    store.upsert_file("People/alice.md", new_items)
    stats = store.stats()
    assert stats["files"] == 2  # still 2 files
    assert stats["chunks"] == 3  # 1 standup + 2 new alice
    # Verify old content is gone
    results = store.knn_search([0.1] * 384, k=10)
    contents = [r[0].content for r in results]
    assert "Old content." not in contents
    assert "New content." in contents


def test_clear_removes_all_data(store):
    store.bulk_insert(
        [
            (Chunk(file_path="a.md", section_header="", content="Alpha"), [0.1] * 384),
            (Chunk(file_path="b.md", section_header="", content="Beta"), [0.2] * 384),
        ]
    )
    assert store.stats()["chunks"] == 2
    store.clear()
    assert store.stats() == {"files": 0, "chunks": 0}


def test_upsert_file_preserves_rowid_correspondence(store):
    # Insert file A with 3 chunks, file B with 2 chunks
    store.bulk_insert(
        [
            (Chunk(file_path="a.md", section_header="## 1", content="A1"), [0.1] * 384),
            (Chunk(file_path="a.md", section_header="## 2", content="A2"), [0.2] * 384),
            (Chunk(file_path="a.md", section_header="## 3", content="A3"), [0.3] * 384),
            (Chunk(file_path="b.md", section_header="## 1", content="B1"), [0.4] * 384),
            (Chunk(file_path="b.md", section_header="## 2", content="B2"), [0.5] * 384),
        ]
    )
    # Upsert a.md, replacing its 3 chunks with 1
    store.upsert_file(
        "a.md",
        [
            (
                Chunk(file_path="a.md", section_header="## new", content="A-new"),
                [0.6] * 384,
            ),
        ],
    )
    # knn_search must return 3 results: 1 from a.md + 2 from b.md, no phantoms
    results = store.knn_search([0.6] * 384, k=10)
    assert len(results) == 3
    contents = sorted(r[0].content for r in results)
    assert contents == ["A-new", "B1", "B2"]
    assert store.stats() == {"files": 2, "chunks": 3}


def test_insert_rejects_wrong_dim_embedding(store):
    chunk = Chunk(file_path="a.md", section_header="", content="x")
    with pytest.raises(ValueError, match="383"):
        store.insert(chunk, [0.1] * 383)


def test_knn_search_rejects_wrong_dim_query(store):
    chunk = Chunk(file_path="a.md", section_header="", content="x")
    store.insert(chunk, [0.1] * 384)
    with pytest.raises(ValueError, match="385"):
        store.knn_search([0.1] * 385, k=1)


def test_store_custom_dim(tmp_path):
    from km.store import Store

    # Use a non-default dim to prove parameterization works end-to-end
    with Store(tmp_path / "index.db", dim=128) as s:
        chunk = Chunk(file_path="a.md", section_header="", content="x")
        s.insert(chunk, [0.1] * 128)
        results = s.knn_search([0.1] * 128, k=1)
        assert len(results) == 1
        assert results[0][0].content == "x"


def test_knn_search_on_empty_database_returns_empty_list(store):
    results = store.knn_search([0.1] * 384, k=5)
    assert results == []


def test_upsert_file_on_nonexistent_file_inserts(store):
    # Upserting a file that was never inserted should just insert
    store.upsert_file(
        "new.md",
        [
            (
                Chunk(file_path="new.md", section_header="", content="hello"),
                [0.1] * 384,
            ),
        ],
    )
    assert store.stats() == {"files": 1, "chunks": 1}
    results = store.knn_search([0.1] * 384, k=1)
    assert len(results) == 1
    assert results[0][0].content == "hello"


def test_upsert_file_with_empty_items_deletes(store):
    # Insert then upsert with [] removes all chunks for that file
    store.bulk_insert(
        [
            (Chunk(file_path="a.md", section_header="", content="A"), [0.1] * 384),
            (Chunk(file_path="b.md", section_header="", content="B"), [0.2] * 384),
        ]
    )
    store.upsert_file("a.md", [])
    assert store.stats() == {"files": 1, "chunks": 1}
    results = store.knn_search([0.1] * 384, k=5)
    contents = [r[0].content for r in results]
    assert "A" not in contents
    assert "B" in contents


def test_store_reopen_preserves_data(tmp_path):
    from km.store import Store

    db_path = tmp_path / "index.db"
    with Store(db_path) as s:
        chunk = Chunk(file_path="a.md", section_header="## h", content="data")
        s.insert(chunk, [0.5] * 384)
    # Reopen
    with Store(db_path) as s:
        assert s.stats() == {"files": 1, "chunks": 1}
        results = s.knn_search([0.5] * 384, k=1)
        assert len(results) == 1
        assert results[0][0].content == "data"


def test_store_handles_unicode_content_and_paths(store):
    chunk = Chunk(
        file_path="People/Álvaro/notas.md",
        section_header="## 会議",
        content="Café ☕ — discussion about 日本語 docs.",
    )
    store.insert(chunk, [0.1] * 384)
    results = store.knn_search([0.1] * 384, k=1)
    assert len(results) == 1
    got = results[0][0]
    assert got.file_path == "People/Álvaro/notas.md"
    assert got.section_header == "## 会議"
    assert got.content == "Café ☕ — discussion about 日本語 docs."


def test_knn_search_round_trips_all_chunk_fields(store):
    # Each field set to a distinct non-empty value so any swap would be detected.
    original = Chunk(
        file_path="People/Nick/2026-review.md",
        section_header="## Open Questions",
        content="What's the single biggest blocker?",
    )
    store.insert(original, [0.7] * 384)
    results = store.knn_search([0.7] * 384, k=1)
    assert len(results) == 1
    got, distance = results[0]
    assert got.file_path == original.file_path
    assert got.section_header == original.section_header
    assert got.content == original.content
    # directory is auto-derived in __post_init__ — verify it still matches
    assert got.directory == original.directory
    assert got.directory == "People"
    # sanity on distance type
    assert isinstance(distance, float)
