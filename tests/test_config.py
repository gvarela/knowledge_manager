from km.config import load_config, resolve_for_file


def test_default_config_without_file(tmp_path):
    config = load_config(tmp_path)  # no .km/config.toml exists
    assert config.chunk.split_on == ("h1", "h2")
    assert config.chunk.strip_frontmatter is True
    assert config.chunk.min_chunk_chars == 0
    assert config.chunk.strategy == "default"
    assert "**/*.md" in config.scan.include
    assert config.scan.exclude_dotdirs is True


def test_load_config_from_toml(tmp_path):
    km_dir = tmp_path / ".km"
    km_dir.mkdir()
    (km_dir / "config.toml").write_text("[defaults]\nmin_chunk_chars = 500\n")
    config = load_config(tmp_path)
    assert config.chunk.min_chunk_chars == 500
    assert config.chunk.split_on == ("h1", "h2")  # other defaults preserved


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
