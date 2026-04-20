import sys

import pytest

from km.cli import discover_km_root, main


def test_discover_km_root_finds_km_dir(tmp_path):
    (tmp_path / ".km").mkdir()
    assert discover_km_root(tmp_path) == tmp_path


def test_discover_km_root_walks_parents(tmp_path):
    (tmp_path / ".km").mkdir()
    nested = tmp_path / "sub" / "deep"
    nested.mkdir(parents=True)
    assert discover_km_root(nested) == tmp_path


def test_discover_km_root_raises_when_not_found(tmp_path):
    with pytest.raises(SystemExit, match=r"no \.km/ directory found"):
        discover_km_root(tmp_path)


class ConstantEmbedder:
    """Returns a fixed vector for any text. Avoids model downloads."""

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.1] * 384 for _ in texts]


def _make_patched_searcher(monkeypatch):
    """Patch km.cli.Searcher so it uses ConstantEmbedder instead of real model."""
    from km.search import Searcher

    original_init = Searcher.__init__

    def _patched_init(self, vault_root, store=None, embedder=None):
        original_init(self, vault_root, store=store, embedder=ConstantEmbedder())

    monkeypatch.setattr("km.search.Searcher.__init__", _patched_init)


def test_cli_index_with_path(tmp_path, monkeypatch, capsys):
    """km index <path> indexes the vault at the given path."""
    (tmp_path / "note.md").write_text("# Hello\nSome content here.")
    _make_patched_searcher(monkeypatch)
    monkeypatch.setattr(sys, "argv", ["km", "index", str(tmp_path)])
    main()
    captured = capsys.readouterr()
    assert "Indexed" in captured.out
    assert "1" in captured.out  # 1 file


def test_cli_index_without_path(tmp_path, monkeypatch, capsys):
    """km index (no path) auto-discovers .km/ and indexes."""
    (tmp_path / ".km").mkdir()
    (tmp_path / "note.md").write_text("# Hello\nSome content here.")
    _make_patched_searcher(monkeypatch)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["km", "index"])
    main()
    captured = capsys.readouterr()
    assert "Indexed" in captured.out
    assert "1" in captured.out  # 1 file


def test_cli_index_json_output(tmp_path, monkeypatch, capsys):
    """km --json index <path> outputs JSON stats."""
    (tmp_path / "note.md").write_text("# Hello\nSome content here.")
    _make_patched_searcher(monkeypatch)
    monkeypatch.setattr(sys, "argv", ["km", "index", str(tmp_path), "--json"])
    main()
    captured = capsys.readouterr()
    import json

    data = json.loads(captured.out)
    assert "files" in data
    assert "chunks" in data


def test_cli_no_subcommand_prints_usage(monkeypatch, capsys):
    """km (no subcommand) prints usage info."""
    monkeypatch.setattr(sys, "argv", ["km"])
    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 0
    captured = capsys.readouterr()
    assert "usage" in captured.out.lower() or "usage" in captured.err.lower()


def _setup_indexed_vault(tmp_path, monkeypatch):
    """Create a vault with .km/ and indexed content."""
    (tmp_path / "alpha.md").write_text("# Alpha\nAlpha content about testing.")
    (tmp_path / "beta.md").write_text("# Beta\nBeta content about searching.")
    _make_patched_searcher(monkeypatch)
    monkeypatch.setattr(sys, "argv", ["km", "index", str(tmp_path)])
    main()
    return tmp_path


def test_cli_search(tmp_path, monkeypatch, capsys):
    """km search returns human-readable results with [distance] and path."""
    _setup_indexed_vault(tmp_path, monkeypatch)
    capsys.readouterr()  # discard index output
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["km", "search", "testing"])
    main()
    captured = capsys.readouterr()
    assert "[" in captured.out
    assert ".md" in captured.out
    assert ">" in captured.out


