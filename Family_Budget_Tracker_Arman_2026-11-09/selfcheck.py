"""End-to-end self check of the application data path.

It runs the exact sequence the Streamlit screens perform - registration, sign-in,
adding transactions, filtering the history, budgets, roles, CSV export - against
a throw-away database. Run it before the weekly check:

    python selfcheck.py

Exit code 0 means every check passed.
"""

from __future__ import annotations

import sys
import uuid
from datetime import date, timedelta
from pathlib import Path

from core.db import Database
from core.export import transactions_to_csv
from core.services import AccessDenied, AuthError, BudgetService
from core.validators import ValidationError, month_bounds

DB_PATH = Path(__file__).resolve().parent / "data" / "selfcheck.db"
PASSWORD = "Demo1234"
results: list[tuple[str, bool, str]] = []


def check(name: str):
    def wrapper(fn):
        try:
            detail = fn() or ""
            results.append((name, True, str(detail)))
        except Exception as exc:  # noqa: BLE001 - report every failure, keep going
            results.append((name, False, f"{type(exc).__name__}: {exc}"))
        return fn

    return wrapper


def fresh_service() -> BudgetService:
    if DB_PATH.exists():
        DB_PATH.unlink()
    for suffix in ("-wal", "-shm"):
        extra = Path(str(DB_PATH) + suffix)
        if extra.exists():
            extra.unlink()
    db = Database(None, DB_PATH)
    db.init_schema()
    return BudgetService(db, "KZT")


svc = fresh_service()
state: dict[str, object] = {}


@check("1. Registration creates a family, an admin and 12 default categories")
def _register() -> str:
    admin = svc.register_family("Selfcheck Family", "Arman Akhmetshiev", "arman@selfcheck.kz", PASSWORD)
    state["admin"] = admin
    assert admin["role"] == "admin"
    cats = svc.list_categories(admin["family_id"])
    assert len(cats) == 12, f"expected 12 categories, got {len(cats)}"
    state["cats"] = {c["name"]: c for c in cats}
    family = svc.get_family(admin["family_id"])
    assert len(family["invite_code"]) == 6
    return f"invite code {family['invite_code']}, categories {len(cats)}"


@check("2. Sign-in accepts the right password and rejects a wrong one")
def _login() -> str:
    user = svc.authenticate("  ARMAN@selfcheck.kz ", PASSWORD)
    assert user["id"] == state["admin"]["id"]
    try:
        svc.authenticate("arman@selfcheck.kz", "WrongPass1")
    except AuthError:
        return "wrong password blocked"
    raise AssertionError("wrong password was accepted")


@check("3. Expense is saved, listed and subtracted from the balance")
def _expense() -> str:
    admin = state["admin"]
    cats = state["cats"]
    svc.add_transaction(admin, "expense", "2500.50", cats["Food"]["id"], date.today(), "Magnum")
    rows = svc.list_transactions(admin["family_id"])
    assert len(rows) == 1 and rows[0]["amount_cents"] == 250_050
    summary = svc.month_summary(admin["family_id"], date.today().year, date.today().month)
    assert summary["expense_cents"] == 250_050
    assert summary["balance_cents"] == -250_050
    return "2500.50 KZT stored as 250050 cents"


@check("4. Income increases the balance")
def _income() -> str:
    admin = state["admin"]
    svc.add_transaction(admin, "income", 600_000, state["cats"]["Salary"]["id"], date.today(), "Salary")
    total = svc.lifetime_balance(admin["family_id"])
    assert total["balance_cents"] == 600_000_00 - 250_050, total
    return f"balance {total['balance_cents']} cents"


@check("5. Invalid input is rejected before it reaches the database")
def _invalid() -> str:
    admin = state["admin"]
    food = state["cats"]["Food"]["id"]
    cases = [
        ("negative amount", lambda: svc.add_transaction(admin, "expense", -500, food, date.today())),
        ("zero amount", lambda: svc.add_transaction(admin, "expense", 0, food, date.today())),
        ("future date", lambda: svc.add_transaction(admin, "expense", 1000, food, date.today() + timedelta(days=1))),
        ("wrong category type", lambda: svc.add_transaction(admin, "expense", 1000, state["cats"]["Salary"]["id"], date.today())),
    ]
    for label, call in cases:
        try:
            call()
        except ValidationError:
            continue
        raise AssertionError(f"{label} was accepted")
    assert len(svc.list_transactions(admin["family_id"])) == 2
    return "4 invalid records blocked, table still has 2 rows"


