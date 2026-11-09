"""Check whether a database can be used by the application.

Run it as soon as Alibek sends the connection string or a dump:

    python tools/db_check.py --sqlite data/family_budget.db
    set DATABASE_URL=postgresql://user:pass@host:5432/family_budget
    python tools/db_check.py

It prints which tables and columns are missing, so the gap can be fixed before
the lesson instead of during it.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

EXPECTED: dict[str, list[str]] = {
    "families": ["id", "name", "invite_code", "currency", "created_at"],
    "users": ["id", "family_id", "full_name", "email", "password_hash", "role", "is_active", "created_at"],
    "categories": ["id", "family_id", "name", "kind", "monthly_limit_cents", "is_active"],
    "transactions": [
        "id",
        "family_id",
        "user_id",
        "category_id",
        "kind",
        "amount_cents",
        "occurred_on",
        "note",
        "created_at",
    ],
}

# Columns the application can live without (it never selects them explicitly).
OPTIONAL = {"created_at"}


def columns_sqlite(path: Path) -> dict[str, list[str]]:
    conn = sqlite3.connect(path)
    try:
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        return {t: [row[1] for row in conn.execute(f"PRAGMA table_info({t})")] for t in tables}
    finally:
        conn.close()


def columns_postgres(url: str) -> dict[str, list[str]]:
    try:
        import psycopg2
    except ImportError:
        print("[ERROR] psycopg2 is not installed. Run: pip install psycopg2-binary")
        raise SystemExit(2)
    conn = psycopg2.connect(url, connect_timeout=8)
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT table_name, column_name FROM information_schema.columns "
            "WHERE table_schema = 'public' ORDER BY table_name, ordinal_position"
        )
        result: dict[str, list[str]] = {}
        for table, column in cur.fetchall():
            result.setdefault(table, []).append(column)
        cur.close()
        return result
    finally:
        conn.close()


def counts_sqlite(path: Path) -> dict[str, int]:
    conn = sqlite3.connect(path)
    try:
        return {
            table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in EXPECTED
            if conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()[0]
        }
    finally:
        conn.close()


def counts_postgres(url: str) -> dict[str, int]:
    import psycopg2

    conn = psycopg2.connect(url, connect_timeout=8)
    try:
        cur = conn.cursor()
        result = {}
        for table in EXPECTED:
            cur.execute(f"SELECT COUNT(*) FROM {table}")
            result[table] = cur.fetchone()[0]
        cur.close()
        return result
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Check a database against the application schema")
    parser.add_argument("--sqlite", help="path to a SQLite file (default: data/family_budget.db)")
    args = parser.parse_args()

    url = (os.getenv("DATABASE_URL") or "").strip()
    if url and not args.sqlite:
        label = "PostgreSQL"
        try:
            found = columns_postgres(url)
            counts = counts_postgres(url)
        except Exception as exc:  # noqa: BLE001
            print(f"[FAIL] Cannot read the database: {exc}")
            return 2
    else:
        path = Path(args.sqlite or ROOT / "data" / "family_budget.db")
        if not path.exists():
            print(f"[FAIL] File not found: {path}")
            return 2
        label = f"SQLite ({path})"
        found = columns_sqlite(path)
        counts = counts_sqlite(path)

    print(f"Database: {label}")
    print("=" * 96)
    print(f"{'Table':<16} {'Status':<10} {'Rows':>6}  Details")
    print("-" * 96)

    failures = 0
    for table, expected in EXPECTED.items():
        actual = found.get(table)
        if actual is None:
            failures += 1
            print(f"{table:<16} {'MISSING':<10} {'-':>6}  table is not in the database")
            continue
        missing = [c for c in expected if c not in actual and c not in OPTIONAL]
        extra = [c for c in actual if c not in expected]
        status = "OK" if not missing else "INCOMPLETE"
        failures += bool(missing)
        details = ""
        if missing:
            details += "missing: " + ", ".join(missing)
        if extra:
            details += ("; " if details else "") + "extra: " + ", ".join(extra)
        if not details:
            details = "all expected columns present"
        print(f"{table:<16} {status:<10} {counts.get(table, 0):>6}  {details}")

    if "user_balance" in found:
        print()
        print("Found a view/table 'user_balance': " + ", ".join(found["user_balance"]))
        print("Tell me its columns: the analytics screen can use it instead of recomputing the balance.")

    print("-" * 96)
    if failures:
        print(f"RESULT: {failures} table(s) need attention before the application can run on this database.")
        print("Send this output to the team and compare it with docs/DB_CONTRACT.md.")
        return 1
    print("RESULT: the database matches the application schema. Set DATABASE_URL and run START.bat.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