def test_cli_search_json(tmp_path, monkeypatch, capsys):
    """km --json search <query> outputs JSON with results list."""
    import json

    _setup_indexed_vault(tmp_path, monkeypatch)
    capsys.readouterr()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["km", "search", "testing", "--json"])
    main()
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert "results" in data
    assert len(data["results"]) > 0
    result = data["results"][0]
    assert "file_path" in result
    assert "distance" in result
    assert "content" in result
    assert "section_header" in result
    assert "directory" in result


def test_cli_search_top_k(tmp_path, monkeypatch, capsys):
    """km --json search <query> --top-k 1 returns only 1 result."""
    import json

    _setup_indexed_vault(tmp_path, monkeypatch)
    capsys.readouterr()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        sys, "argv", ["km", "search", "testing", "--top-k", "1", "--json"]
    )
    main()
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert len(data["results"]) == 1


def test_cli_update(tmp_path, monkeypatch, capsys):
    """km update <path> re-indexes a specific file."""
    _setup_indexed_vault(tmp_path, monkeypatch)
    capsys.readouterr()
    # Modify a file and update it
    (tmp_path / "alpha.md").write_text("# Alpha\nUpdated alpha content.")
    monkeypatch.setattr(sys, "argv", ["km", "update", "alpha.md"])
    monkeypatch.chdir(tmp_path)
    main()
    captured = capsys.readouterr()
    assert "Updated" in captured.out
    assert "1" in captured.out


def test_cli_stats(tmp_path, monkeypatch, capsys):
    """km stats shows file and chunk counts."""
    _setup_indexed_vault(tmp_path, monkeypatch)
    capsys.readouterr()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["km", "stats"])
    main()
    captured = capsys.readouterr()
    assert "files" in captured.out
    assert "chunks" in captured.out


def test_cli_stats_json(tmp_path, monkeypatch, capsys):
    """km --json stats outputs JSON with files and chunks keys."""
    import json

    _setup_indexed_vault(tmp_path, monkeypatch)
    capsys.readouterr()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["km", "stats", "--json"])
    main()
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert "files" in data
    assert "chunks" in data
    assert data["files"] == 2
    assert data["chunks"] == 2


def test_cli_json_flag_after_subcommand(tmp_path, monkeypatch, capsys):
    """km search <query> --json works (flag after subcommand)."""
    import json

    _setup_indexed_vault(tmp_path, monkeypatch)
    capsys.readouterr()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["km", "search", "testing", "--json"])
    main()
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert "results" in data


def test_cli_config_show(tmp_path, monkeypatch, capsys):
    """km config show displays default config values."""
    (tmp_path / ".km").mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["km", "config", "show"])
    main()
    captured = capsys.readouterr()
    assert "split_on" in captured.out
    assert "h1" in captured.out


def test_cli_config_show_json(tmp_path, monkeypatch, capsys):
    """km --json config show outputs JSON with chunk and scan keys."""
    import json

    (tmp_path / ".km").mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["km", "config", "show", "--json"])
    main()
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert "chunk" in data
    assert "split_on" in data["chunk"]
    assert "scan" in data


def test_cli_config_get(tmp_path, monkeypatch, capsys):
    """km config get <file> shows resolved config with overrides applied."""
    (tmp_path / ".km").mkdir()
    (tmp_path / ".km" / "config.toml").write_text(
        '[[overrides]]\nfiles = "Memory/**"\nstrategy = "atomic"\n'
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["km", "config", "get", "Memory/insight.md"])
    main()
    captured = capsys.readouterr()
    assert "atomic" in captured.out


def test_cli_config_get_json(tmp_path, monkeypatch, capsys):
    """km --json config get <file> outputs JSON with resolved ChunkConfig."""
    import json

    (tmp_path / ".km").mkdir()
    (tmp_path / ".km" / "config.toml").write_text(
        '[[overrides]]\nfiles = "Memory/**"\nstrategy = "atomic"\n'
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        sys, "argv", ["km", "config", "get", "Memory/insight.md", "--json"]
    )
    main()
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["strategy"] == "atomic"


