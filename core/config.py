"""Application settings.

Everything is environment-driven so the same code runs on a developer laptop
(SQLite fallback) and against the team PostgreSQL server (DATABASE_URL).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SQLITE_PATH = PROJECT_ROOT / "data" / "family_budget.db"
SQL_DIR = PROJECT_ROOT / "sql"


@dataclass(frozen=True)
class Settings:
    app_name: str = "Family Budget Tracker"
    team: str = "Team 38"
    currency: str = "KZT"
    database_url: str | None = None
    sqlite_path: Path = DEFAULT_SQLITE_PATH
    max_login_attempts: int = 5
    lockout_seconds: int = 60

    @property
    def backend(self) -> str:
        return "PostgreSQL" if self.database_url else "SQLite (demo mode)"


def load_settings() -> Settings:
    return Settings(
        currency=os.getenv("FBT_CURRENCY", "KZT").strip().upper() or "KZT",
        database_url=(os.getenv("DATABASE_URL") or "").strip() or None,
        sqlite_path=Path(os.getenv("FBT_SQLITE_PATH", str(DEFAULT_SQLITE_PATH))),
        app_name=os.getenv("FBT_APP_NAME", "Family Budget Tracker"),
    )
