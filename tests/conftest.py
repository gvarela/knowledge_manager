from collections.abc import Iterator
from pathlib import Path

import pytest

from km.store import Store


@pytest.fixture
def store(tmp_path: Path) -> Iterator[Store]:
    db_path = tmp_path / "index.db"
    with Store(db_path) as s:
        yield s
