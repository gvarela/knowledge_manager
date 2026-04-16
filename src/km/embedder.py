"""Thin adapter over fastembed.TextEmbedding -- plain strings in, float lists out."""

from __future__ import annotations

from pathlib import Path


class Embedder:
    """Wraps fastembed.TextEmbedding. No km imports."""

    def __init__(
        self,
        model_name: str = "BAAI/bge-small-en-v1.5",
        cache_dir: Path | None = None,
        dim: int = 384,
        *,
        lazy_load: bool = False,
    ) -> None:
        from fastembed import TextEmbedding

        self._dim = dim
        self._model = TextEmbedding(
            model_name=model_name,
            cache_dir=str(cache_dir) if cache_dir else None,
            lazy_load=lazy_load,
        )

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed a list of texts, returning one float-vector per text."""
        vectors = [arr.tolist() for arr in self._model.embed(texts)]
        for v in vectors:
            if len(v) != self._dim:
                raise ValueError(
                    f"embedder produced {len(v)} dims, expected {self._dim}"
                )
        return vectors