def _food_status(family_id: int, day: date) -> dict:
    rows = svc.budget_status(family_id, day.year, day.month)
    return next(r for r in rows if r["name"] == "Food")


@check("6. Budget status moves from ok to warning to over")
def _budgets() -> str:
    admin = state["admin"]
    food = state["cats"]["Food"]["id"]
    today = date.today()
    svc.add_transaction(admin, "expense", 100_000, food, today)
    status = _food_status(admin["family_id"], today)
    assert status["status"] == "ok", status
    svc.add_transaction(admin, "expense", 25_000, food, today)
    status = _food_status(admin["family_id"], today)
    assert status["status"] == "warning", status
    svc.add_transaction(admin, "expense", 30_000, food, today)
    status = _food_status(admin["family_id"], today)
    assert status["status"] == "over" and status["remaining_cents"] < 0, status
    return "ok -> warning -> over"


@check("7. A second member joins with the invite code and gets member rights")
def _member() -> str:
    admin = state["admin"]
    family = svc.get_family(admin["family_id"])
    member = svc.join_family(family["invite_code"], "Aigerim Akhmetshieva", "aigerim@selfcheck.kz", PASSWORD)
    state["member"] = member
    assert member["role"] == "member"
    try:
        svc.create_category(member, "Pets", "expense", 10_000)
    except AccessDenied:
        pass
    else:
        raise AssertionError("member was allowed to create a category")
    return "member cannot change the structure"


@check("8. A member cannot delete another member's transaction, the admin can")
def _permissions() -> str:
    admin = state["admin"]
    member = state["member"]
    tx = svc.add_transaction(member, "expense", 1200, state["cats"]["Transport"]["id"], date.today(), "Bus")
    try:
        svc.delete_transaction(admin, tx)  # admin may delete anything
    except Exception as exc:  # noqa: BLE001
        raise AssertionError(f"admin could not delete: {exc}") from exc
    tx2 = svc.add_transaction(admin, "expense", 900, state["cats"]["Transport"]["id"], date.today(), "Taxi")
    try:
        svc.delete_transaction(member, tx2)
    except AccessDenied:
        return "protected"
    raise AssertionError("member deleted an admin row")


@check("9. History filter and CSV export return the same rows")
def _export() -> str:
    admin = state["admin"]
    rows = svc.list_transactions(admin["family_id"], kind="expense", search="food")
    assert rows, "no expense rows found"
    payload = transactions_to_csv(rows)
    text = payload.decode("utf-8-sig")
    assert text.startswith("Transaction ID,Date,Type,Category,Member,Amount,Note")
    assert text.count("\n") == len(rows) + 1, text
    assert "TX-" in text
    return f"{len(rows)} rows exported, {len(payload)} bytes"


@check("10. Six-month trend and month bounds are correct")
def _trend() -> str:
    admin = state["admin"]
    trend = svc.monthly_trend(admin["family_id"], 6)
    assert len(trend) == 6
    start, end = month_bounds(2026, 2)
    assert (start, end) == (date(2026, 2, 1), date(2026, 2, 28))
    return f"{trend[0]['label']} … {trend[-1]['label']}"


def main() -> int:
    print("Family Budget Tracker - self check")
    print(f"Database: {DB_PATH}")
    print("-" * 78)
    passed = 0
    for name, ok, detail in results:
        mark = "PASS" if ok else "FAIL"
        print(f"[{mark}] {name}")
        if detail:
            print(f"       {detail}")
        passed += ok
    print("-" * 78)
    print(f"{passed}/{len(results)} checks passed")
    if passed != len(results):
        print("Self check FAILED - fix the errors above before the lesson.")
        return 1
    print("Self check OK - the application data path works end to end.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
