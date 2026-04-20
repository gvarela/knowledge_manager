import argparse
import json
import sys
import tomllib
from dataclasses import asdict
from pathlib import Path

import tomli_w

from km.config import load_config, resolve_for_file
from km.search import Searcher
from km.store import Store


def discover_km_root(start: Path | None = None) -> Path:
    """Walk parent directories to find .km/, returning the vault root."""
    current = (start or Path.cwd()).resolve()
    while True:
        if (current / ".km").is_dir():
            return current
        parent = current.parent
        if parent == current:
            raise SystemExit(
                "km: no .km/ directory found (run 'km index <path>' first)"
            )
        current = parent


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="km", description="Semantic search for Obsidian vaults"
    )
    sub = parser.add_subparsers(dest="command")

    json_parent = argparse.ArgumentParser(add_help=False)
    json_parent.add_argument(
        "--json", action="store_true", help="Output in JSON format"
    )

    p_index = sub.add_parser("index", help="Build search index", parents=[json_parent])
    p_index.add_argument(
        "vault_path", nargs="?", help="Path to vault (default: auto-discover)"
    )

    p_search = sub.add_parser("search", help="Semantic search", parents=[json_parent])
    p_search.add_argument("query", help="Search query")
    p_search.add_argument("--top-k", type=int, default=10, help="Number of results")
    p_search.add_argument("--dir", help="Filter results to this directory")

    p_update = sub.add_parser(
        "update", help="Re-index specific files", parents=[json_parent]
    )
    p_update.add_argument("paths", nargs="+", help="Vault-relative file paths")

    sub.add_parser("stats", help="Show index statistics", parents=[json_parent])
    sub.add_parser(
        "sync",
        help="Sync index with vault (add new, remove deleted)",
        parents=[json_parent],
    )
    sub.add_parser("prime", help="Output context for Claude Code hooks")

    p_config = sub.add_parser("config", help="Manage configuration")
    config_sub = p_config.add_subparsers(dest="config_command")
    config_sub.add_parser("show", help="Show resolved config", parents=[json_parent])
    p_get = config_sub.add_parser(
        "get", help="Show config for a file", parents=[json_parent]
    )
    p_get.add_argument("file_path", help="Vault-relative file path")
    p_set = config_sub.add_parser(
        "set", help="Set config override", parents=[json_parent]
    )
    p_set.add_argument("pattern", help='Glob pattern (e.g., "Memory/**") or "defaults"')
    p_set.add_argument("settings", nargs="+", help="key=value pairs")

    return parser


def _cmd_index(args: argparse.Namespace) -> None:
    vault_root = Path(args.vault_path) if args.vault_path else discover_km_root()

    with Searcher(vault_root) as s:
        stats = s.index_vault()

    if args.json:
        print(json.dumps(stats))
    else:
        print(f"Indexed {stats['files']} files ({stats['chunks']} chunks)")


def _cmd_search(args: argparse.Namespace) -> None:
    vault_root = discover_km_root()
    fetch_k = args.top_k * 5 if args.dir else args.top_k

    with Searcher(vault_root) as s:
        results = s.search(args.query, k=fetch_k)

    if args.dir:
        dir_prefix = args.dir.rstrip("/")
        results = [r for r in results if r.chunk.directory == dir_prefix]
    results = results[: args.top_k]

    if args.json:
        print(
            json.dumps(
                {
                    "results": [
                        {
                            "file_path": r.chunk.file_path,
                            "section_header": r.chunk.section_header,
                            "content": r.chunk.content,
                            "directory": r.chunk.directory,
                            "distance": r.distance,
                        }
                        for r in results
                    ]
                }
            )
        )
    else:
        for r in results:
            header_part = (
                f" :: {r.chunk.section_header}" if r.chunk.section_header else ""
            )
            print(f"[{r.distance:.2f}] {r.chunk.file_path}{header_part}")
            first_line = r.chunk.content.split("\n", 1)[0]
            if len(first_line) > 80:
                first_line = first_line[:80] + "..."
            print(f"  > {first_line}")
            print()


def _cmd_update(args: argparse.Namespace) -> None:
    vault_root = discover_km_root()

    with Searcher(vault_root) as s:
        stats = s.update_files(args.paths)

    if args.json:
        print(json.dumps(stats))
    else:
        print(f"Updated {stats['files']} files ({stats['chunks']} chunks)")


def _cmd_sync(args: argparse.Namespace) -> None:
    vault_root = discover_km_root()

    with Searcher(vault_root) as s:
        result = s.sync()

    if args.json:
        print(json.dumps(result))
    else:
        print(
            f"Synced: {result['added']} added, {result['removed']} removed"
            f" ({result['chunks']} chunks)"
        )


def _cmd_stats(args: argparse.Namespace) -> None:
    vault_root = discover_km_root()
    db_path = vault_root / ".km" / "index.db"

    with Store(db_path) as store:
        stats = store.stats()

    if args.json:
        print(json.dumps(stats))
    else:
        print(f"{stats['files']} files, {stats['chunks']} chunks")


