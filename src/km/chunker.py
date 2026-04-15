import re
from pathlib import Path

from km import Chunk, ChunkConfig, ScanConfig

_FRONTMATTER_RE = re.compile(r"^---\n.*?\n---\n?", re.DOTALL)


def scan_vault(vault_path: Path, config: ScanConfig) -> list[Path]:
    """Scan vault for files matching config patterns, excluding dotdirs."""
    results: set[Path] = set()
    for pattern in config.include:
        for path in vault_path.glob(pattern):
            if not path.is_file():
                continue
            if config.exclude_dotdirs:
                rel = path.relative_to(vault_path)
                if any(part.startswith(".") for part in rel.parts):
                    continue
            results.add(path)
    return sorted(results)


_LEVEL_TO_PART = {"h1": r"(?<!#)# (?!#)", "h2": r"(?<!#)## (?!#)"}


def _build_header_pattern(split_on: tuple[str, ...]) -> re.Pattern[str] | None:
    parts = [_LEVEL_TO_PART[level] for level in split_on if level in _LEVEL_TO_PART]
    if not parts:
        return None
    pattern = r"^(" + "|".join(parts) + r")"
    return re.compile(pattern, re.MULTILINE)


def chunk_markdown(text: str, file_path: str, config: ChunkConfig) -> list[Chunk]:
    """Split markdown text into chunks based on config."""
    stripped = text.strip()
    if not stripped:
        return []

    if config.strip_frontmatter:
        stripped = _FRONTMATTER_RE.sub("", stripped)
        stripped = stripped.strip()
        if not stripped:
            return []

    # If total content is below min_chunk_chars, return as single chunk
    if config.min_chunk_chars > 0 and len(stripped) < config.min_chunk_chars:
        return [Chunk(file_path=file_path, section_header="", content=stripped)]

    if config.strategy == "atomic":
        return [Chunk(file_path=file_path, section_header="", content=stripped)]

    header_re = _build_header_pattern(config.split_on)
    if header_re is None:
        return [Chunk(file_path=file_path, section_header="", content=stripped)]

    lines = stripped.splitlines()
    sections: list[tuple[str, list[str]]] = []
    current_header = ""
    current_lines: list[str] = []

    for line in lines:
        if header_re.match(line):
            if current_lines or current_header:
                sections.append((current_header, current_lines))
            current_header = line
            current_lines = []
        else:
            current_lines.append(line)

    sections.append((current_header, current_lines))

    chunks = []
    for header, body_lines in sections:
        all_lines = [header, *body_lines] if header else body_lines
        content = "\n".join(all_lines).strip()
        if content:
            chunks.append(
                Chunk(file_path=file_path, section_header=header, content=content)
            )

    return chunks
