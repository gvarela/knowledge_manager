"""Persistence layer for embedded markdown chunks.

Store uses two tables linked by rowid:
  - chunks: authoritative metadata (id INTEGER PRIMARY KEY AUTOINCREMENT)
  - vec_chunks: vector virtual table, rowid equals the corresponding chunks.id

Invariant: every chunks row has a matching vec_chunks row with the same rowid,
and vice versa. All insertion MUST go through `_insert_pair` to preserve this.
All deletion MUST remove both rows atomically in the same transaction.
"""

import sqlite3
from pathlib import Path

import sqlite_vec

from km import Chunk

_CREATE_CHUNKS = """
CREATE TABLE IF NOT EXISTS chunks (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path      TEXT NOT NULL,
    section_header TEXT NOT NULL,
    content        TEXT NOT NULL,
    directory      TEXT NOT NULL
);
"""

_CREATE_VEC_CHUNKS_TMPL = """
CREATE VIRTUAL TABLE IF NOT EXISTS vec_chunks USING vec0(
    embedding float[{dim}]
);
"""

_CREATE_INDEX = """
CREATE INDEX IF NOT EXISTS idx_chunks_file_path ON chunks(file_path);
"""


class Store:
    def __init__(self, db_path: Path, dim: int = 384) -> None:
        self._dim: int = dim
        self._conn = sqlite3.connect(db_path)
        self._conn.enable_load_extension(True)
        sqlite_vec.load(self._conn)
        self._conn.enable_load_extension(False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute(_CREATE_CHUNKS)
        self._conn.execute(_CREATE_VEC_CHUNKS_TMPL.format(dim=self._dim))
        self._conn.execute(_CREATE_INDEX)
        self._conn.commit()

    def _check_dim(self, embedding: list[float]) -> None:
        if len(embedding) != self._dim:
            raise ValueError(
                f"embedding has {len(embedding)} dimensions, expected {self._dim}"
            )

    def _insert_pair(self, chunk: Chunk, embedding: list[float]) -> int:
        self._check_dim(embedding)
        sql = (
            "INSERT INTO chunks (file_path, section_header, content, directory)"
            " VALUES (?, ?, ?, ?)"
        )
        cur = self._conn.execute(
            sql,
            (chunk.file_path, chunk.section_header, chunk.content, chunk.directory),
        )
        rowid = cur.lastrowid
        self._conn.execute(
            "INSERT INTO vec_chunks(rowid, embedding) VALUES (?, ?)",
            (rowid, sqlite_vec.serialize_float32(embedding)),
        )
        return rowid

    def insert(self, chunk: Chunk, embedding: list[float]) -> int:
        with self._conn:
            rowid = self._insert_pair(chunk, embedding)
        return rowid

    def bulk_insert(self, items: list[tuple[Chunk, list[float]]]) -> None:
        with self._conn:
            for chunk, embedding in items:
                self._insert_pair(chunk, embedding)

    def upsert_file(
        self, file_path: str, items: list[tuple[Chunk, list[float]]]
    ) -> None:
        with self._conn:
            cur = self._conn.execute(
                "SELECT id FROM chunks WHERE file_path = ?", (file_path,)
            )
            ids = [row[0] for row in cur.fetchall()]
            self._conn.execute("DELETE FROM chunks WHERE file_path = ?", (file_path,))
            if ids:
                placeholders = ",".join("?" * len(ids))
                self._conn.execute(
                    f"DELETE FROM vec_chunks WHERE rowid IN ({placeholders})", ids
                )
            for chunk, embedding in items:
                self._insert_pair(chunk, embedding)

    def knn_search(
        self, query_embedding: list[float], k: int = 10
    ) -> list[tuple[Chunk, float]]:
        sql = """
        SELECT c.file_path, c.section_header, c.content, v.distance
        FROM vec_chunks v
        JOIN chunks c ON c.id = v.rowid
        WHERE v.embedding MATCH ?
          AND v.k = ?
        ORDER BY v.distance
        """
        self._check_dim(query_embedding)
        query_vec = sqlite_vec.serialize_float32(query_embedding)
        cur = self._conn.execute(sql, (query_vec, k))
        return [
            (Chunk(file_path=row[0], section_header=row[1], content=row[2]), row[3])
            for row in cur.fetchall()
        ]

    def file_paths(self) -> set[str]:
        cur = self._conn.execute("SELECT DISTINCT file_path FROM chunks")
        return {row[0] for row in cur.fetchall()}

    def stats(self) -> dict[str, int]:
        cur = self._conn.execute(
            "SELECT COUNT(DISTINCT file_path), COUNT(*) FROM chunks"
        )
        files, chunks = cur.fetchone()
        return {"files": files, "chunks": chunks}

    def clear(self) -> None:
        with self._conn:
            self._conn.execute("DELETE FROM vec_chunks")
            self._conn.execute("DELETE FROM chunks")

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "Store":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()