def _cmd_config_show(args: argparse.Namespace) -> None:
    vault_root = discover_km_root()
    config = load_config(vault_root)

    if args.json:
        print(json.dumps(asdict(config)))
    else:
        chunk = config.chunk
        scan = config.scan
        print("[defaults]")
        print(f"split_on = {list(chunk.split_on)}")
        print(f"strip_frontmatter = {str(chunk.strip_frontmatter).lower()}")
        print(f"min_chunk_chars = {chunk.min_chunk_chars}")
        print(f"strategy = {chunk.strategy}")
        print()
        print("[scan]")
        print(f"include = {list(scan.include)}")
        print(f"exclude_dotdirs = {str(scan.exclude_dotdirs).lower()}")
        if config.overrides:
            for override in config.overrides:
                print()
                print("[[overrides]]")
                for key, val in override.items():
                    print(f"{key} = {val}")


def _cmd_config_get(args: argparse.Namespace) -> None:
    vault_root = discover_km_root()
    config = load_config(vault_root)
    resolved = resolve_for_file(config, args.file_path)

    if args.json:
        print(json.dumps(asdict(resolved)))
    else:
        print(f"split_on = {list(resolved.split_on)}")
        print(f"strip_frontmatter = {str(resolved.strip_frontmatter).lower()}")
        print(f"min_chunk_chars = {resolved.min_chunk_chars}")
        print(f"strategy = {resolved.strategy}")


def _parse_value(s: str):
    """Coerce a string value to the appropriate Python type."""
    if s.lower() == "true":
        return True
    if s.lower() == "false":
        return False
    try:
        return int(s)
    except ValueError:
        pass
    if s.startswith("["):
        return json.loads(s)
    return s


_PRIME_TEXT = """\
# km — Semantic Search Context

> Auto-injected by `km prime` on session start / context recovery.

## Available Commands

```bash
km search "<query>" [--top-k N]   # semantic search (auto-discovers .km/)
km search "<query>" --json        # machine-parseable output for skills
km search "<query>" --dir People  # filter results to a directory
km index [<vault-path>]           # full re-index (or create new index)
km update <file1.md> [file2.md…]  # incremental re-index after file writes
km sync [--json]                  # add new files, remove deleted (handles moves)
km stats [--json]                 # file/chunk counts
km config show [--json]           # dump current config
km config get "<file>" [--json]   # resolved config for a specific file
km config set "<pattern>" k=v…    # add/update override (e.g., strategy=atomic)
```

## When to Use

- **Semantic search**: `km search "<topic>" --top-k 10 --json` finds content by meaning,
  not just keywords. Use when grep/glob miss semantic matches.
- **After writing files**: `km update <paths…>` keeps the index fresh. Call after
  skills write or modify vault files.
- **Config management**: `km config set/get/show` lets you adjust chunking rules
  without editing TOML directly.

## Key Notes

- `--json` goes after the subcommand: `km search "…" --json`
- Auto-discovers `.km/` by walking parent directories (like `.git/`)
- All paths are vault-relative (e.g., `People/Nick/README.md`)
"""


def _cmd_prime(args: argparse.Namespace) -> None:
    import time

    vault_root = discover_km_root()
    db_path = vault_root / ".km" / "index.db"
    output = _PRIME_TEXT
    if not db_path.exists():
        output += "\n**Warning:** No index found. Run `km index` to build it.\n"
    else:
        with Store(db_path) as store:
            stats = store.stats()
        age_days = int((time.time() - db_path.stat().st_mtime) / 86400)
        age_str = "today" if age_days == 0 else f"{age_days}d ago"
        output += (
            f"\n**Index:** {stats['files']} files, {stats['chunks']} chunks"
            f" (updated {age_str})\n"
        )
    print(output)


def _cmd_config_set(args: argparse.Namespace) -> None:
    vault_root = discover_km_root()
    config_path = vault_root / ".km" / "config.toml"

    # Read existing or start fresh
    if config_path.exists():
        with open(config_path, "rb") as f:
            data = tomllib.load(f)
        backup = config_path.read_bytes()
    else:
        data = {}
        backup = None

    # Parse key=value pairs
    settings = {}
    for item in args.settings:
        key, _, val = item.partition("=")
        settings[key] = _parse_value(val)

    if args.pattern == "defaults":
        data.setdefault("defaults", {}).update(settings)
    else:
        overrides = data.setdefault("overrides", [])
        existing = None
        for o in overrides:
            if o.get("files") == args.pattern:
                existing = o
                break
        if existing:
            existing.update(settings)
        else:
            overrides.append({"files": args.pattern, **settings})

    # Write back
    with open(config_path, "wb") as f:
        tomli_w.dump(data, f)

    # Validate — restore original on failure
    try:
        load_config(vault_root)
    except Exception as e:
        if backup is not None:
            config_path.write_bytes(backup)
        else:
            config_path.unlink()
        raise SystemExit(f"km: invalid config after set: {e}") from e

    if args.json:
        result = {
            "status": "ok",
            "pattern": args.pattern,
            "settings": settings,
        }
        print(json.dumps(result))
    else:
        pairs = ", ".join(f"{k}={v}" for k, v in settings.items())
        print(f"Set {args.pattern}: {pairs}")


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(0)

    if args.command == "index":
        _cmd_index(args)
    elif args.command == "search":
        _cmd_search(args)
    elif args.command == "update":
        _cmd_update(args)
    elif args.command == "sync":
        _cmd_sync(args)
    elif args.command == "stats":
        _cmd_stats(args)
    elif args.command == "prime":
        _cmd_prime(args)
    elif args.command == "config":
        if args.config_command == "show":
            _cmd_config_show(args)
        elif args.config_command == "get":
            _cmd_config_get(args)
        elif args.config_command == "set":
            _cmd_config_set(args)
        else:
            parser.parse_args(["config", "--help"])
