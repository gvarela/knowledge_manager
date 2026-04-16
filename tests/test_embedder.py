import numpy as np
import pytest

from km.embedder import Embedder


@pytest.mark.slow
def test_embed_returns_correct_dim_vectors():
    embedder = Embedder()
    result = embedder.embed(["hello world"])
    assert isinstance(result, list)
    assert len(result) == 1
    assert len(result[0]) == 384
    assert all(isinstance(x, float) for x in result[0])


@pytest.mark.slow
def test_embed_handles_multiple_texts():
    embedder = Embedder()
    result = embedder.embed(["a", "b", "c"])
    assert len(result) == 3
    for vec in result:
        assert len(vec) == 384


def test_embed_rejects_dim_mismatch():
    class FakeModel:
        def embed(self, texts, **kwargs):
            for _ in texts:
                yield np.array([0.1] * 10)

    embedder = Embedder(lazy_load=True)
    embedder._model = FakeModel()
    with pytest.raises(ValueError, match="10 dims, expected 384"):
        embedder.embed(["test"])