def test_cli_config_set_new_override(tmp_path, monkeypatch, capsys):
    """km config set creates a new override in config.toml."""
    import tomllib

    (tmp_path / ".km").mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        sys, "argv", ["km", "config", "set", "Memory/**", "strategy=atomic"]
    )
    main()
    captured = capsys.readouterr()
    assert "Set" in captured.out

    with open(tmp_path / ".km" / "config.toml", "rb") as f:
        data = tomllib.load(f)
    assert len(data["overrides"]) == 1
    assert data["overrides"][0]["files"] == "Memory/**"
    assert data["overrides"][0]["strategy"] == "atomic"


def test_cli_config_set_update_existing(tmp_path, monkeypatch, capsys):
    """km config set updates an existing override without duplicating it."""
    import tomllib

    (tmp_path / ".km").mkdir()
    (tmp_path / ".km" / "config.toml").write_text(
        '[[overrides]]\nfiles = "Memory/**"\nstrategy = "atomic"\n'
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        sys, "argv", ["km", "config", "set", "Memory/**", "strategy=default"]
    )
    main()
    captured = capsys.readouterr()
    assert "Set" in captured.out

    with open(tmp_path / ".km" / "config.toml", "rb") as f:
        data = tomllib.load(f)
    assert len(data["overrides"]) == 1
    assert data["overrides"][0]["strategy"] == "default"


def test_cli_config_set_defaults(tmp_path, monkeypatch, capsys):
    """km config set defaults updates the [defaults] section."""
    import tomllib

    (tmp_path / ".km").mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        sys, "argv", ["km", "config", "set", "defaults", "min_chunk_chars=500"]
    )
    main()
    captured = capsys.readouterr()
    assert "Set" in captured.out

    with open(tmp_path / ".km" / "config.toml", "rb") as f:
        data = tomllib.load(f)
    assert data["defaults"]["min_chunk_chars"] == 500


def test_cli_prime(tmp_path, monkeypatch, capsys):
    """km prime outputs markdown context for Claude Code hooks."""
    (tmp_path / ".km").mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["km", "prime"])
    main()
    captured = capsys.readouterr()
    assert "km search" in captured.out
    assert "km index" in captured.out
    assert "km update" in captured.out
    assert "km config" in captured.out


def test_cli_prime_detects_no_index(tmp_path, monkeypatch, capsys):
    """km prime warns when .km/ exists but index.db is missing."""
    (tmp_path / ".km").mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["km", "prime"])
    main()
    captured = capsys.readouterr()
    assert "no index" in captured.out.lower() or "km index" in captured.out


def test_cli_prime_shows_index_stats(tmp_path, monkeypatch, capsys):
    """km prime shows file/chunk counts and index age when index exists."""
    _setup_indexed_vault(tmp_path, monkeypatch)
    capsys.readouterr()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["km", "prime"])
    main()
    captured = capsys.readouterr()
    assert "2 files" in captured.out
    assert "2 chunks" in captured.out


def test_cli_search_dir_filter(tmp_path, monkeypatch, capsys):
    """km search --dir People/ filters results to that directory."""
    import json

    people = tmp_path / "People"
    people.mkdir()
    meetings = tmp_path / "Meetings"
    meetings.mkdir()
    (people / "alice.md").write_text("# Alice\nAlice works on billing.")
    (meetings / "standup.md").write_text("# Standup\nDiscussed billing updates.")
    _make_patched_searcher(monkeypatch)
    monkeypatch.setattr(sys, "argv", ["km", "index", str(tmp_path)])
    main()
    capsys.readouterr()

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        sys, "argv", ["km", "search", "billing", "--dir", "People", "--json"]
    )
    main()
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert len(data["results"]) > 0
    assert all(r["directory"] == "People" for r in data["results"])
