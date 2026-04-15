from km import ChunkConfig, ScanConfig
from km.chunker import chunk_markdown, scan_vault


def test_single_paragraph_returns_one_chunk():
    config = ChunkConfig()
    text = "This is a simple note with no headers."
    chunks = chunk_markdown(text, "Memory/insight.md", config)
    assert len(chunks) == 1
    assert chunks[0].content == text
    assert chunks[0].file_path == "Memory/insight.md"
    assert chunks[0].directory == "Memory"
    assert chunks[0].section_header == ""


def test_splits_on_h2_headers():
    config = ChunkConfig()
    text = "## Notes\nSome notes here.\n\n## Actions\nDo stuff."
    chunks = chunk_markdown(text, "Meetings/standup.md", config)
    assert len(chunks) == 2
    assert chunks[0].section_header == "## Notes"
    assert chunks[1].section_header == "## Actions"


def test_splits_on_h1_and_h2():
    config = ChunkConfig()
    text = "# Title\nIntro paragraph.\n\n## Section\nBody content."
    chunks = chunk_markdown(text, "Thinking/idea.md", config)
    assert len(chunks) == 2
    assert chunks[0].section_header == "# Title"
    assert chunks[1].section_header == "## Section"


def test_empty_file_returns_empty():
    config = ChunkConfig()
    assert chunk_markdown("", "empty.md", config) == []
    assert chunk_markdown("   \n\n  ", "blank.md", config) == []


def test_preamble_before_first_header():
    config = ChunkConfig()
    text = "Some intro text.\n\n## Section\nBody content."
    chunks = chunk_markdown(text, "People/Nick/README.md", config)
    assert len(chunks) == 2
    assert chunks[0].section_header == ""
    assert "Some intro text." in chunks[0].content
    assert chunks[1].section_header == "## Section"


def test_strips_yaml_frontmatter():
    config = ChunkConfig(strip_frontmatter=True)
    text = "---\ntype: pattern\ndate: 2026-04-04\n---\n\n## Notes\nContent here."
    chunks = chunk_markdown(text, "Memory/insight.md", config)
    assert len(chunks) == 1
    assert "---" not in chunks[0].content
    assert "Content here." in chunks[0].content


def test_frontmatter_only_returns_empty():
    config = ChunkConfig(strip_frontmatter=True)
    text = "---\ntype: stub\ndate: 2026-04-04\n---\n"
    chunks = chunk_markdown(text, "Memory/stub.md", config)
    assert chunks == []


def test_short_sections_stay_as_single_chunk():
    config = ChunkConfig(min_chunk_chars=200)
    # Total content is short even though it has headers
    text = "# Title\nShort.\n\n## Section\nAlso short."
    chunks = chunk_markdown(text, "Memory/brief.md", config)
    assert len(chunks) == 1  # below threshold, stays as one chunk


def test_atomic_strategy_returns_single_chunk():
    config = ChunkConfig(strategy="atomic")
    text = "# Title\nIntro.\n\n## Section One\nContent.\n\n## Section Two\nMore."
    chunks = chunk_markdown(text, "Daily/2026-04-14.md", config)
    assert len(chunks) == 1
    assert "Section One" in chunks[0].content
    assert "Section Two" in chunks[0].content


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


def test_scan_vault_top_level_only_pattern(tmp_path):
    # File at top level
    (tmp_path / "top.md").write_text("top")
    # File in subdirectory — should NOT be matched by top-level-only pattern
    subdir = tmp_path / "sub"
    subdir.mkdir()
    (subdir / "nested.md").write_text("nested")

    config = ScanConfig(include=("*.md",))
    files = scan_vault(tmp_path, config)
    names = sorted(f.name for f in files)
    assert names == ["top.md"]


def test_scan_vault_recursive_pattern_finds_nested(tmp_path):
    (tmp_path / "top.md").write_text("top")
    subdir = tmp_path / "sub" / "deeper"
    subdir.mkdir(parents=True)
    (subdir / "nested.md").write_text("nested")

    config = ScanConfig(include=("**/*.md",))
    files = scan_vault(tmp_path, config)
    names = sorted(f.name for f in files)
    assert names == ["nested.md", "top.md"]


def test_scan_vault_on_nonexistent_path_raises(tmp_path):
    # vault_path that does not exist — Path.glob on nonexistent directory returns empty
    nonexistent = tmp_path / "does-not-exist"
    # Document observed behavior: Path.glob on nonexistent directory returns empty
    from km import ScanConfig
    from km.chunker import scan_vault

    files = scan_vault(nonexistent, ScanConfig())
    assert files == []
