"""Check Abu Nurbol's nine defects against this build.

Abu tested his own reference module (his report, section 7). This script takes
the same nine defects, reproduces the same attempts against the team application
layer, and prints where each one stands here. Run it before the integration
meeting:

    python tools/abu_conformance.py
"""

from __future__ import annotations

import shutil
import sqlite3
import sys
import uuid
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.db import Database
from core.services import AccessDenied, BudgetService
from core.validators import ValidationError

TMP = ROOT / "tests" / "_tmp"
RESULTS: list[tuple[str, str, str, str]] = []  # id, title, status, note


def check(abu_id: str, title: str, expectation: str):
    def wrapper(fn):
        try:
            note = fn() or ""
            status = "FIXED"
        except Exception as exc:  # noqa: BLE001
            status = "OPEN"
            note = f"{type(exc).__name__}: {exc}"
        RESULTS.append((abu_id, title, status, note or expectation))
        return fn

    return wrapper


def raises(exc, call) -> bool:
    try:
        call()
    except exc:
        return True
    return False


TMP.mkdir(parents=True, exist_ok=True)
work = TMP / f"abu_{uuid.uuid4().hex[:8]}"
work.mkdir(parents=True)
db = Database(None, work / "abu.db")
db.init_schema()
svc = BudgetService(db, "KZT")

admin = svc.register_family("Abu Check", "Arman Admin", "arman@abu.kz", "Secret123")
family = svc.get_family(admin["family_id"])
member = svc.join_family(family["invite_code"], "Teen Member", "teen@abu.kz", "Secret123")
cats = {c["name"]: c for c in svc.list_categories(admin["family_id"])}
food = cats["Food"]["id"]


@check("D-01", "Duplicate transaction ID accepted (Critical)", "system IDs cannot repeat; PK rejects a direct duplicate")
def d01() -> str:
    for _ in range(20):
        svc.add_transaction(admin, "expense", 100, food, date.today())
    codes = [r["code"] for r in svc.list_transactions(admin["family_id"])]
    assert len(codes) == len(set(codes)), "duplicate code"
    # The database itself must refuse a duplicate primary key, even if a client
    # bypasses the application layer.
    with db.connection() as conn:
        cur = conn.cursor()
        try:
            cur.execute(
                "INSERT INTO transactions (id, family_id, user_id, category_id, kind, amount_cents, occurred_on, note) "
                "VALUES (1, ?, ?, ?, 'expense', 100, ?, 'dup')",
                (admin["family_id"], admin["id"], food, date.today().isoformat()),
            )
            conn.commit()
        except sqlite3.IntegrityError:
            conn.rollback()
        else:
            raise AssertionError("database accepted a duplicate id")
        finally:
            cur.close()
    return "20 unique codes; direct duplicate insert rejected by the primary key"


@check("D-02", "Negative and zero amounts accepted (Critical)", "service rejects and the table CHECK rejects")
def d02() -> str:
    assert raises(ValidationError, lambda: svc.add_transaction(admin, "expense", -500, food, date.today()))
    assert raises(ValidationError, lambda: svc.add_transaction(admin, "expense", 0, food, date.today()))
    with db.connection() as conn:
        cur = conn.cursor()
        try:
            cur.execute(
                "INSERT INTO transactions (family_id, user_id, category_id, kind, amount_cents, occurred_on, note) "
                "VALUES (?, ?, ?, 'expense', -100, ?, 'bad')",
                (admin["family_id"], admin["id"], food, date.today().isoformat()),
            )
            conn.commit()
        except sqlite3.IntegrityError:
            conn.rollback()
        else:
            raise AssertionError("database accepted a negative amount")
        finally:
            cur.close()
    return "rejected in the service and by CHECK (amount_cents > 0)"


@check("D-03", "Future and wrongly formatted dates accepted (High)", "both rejected with a date message")
def d03() -> str:
    assert raises(
        ValidationError, lambda: svc.add_transaction(admin, "expense", 1000, food, date.today() + timedelta(days=1))
    )
    assert raises(ValidationError, lambda: svc.add_transaction(admin, "expense", 1000, food, "10/10/2026"))
    try:
        svc.add_transaction(admin, "expense", 1000, food, "10/10/2026")
    except ValidationError as exc:
        assert exc.field == "occurred_on"
        return "rejected; field name reported to the form"
    raise AssertionError("no error")


