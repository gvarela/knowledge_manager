from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Literal

__version__ = "0.1.0"


@dataclass(frozen=True, slots=True)
class ChunkConfig:
    split_on: tuple[str, ...] = ("h1", "h2")
    strip_frontmatter: bool = True
    min_chunk_chars: int = 0
    strategy: Literal["default", "atomic"] = "default"


@dataclass(frozen=True, slots=True)
class ScanConfig:
    include: tuple[str, ...] = ("**/*.md",)
    exclude_dotdirs: bool = True


@dataclass(frozen=True, slots=True)
class VaultConfig:
    chunk: ChunkConfig = field(default_factory=ChunkConfig)
    scan: ScanConfig = field(default_factory=ScanConfig)
    overrides: tuple[dict, ...] = ()


@dataclass(frozen=True, slots=True)
class Chunk:
    file_path: str
    section_header: str
    content: str
    directory: str = field(init=False)

    def __post_init__(self) -> None:
        parts = PurePosixPath(self.file_path).parts
        object.__setattr__(self, "directory", parts[0] if len(parts) > 1 else "")


__all__ = ["Chunk", "ChunkConfig", "ScanConfig", "VaultConfig", "__version__"]
