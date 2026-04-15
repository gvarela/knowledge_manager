import tomllib
from dataclasses import asdict
from pathlib import Path, PurePosixPath

from km import ChunkConfig, ScanConfig, VaultConfig

_KNOWN_TOP_LEVEL = {"defaults", "scan", "overrides"}
_CHUNK_FIELDS = set(ChunkConfig.__dataclass_fields__)
_SCAN_FIELDS = set(ScanConfig.__dataclass_fields__)
_OVERRIDE_FIELDS = _CHUNK_FIELDS | {"files", "index"}


def _validate_keys(mapping: dict, allowed: set[str], section: str) -> None:
    for key in mapping:
        if key not in allowed:
            valid = ", ".join(sorted(allowed))
            raise ValueError(
                f"Unknown key '{key}' in [{section}] (valid keys: {valid})"
            )


def load_config(vault_path: Path) -> VaultConfig:
    """Load config from .km/config.toml, falling back to defaults."""
    config_path = vault_path / ".km" / "config.toml"
    if not config_path.exists():
        return VaultConfig()

    with open(config_path, "rb") as f:
        raw = tomllib.load(f)

    _validate_keys(raw, _KNOWN_TOP_LEVEL, "config.toml")

    defaults = raw.get("defaults", {})
    _validate_keys(defaults, _CHUNK_FIELDS, "defaults")

    scan_raw = raw.get("scan", {})
    _validate_keys(scan_raw, _SCAN_FIELDS, "scan")

    overrides_raw = raw.get("overrides", [])
    for override in overrides_raw:
        _validate_keys(override, _OVERRIDE_FIELDS, "overrides")

    chunk_kwargs = {}
    for key in ("split_on", "strip_frontmatter", "min_chunk_chars", "strategy"):
        if key in defaults:
            val = defaults[key]
            if isinstance(val, list):
                val = tuple(val)
            chunk_kwargs[key] = val

    scan_kwargs = {}
    for key in ("include", "exclude_dotdirs"):
        if key in scan_raw:
            val = scan_raw[key]
            if isinstance(val, list):
                val = tuple(val)
            scan_kwargs[key] = val

    return VaultConfig(
        chunk=ChunkConfig(**chunk_kwargs),
        scan=ScanConfig(**scan_kwargs),
        overrides=tuple(overrides_raw),
    )


def resolve_for_file(config: VaultConfig, file_path: str) -> ChunkConfig:
    """Resolve ChunkConfig for a specific file, applying matching overrides."""
    resolved = asdict(config.chunk)

    for override in config.overrides:
        files_pattern = override.get("files", "")
        patterns = [files_pattern] if isinstance(files_pattern, str) else files_pattern

        path = PurePosixPath(file_path)
        for pattern in patterns:
            if path.match(pattern):
                for key, val in override.items():
                    if key in ("files", "index"):
                        continue
                    if isinstance(val, list):
                        val = tuple(val)
                    resolved[key] = val
                break

    fields = ChunkConfig.__dataclass_fields__
    return ChunkConfig(**{k: v for k, v in resolved.items() if k in fields})
