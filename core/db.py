"""Small database access layer with two interchangeable backends.

* PostgreSQL - the production database of the project (`DATABASE_URL`).
* SQLite     - identical schema, used for the offline demo and for unit tests.

All SQL in the project is written once with ``?`` placeholders; the layer
rewrites them to ``%s`` for psycopg2. Money is always stored as integer cents,
never as a float, so no rounding error can enter a balance.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Sequence

try:  # psycopg2 is only required when DATABASE_URL points at PostgreSQL
    import psycopg2
    import psycopg2.extras
except ImportError:  # pragma: no cover - exercised only on machines without it
    psycopg2 = None  # type: ignore[assignment]


class DatabaseError(RuntimeError):
    """Raised when the database cannot be reached or a statement fails."""


class Database:
    def __init__(self, database_url: str | None = None, sqlite_path: str | Path | None = None) -> None:
        self.database_url = (database_url or "").strip() or None
        self.dialect = "postgres" if self.database_url else "sqlite"
        self.sqlite_path = Path(sqlite_path or "data/family_budget.db")

        if self.dialect == "postgres" and psycopg2 is None:
            raise DatabaseError(
                "DATABASE_URL is set but psycopg2 is not installed. "
                "Run: pip install -r requirements.txt"
            )

    # ------------------------------------------------------------------ infra
    @property
    def label(self) -> str:
        return "PostgreSQL" if self.dialect == "postgres" else "SQLite"

    def _connect(self) -> Any:
        try:
            if self.dialect == "postgres":
                conn = psycopg2.connect(self.database_url, connect_timeout=5)
                conn.cursor_factory = psycopg2.extras.RealDictCursor
                return conn
            self.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(self.sqlite_path, timeout=15)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("PRAGMA journal_mode = WAL")
            return conn
        except Exception as exc:  # pragma: no cover - depends on the host
            raise DatabaseError(f"Cannot connect to {self.label}: {exc}") from exc

    def _sql(self, sql: str) -> str:
        return sql.replace("?", "%s") if self.dialect == "postgres" else sql

    @contextmanager
    def connection(self) -> Iterator[Any]:
        conn = self._connect()
        try:
            yield conn
        finally:
            conn.close()

    # --------------------------------------------------------------- queries
    def query(self, sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
        with self.connection() as conn:
            cur = conn.cursor()
            try:
                cur.execute(self._sql(sql), tuple(params))
                rows = cur.fetchall()
            finally:
                cur.close()
        return [dict(row) for row in rows]

    def query_one(self, sql: str, params: Sequence[Any] = ()) -> dict[str, Any] | None:
        rows = self.query(sql, params)
        return rows[0] if rows else None

    def scalar(self, sql: str, params: Sequence[Any] = (), default: Any = None) -> Any:
        row = self.query_one(sql, params)
        if not row:
            return default
        return next(iter(row.values()), default)

    def execute(self, sql: str, params: Sequence[Any] = ()) -> int:
        """Run a statement and return the affected row count."""
        with self.connection() as conn:
            cur = conn.cursor()
            try:
                cur.execute(self._sql(sql), tuple(params))
                conn.commit()
                return cur.rowcount
            except Exception:
                conn.rollback()
                raise
            finally:
                cur.close()

    def insert(self, sql: str, params: Sequence[Any] = ()) -> int:
        """Run an INSERT and return the new primary key on both backends."""
        with self.connection() as conn:
            cur = conn.cursor()
            try:
                statement = self._sql(sql).rstrip().rstrip(";")
                if self.dialect == "postgres":
                    statement += " RETURNING id"
                cur.execute(statement, tuple(params))
                if self.dialect == "postgres":
                    row = cur.fetchone()
                    new_id = row["id"] if isinstance(row, dict) else row[0]
                else:
                    new_id = cur.lastrowid
                conn.commit()
                return int(new_id)
            except Exception:
                conn.rollback()
                raise
            finally:
                cur.close()

    # ----------------------------------------------------------------- schema
    def init_schema(self) -> None:
        script = (Path(__file__).resolve().parent.parent / "sql" / f"schema_{self.dialect}.sql").read_text(
            encoding="utf-8"
        )
        with self.connection() as conn:
            cur = conn.cursor()
            try:
                if self.dialect == "sqlite":
                    cur.executescript(script)
                else:
                    cur.execute(script)
                conn.commit()
            finally:
                cur.close()

    def ping(self) -> bool:
        try:
            return self.scalar("SELECT 1") == 1
        except Exception:
            return False
