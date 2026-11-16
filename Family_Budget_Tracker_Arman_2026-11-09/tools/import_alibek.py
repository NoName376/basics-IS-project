"""Import Alibek's PostgreSQL dump into the team application schema.

His dump (schema.sql + data.sql) has three flat tables and a user_balance view:
no families, no roles, no password hashes, no monthly limits. The application
needs the four-table schema from sql/schema_postgres.sql. This tool reads his
INSERT statements and recreates the same records in the application schema, so
his sample data survives the merge.

Examples:
    python tools/import_alibek.py --sqlite data/import_test.db --schema schema.sql --data data.sql
    set DATABASE_URL=postgresql://postgres:password@localhost:5432/family_budget
    python tools/import_alibek.py --schema schema.sql --data data.sql

The first user in his dump becomes the family admin, the rest become members.
Everyone gets the password from --password (default Demo1234) because his dump
stores the placeholder 'hashed_password' instead of a real hash.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.db import Database
from core.services import BudgetService, ConflictError
from core.validators import ValidationError

INSERT_RE = re.compile(r"INSERT INTO public\.(\w+) VALUES \((.*)\);")
KIND_MAP = {"Income": "income", "Expense": "expense"}


# --------------------------------------------------------------------------- parsing
def split_values(raw: str) -> list[str]:
    """Split a SQL VALUES list on commas that are outside single quotes."""
    values: list[str] = []
    current: list[str] = []
    in_quote = False
    index = 0
    while index < len(raw):
        char = raw[index]
        if char == "'":
            if in_quote and index + 1 < len(raw) and raw[index + 1] == "'":
                current.append("'")
                index += 2
                continue
            in_quote = not in_quote
            current.append(char)
        elif char == "," and not in_quote:
            values.append("".join(current).strip())
            current = []
        else:
            current.append(char)
        index += 1
    values.append("".join(current).strip())
    return values


def parse_value(token: str):
    if token.upper() == "NULL":
        return None
    if token.startswith("'") and token.endswith("'"):
        return token[1:-1].replace("''", "'")
    try:
        return Decimal(token)
    except Exception:  # noqa: BLE001
        return token


def parse_dump(text: str) -> dict[str, list[dict]]:
    tables: dict[str, list[dict]] = {"users": [], "categories": [], "transactions": []}
    for line in text.splitlines():
        match = INSERT_RE.search(line.strip())
        if not match:
            continue
        table, body = match.group(1), match.group(2)
        if table not in tables:
            continue
        tables[table].append({"raw": [parse_value(v) for v in split_values(body)]})
    return tables


# --------------------------------------------------------------------------- import
def run(db: Database, svc: BudgetService, dump: dict[str, list[dict]], family_name: str, password: str) -> dict:
    stats = {"users": 0, "categories": 0, "transactions": 0, "skipped": 0}

    users = dump["users"]
    categories = dump["categories"]
    transactions = dump["transactions"]
    if not users:
        raise SystemExit("No users found in the dump.")

    # 1. Family + first user as admin.
    first = users[0]["raw"]  # user_id, full_name, email, password
    existing = db.query_one("SELECT * FROM users WHERE email = ?", (str(first[2]).lower(),))
    if existing:
        admin = svc.get_user(existing["id"])
        family_id = admin["family_id"]
        print(f"Family already exists for {first[2]}, reusing it.")
    else:
        admin = svc.register_family(family_name, str(first[1]), str(first[2]), password)
        family_id = admin["family_id"]
        stats["users"] += 1
        print(f"Family created: {family_name} (invite code {svc.get_family(family_id)['invite_code']})")

    user_map: dict[int, int] = {int(first[0]): int(admin["id"])}
    family = svc.get_family(family_id)
    for row in users[1:]:
        user_id, full_name, email, _ = row["raw"]
        found = db.query_one("SELECT * FROM users WHERE email = ?", (str(email).lower(),))
        if found:
            user_map[int(user_id)] = int(found["id"])
            stats["skipped"] += 1
            continue
        created = svc.join_family(family["invite_code"], str(full_name), str(email), password)
        user_map[int(user_id)] = int(created["id"])
        stats["users"] += 1

    # 2. Categories, mapped to our kind values.
    category_map: dict[int, int] = {}
    for row in categories:
        category_id, name, kind = row["raw"]
        kind = KIND_MAP.get(str(kind), str(kind).lower())
        found = db.query_one(
            "SELECT * FROM categories WHERE family_id = ? AND name = ? AND kind = ?",
            (family_id, str(name), kind),
        )
        if found:
            category_map[int(category_id)] = int(found["id"])
            continue
        try:
            new_id = svc.create_category(admin, str(name), kind, None)
        except ConflictError:
            found = db.query_one(
                "SELECT * FROM categories WHERE family_id = ? AND name = ? AND kind = ?",
                (family_id, str(name), kind),
            )
            if not found:
                raise
            new_id = int(found["id"])
        category_map[int(category_id)] = int(new_id)
        stats["categories"] += 1

    # 3. Transactions, mapped to integer cents.
    for row in transactions:
        transaction_id, user_id, category_id, amount, tx_type, description, tx_date = row["raw"]
        kind = KIND_MAP.get(str(tx_type), str(tx_type).lower())
        actor = svc.get_user(user_map[int(user_id)])
        note = str(description or "")
        cents = int((Decimal(str(amount)) * 100).quantize(Decimal("1")))
        duplicate = db.query_one(
            "SELECT id FROM transactions WHERE family_id = ? AND user_id = ? AND category_id = ? "
            "AND amount_cents = ? AND occurred_on = ? AND note = ?",
            (family_id, actor["id"], category_map[int(category_id)], cents, str(tx_date), note),
        )
        if duplicate:
            stats["skipped"] += 1
            continue
        try:
            svc.add_transaction(actor, kind, amount, category_map[int(category_id)], str(tx_date), note)
        except ValidationError as exc:
            print(f"  skipped transaction {transaction_id}: {exc.message}")
            stats["skipped"] += 1
            continue
        stats["transactions"] += 1

    return stats, int(family_id)


def verify(db: Database, family_id: int) -> None:
    print()
    print("Balances after the import (same numbers as Alibek's user_balance view):")
    rows = db.query(
        "SELECT u.full_name, "
        "  COALESCE(SUM(CASE WHEN t.kind = 'income' THEN t.amount_cents END), 0) AS income, "
        "  COALESCE(SUM(CASE WHEN t.kind = 'expense' THEN t.amount_cents END), 0) AS expense "
        "FROM users u LEFT JOIN transactions t ON t.user_id = u.id "
        "WHERE u.family_id = ? GROUP BY u.id, u.full_name ORDER BY u.id",
        (family_id,),
    )
    for row in rows:
        income = int(row["income"]) / 100
        expense = int(row["expense"]) / 100
        print(f"  {row['full_name']:<20} income {income:>10.2f}   expense {expense:>10.2f}   balance {income - expense:>10.2f}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Import Alibek's dump into the application schema")
    parser.add_argument("--schema", required=True, help="path to Alibek's schema.sql (for reference)")
    parser.add_argument("--data", required=True, help="path to Alibek's data.sql")
    parser.add_argument("--family", default="Family (imported)", help="family name for the imported users")
    parser.add_argument("--password", default="Demo1234", help="password given to every imported user")
    parser.add_argument("--sqlite", help="import into a SQLite file instead of PostgreSQL (for testing)")
    args = parser.parse_args()

    data_text = Path(args.data).read_text(encoding="utf-8")
    dump = parse_dump(data_text)
    print(f"Parsed: {len(dump['users'])} users, {len(dump['categories'])} categories, "
          f"{len(dump['transactions'])} transactions")

    url = (os.getenv("DATABASE_URL") or "").strip() if not args.sqlite else None
    db = Database(url, args.sqlite or ROOT / "data" / "family_budget.db")
    db.init_schema()
    svc = BudgetService(db, "KZT")

    stats, family_id = run(db, svc, dump, args.family, args.password)
    print(f"Imported: {stats['users']} users, {stats['categories']} categories, "
          f"{stats['transactions']} transactions, {stats['skipped']} skipped (already present)")
    verify(db, family_id)
    print()
    print(f"Sign in with any imported e-mail and the password: {args.password}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
