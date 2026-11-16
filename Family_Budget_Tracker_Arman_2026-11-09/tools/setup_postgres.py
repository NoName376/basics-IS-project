"""One-command PostgreSQL setup (option B: our schema as the shared one).

What it does:
  1. reads the connection string from postgres_url.txt (or asks for it);
  2. creates the database if it does not exist;
  3. loads sql/schema_postgres.sql;
  4. imports Alibek's dump (schema.sql + data.sql) into that schema;
  5. prints the balances and the next commands.

Run it after installing PostgreSQL:

    python tools/setup_postgres.py

or with explicit arguments:

    python tools/setup_postgres.py --dsn "postgresql://postgres:pass@localhost:5432/family_budget" ^
        --schema "C:\\path\\schema.sql" --data "C:\\path\\data.sql"
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from core.db import Database  # noqa: E402
from core.services import BudgetService  # noqa: E402
from import_alibek import parse_dump, run, verify  # noqa: E402

URL_FILE = ROOT / "postgres_url.txt"
IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def split(dsn: str):
    return urlsplit(dsn.strip())


def database_name(dsn: str) -> str:
    return split(dsn).path.lstrip("/") or "postgres"


def admin_dsn(dsn: str) -> str:
    parts = split(dsn)
    return urlunsplit((parts.scheme, parts.netloc, "/postgres", "", ""))


def ask(prompt: str) -> str:
    value = input(prompt).strip().strip('"').strip("'")
    return value


def resolve_dsn(args) -> str:
    if args.dsn:
        return args.dsn.strip()
    if URL_FILE.exists():
        text = URL_FILE.read_text(encoding="utf-8").strip()
        if text:
            print(f"Using the connection string from {URL_FILE.name}")
            return text
    print("PostgreSQL connection string is required, for example:")
    print("  postgresql://postgres:YOUR_PASSWORD@localhost:5432/family_budget")
    dsn = ask("Connection string: ")
    if not dsn:
        raise SystemExit("No connection string, nothing to do.")
    return dsn


def resolve_file(args_value: str | None, name: str, hint: str) -> Path:
    if args_value:
        path = Path(args_value.strip('"'))
    else:
        print(f"Path to {name} was not given ({hint}).")
        path = Path(ask(f"Path to {name}: ").strip('"'))
    if not path.exists():
        raise SystemExit(f"File not found: {path}")
    return path


# --------------------------------------------------------------------------- steps
def ensure_database(dsn: str) -> None:
    import psycopg2

    name = database_name(dsn)
    print(f"[1/4] Checking database '{name}' ...")
    conn = psycopg2.connect(admin_dsn(dsn), connect_timeout=8)
    conn.autocommit = True
    try:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,))
        exists = cur.fetchone()
        if exists:
            print(f"      database '{name}' already exists")
        else:
            if not IDENTIFIER.fullmatch(name):
                raise SystemExit(f"Unsafe database name: {name}")
            cur.execute(f'CREATE DATABASE "{name}"')
            print(f"      created database '{name}'")
        cur.close()
    finally:
        conn.close()


def load_schema(dsn: str) -> None:
    import psycopg2

    print("[2/4] Loading sql/schema_postgres.sql ...")
    script = (ROOT / "sql" / "schema_postgres.sql").read_text(encoding="utf-8")
    conn = psycopg2.connect(dsn, connect_timeout=8)
    try:
        cur = conn.cursor()
        cur.execute(script)
        conn.commit()
        cur.close()
    finally:
        conn.close()
    print("      four tables, indexes and the user_balance view are in place")


def import_data(dsn: str, data_path: Path, family: str, password: str) -> None:
    print("[3/4] Importing Alibek's records ...")
    dump = parse_dump(data_path.read_text(encoding="utf-8"))
    print(f"      parsed {len(dump['users'])} users, {len(dump['categories'])} categories, "
          f"{len(dump['transactions'])} transactions")
    db = Database(dsn)
    db.init_schema()
    svc = BudgetService(db, "KZT")
    stats, family_id = run(db, svc, dump, family, password)
    print(f"      imported {stats['users']} users, {stats['categories']} categories, "
          f"{stats['transactions']} transactions, {stats['skipped']} skipped")
    verify(db, family_id)


def write_url(dsn: str) -> None:
    URL_FILE.write_text(dsn.strip() + "\n", encoding="utf-8")
    print(f"[4/4] Saved the connection string to {URL_FILE.name}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Create the PostgreSQL database and import the team data")
    parser.add_argument("--dsn", help="postgresql://user:password@host:5432/family_budget")
    parser.add_argument("--schema", help="path to Alibek's schema.sql (reference only)")
    parser.add_argument("--data", help="path to Alibek's data.sql")
    parser.add_argument("--family", default="Akhmetshiev Family", help="family name for the imported users")
    parser.add_argument("--password", default="Demo1234", help="password for the imported users")
    args = parser.parse_args()

    dsn = resolve_dsn(args)
    data_path = resolve_file(args.data, "data.sql", "the file Alibek sent")
    if args.schema:
        resolve_file(args.schema, "schema.sql", "reference only")

    try:
        ensure_database(dsn)
        load_schema(dsn)
        import_data(dsn, data_path, args.family, args.password)
        write_url(dsn)
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001
        print()
        print(f"[ERROR] {exc}")
        print()
        print("Most common reasons:")
        print("  * PostgreSQL is not installed or the service is not running;")
        print("  * wrong password or port in the connection string;")
        print("  * the password contains % or @ and must be percent-encoded (%25, %40);")
        print("  * psycopg2 is missing: python -m pip install psycopg2-binary")
        return 1

    print()
    print("Done. Next commands:")
    print("  python tools\\db_check.py     (expects: the database matches the application schema)")
    print("  python selfcheck.py          (expects: 10/10 checks passed)")
    print("  START.bat                    (sidebar must show: Backend: PostgreSQL)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
