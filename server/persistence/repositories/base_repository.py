from __future__ import annotations

from typing import Any, Dict, Iterable, List, Sequence

from ..db import Database, decode_row


class BaseRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def _one(self, query: str, params: Sequence[Any] = ()) -> Dict[str, Any] | None:
        with self.database.connection() as connection:
            return decode_row(connection.execute(query, params).fetchone())

    def _many(self, query: str, params: Sequence[Any] = ()) -> List[Dict[str, Any]]:
        with self.database.connection() as connection:
            return [decode_row(row) or {} for row in connection.execute(query, params).fetchall()]

    def _write(self, query: str, params: Sequence[Any]) -> None:
        with self.database.transaction() as connection:
            connection.execute(query, params)

    def _write_many(self, query: str, params: Iterable[Sequence[Any]]) -> None:
        with self.database.transaction() as connection:
            connection.executemany(query, params)