@check("D-04", "Unapproved and unknown categories accepted (High)", "unknown, foreign and mismatched categories rejected")
def d04() -> str:
    assert raises(ValidationError, lambda: svc.add_transaction(admin, "expense", 100, 999_999, date.today()))
    other = svc.register_family("Other Family", "Stranger", "s@abu.kz", "Secret123")
    foreign = next(c for c in svc.list_categories(other["family_id"]) if c["name"] == "Food")
    assert raises(ValidationError, lambda: svc.add_transaction(admin, "expense", 100, foreign["id"], date.today()))
    assert raises(ValidationError, lambda: svc.add_transaction(admin, "expense", 100, cats["Salary"]["id"], date.today()))
    with db.connection() as conn:
        cur = conn.cursor()
        try:
            cur.execute(
                "INSERT INTO transactions (family_id, user_id, category_id, kind, amount_cents, occurred_on, note) "
                "VALUES (?, ?, 999999, 'expense', 100, ?, 'orphan')",
                (admin["family_id"], admin["id"], date.today().isoformat()),
            )
            conn.commit()
        except sqlite3.IntegrityError:
            conn.rollback()
        else:
            raise AssertionError("foreign key did not reject the orphan row")
        finally:
            cur.close()
    return "unknown / foreign / wrong-kind categories rejected; FK blocks orphans"


@check("D-05", "Income ignored by the month summary (Critical)", "income is counted and the balance is correct")
def d05() -> str:
    today = date.today()
    before = svc.month_summary(admin["family_id"], today.year, today.month)
    svc.add_transaction(admin, "income", 100_000, cats["Salary"]["id"], today, "Freelance")
    after = svc.month_summary(admin["family_id"], today.year, today.month)
    assert after["income_cents"] - before["income_cents"] == 10_000_000
    assert after["balance_cents"] == after["income_cents"] - after["expense_cents"]
    return f"income {after['income_cents'] / 100:.2f} KZT counted in the balance"


@check("D-06", "Money stored as floating point (High)", "amounts are integer cents, totals exact")
def d06() -> str:
    today = date.today()
    before = svc.month_summary(admin["family_id"], today.year, today.month)["expense_cents"]
    for _ in range(3):
        svc.add_transaction(admin, "expense", "0.10", food, today)
    after = svc.month_summary(admin["family_id"], today.year, today.month)["expense_cents"]
    assert after - before == 30, f"expected 30 cents, got {after - before}"
    return "three expenses of 0.10 give exactly 0.30"


@check("D-07", "Rejected record still written (Medium)", "a rejected save leaves zero rows")
def d07() -> str:
    before = len(svc.list_transactions(admin["family_id"]))
    for _ in range(5):
        try:
            svc.add_transaction(admin, "expense", -1, food, date.today())
        except ValidationError:
            pass
    after = len(svc.list_transactions(admin["family_id"]))
    assert before == after, f"row count changed {before} -> {after}"
    return "5 rejected attempts, row count unchanged"


@check("D-08", "No ownership check when editing a record (High)", "a member cannot change or delete another member's row")
def d08() -> str:
    admin_tx = svc.add_transaction(admin, "expense", 500, food, date.today(), "mother's record")
    assert raises(AccessDenied, lambda: svc.delete_transaction(member, admin_tx))
    own = svc.add_transaction(member, "expense", 300, food, date.today(), "teen's record")
    svc.delete_transaction(member, own)  # own row is allowed
    return "member refused on another member's row, allowed on their own (edit is not implemented yet)"


@check("D-09", "Error messages did not name the field (Low)", "every rejection carries a field and a readable message")
def d09() -> str:
    cases = [
        (lambda: svc.add_transaction(admin, "expense", "abc", food, date.today()), "amount"),
        (lambda: svc.add_transaction(admin, "expense", 100, food, "2027-01-15"), "occurred_on"),
        (lambda: svc.add_transaction(admin, "expense", 100, 999_999, date.today()), "category_id"),
    ]
    for call, field in cases:
        try:
            call()
        except ValidationError as exc:
            assert exc.field == field, f"expected field {field}, got {exc.field}"
            assert len(exc.message) > 10
        else:
            raise AssertionError("no error")
    return "amount / occurred_on / category_id each reported separately"


def main() -> int:
    width_id, width_title = 6, 52
    print("Abu Nurbol's defect log, checked against the team build")
    print("=" * 108)
    print(f"{'ID':<{width_id}} {'Defect from the report':<{width_title}} {'Status':<8} Note")
    print("-" * 108)
    fixed = 0
    for abu_id, title, status, note in RESULTS:
        fixed += status == "FIXED"
        print(f"{abu_id:<{width_id}} {title[:width_title]:<{width_title}} {status:<8} {note}")
    print("-" * 108)
    print(f"{fixed} of {len(RESULTS)} defects are already closed in this build")
    if fixed != len(RESULTS):
        print("OPEN items must be reported to the team before the integration meeting.")
        return 1
    print("No open item from Abu's log reproduces here.")
    return 0


if __name__ == "__main__":
    try:
        code = main()
    finally:
        shutil.rmtree(work, ignore_errors=True)
    sys.exit(code)
