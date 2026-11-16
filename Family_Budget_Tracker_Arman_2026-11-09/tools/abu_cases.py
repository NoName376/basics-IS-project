"""Run Abu Nurbol's 31 test cases against the team build.

His suite was written for his reference module. This script re-implements the
same 31 cases on top of the team service layer, so the results can be compared
one to one. The cases are taken from his report, section 5 (tables 5.1-5.3).

Statuses:
    PASS   the case passes on this build with the same input
    PASS*  the case passes, but the check was adapted to this data model
           (for example, transaction IDs are generated, there is no receipt path)
    N/A    the feature does not exist in this build; the reason is printed
    FAIL   the behaviour does not match the expected result

Run:
    python tools/abu_cases.py
"""

from __future__ import annotations

import shutil
import sqlite3
import sys
import uuid
from datetime import date
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import security

security.ITERATIONS = 1000  # test fixtures only; stored hashes keep their own count

from core.db import Database  # noqa: E402
from core.services import AccessDenied, BudgetService  # noqa: E402
from core.validators import ValidationError  # noqa: E402

TMP = ROOT / "tests" / "_tmp_cases"
RESULTS: list[tuple[str, str, str, str]] = []


def case(case_id: str, title: str, status_if_pass: str = "PASS"):
    def wrapper(fn):
        if status_if_pass == "N/A":
            RESULTS.append((case_id, title, "N/A", "feature is not part of this schema"))
            return fn
        try:
            note = fn() or ""
            status = status_if_pass
        except Exception as exc:  # noqa: BLE001
            status = "FAIL"
            note = f"{type(exc).__name__}: {exc}"
        RESULTS.append((case_id, title, status, note))
        return fn

    return wrapper


def fixture():
    folder = TMP / uuid.uuid4().hex[:8]
    folder.mkdir(parents=True)
    db = Database(None, folder / "case.db")
    db.init_schema()
    svc = BudgetService(db, "KZT")
    admin = svc.register_family("Test Family", "Parent One", f"p1_{folder.name}@test.kz", "Secret123")
    family = svc.get_family(admin["family_id"])
    member = svc.join_family(family["invite_code"], "Teen", f"teen_{folder.name}@test.kz", "Secret123")
    cats = {c["name"]: c for c in svc.list_categories(admin["family_id"])}
    return db, svc, admin, member, cats, folder


def rows_count(svc: BudgetService, family_id: int) -> int:
    return len(svc.list_transactions(family_id, limit=1000))


def expect_error(svc, actor, kind, amount, category_id, day):
    try:
        svc.add_transaction(actor, kind, amount, category_id, day)
    except ValidationError as exc:
        return exc
    raise AssertionError("invalid record was accepted")


# --------------------------------------------------------------------- functional
def _f01():
    db, svc, admin, _, cats, _ = fixture()
    svc.add_transaction(admin, "expense", "2500.00", cats["Food"]["id"], "2026-10-12", "Magnum")
    rows = svc.list_transactions(admin["family_id"])
    assert len(rows) == 1
    assert rows[0]["amount_cents"] == 250000, rows[0]
    assert rows[0]["occurred_on"] == date(2026, 10, 12)
    return "stored once, exact amount and date"


def _f02():
    db, svc, admin, _, cats, _ = fixture()
    exc = expect_error(svc, admin, "expense", "", cats["Food"]["id"], date.today())
    assert exc.field == "amount"
    assert rows_count(svc, admin["family_id"]) == 0
    return "empty amount rejected, no row written"


def _f03():
    db, svc, admin, _, cats, _ = fixture()
    expect_error(svc, admin, "expense", "-500.00", cats["Food"]["id"], date.today())
    assert rows_count(svc, admin["family_id"]) == 0
    return "negative rejected"


def _f04():
    db, svc, admin, _, cats, _ = fixture()
    expect_error(svc, admin, "expense", 0, cats["Food"]["id"], date.today())
    return "zero rejected"


def _f05():
    db, svc, admin, _, cats, _ = fixture()
    expect_error(svc, admin, "expense", "two thousand", cats["Food"]["id"], date.today())
    return "non-numeric rejected with a readable message"


def _f06():
    db, svc, admin, _, cats, _ = fixture()
    expect_error(svc, admin, "expense", 1000, cats["Food"]["id"], "2027-01-15")
    return "future date rejected"


def _f07():
    db, svc, admin, _, cats, _ = fixture()
    exc = expect_error(svc, admin, "expense", 1000, cats["Food"]["id"], "10/10/2026")
    assert exc.field == "occurred_on"
    return "non-ISO date rejected"


def _f08():
    db, svc, admin, _, cats, _ = fixture()
    other = svc.register_family("Other", "Stranger", "s@test.kz", "Secret123")
    foreign = next(c for c in svc.list_categories(other["family_id"]) if c["name"] == "Food")
    expect_error(svc, admin, "expense", 1000, foreign["id"], date.today())
    return "category from another family rejected (this model has no global list)"


def _f09():
    db, svc, admin, _, cats, _ = fixture()
    expect_error(svc, admin, "expense", 1000, 999_999, date.today())
    return "unknown category rejected"


def _f10():
    db, svc, admin, _, cats, _ = fixture()
    svc.add_transaction(admin, "expense", 1000, cats["Food"]["id"], date.today())
    codes = [r["code"] for r in svc.list_transactions(admin["family_id"])]
    assert len(codes) == len(set(codes))
    with db.connection() as conn:
        cur = conn.cursor()
        try:
            cur.execute(
                "INSERT INTO transactions (id, family_id, user_id, category_id, kind, amount_cents, occurred_on, note) "
                "VALUES (1, ?, ?, ?, 'expense', 100, ?, 'duplicate')",
                (admin["family_id"], admin["id"], cats["Food"]["id"], date.today().isoformat()),
            )
            conn.commit()
        except sqlite3.IntegrityError:
            conn.rollback()
        else:
            raise AssertionError("duplicate ID accepted")
        finally:
            cur.close()
    return "IDs are generated (TX-000001); a duplicate is refused by the primary key"


def _f11():
    db, svc, admin, _, cats, _ = fixture()
    svc.add_transaction(admin, "expense", 2500, cats["Food"]["id"], date.today())
    svc.add_transaction(admin, "income", "30000.00", cats["Salary"]["id"], date.today(), "Freelance")
    summary = svc.month_summary(admin["family_id"], date.today().year, date.today().month)
    assert summary["income_cents"] == 3_000_000, summary
    return f"income {summary['income_cents'] / 100:.2f} counted"


def _f12():
    db, svc, admin, _, cats, _ = fixture()
    today = date.today()
    svc.add_transaction(admin, "income", "480000.00", cats["Salary"]["id"], today)
    svc.add_transaction(admin, "expense", "32500.00", cats["Food"]["id"], today)
    summary = svc.month_summary(admin["family_id"], today.year, today.month)
    assert summary["balance_cents"] == 44_750_000, summary
    return "balance 447 500.00 for income 480 000 / expense 32 500"


def _f13():
    db, svc, admin, _, cats, _ = fixture()
    today = date.today()
    svc.add_transaction(admin, "expense", 1000, cats["Food"]["id"], today)
    svc.add_transaction(admin, "expense", 2000, cats["Transport"]["id"], today)
    breakdown = svc.category_breakdown(admin["family_id"], today.year, today.month)
    expenses = sum(r["total_cents"] for r in breakdown if r["kind"] == "expense")
    summary = svc.month_summary(admin["family_id"], today.year, today.month)
    assert expenses == summary["expense_cents"]
    assert all(r["name"] for r in breakdown)
    return "category totals equal the expense total, every row has a name"


def _f14():
    db, svc, admin, _, cats, _ = fixture()
    today = date.today()
    for _ in range(3):
        svc.add_transaction(admin, "expense", "0.10", cats["Food"]["id"], today)
    summary = svc.month_summary(admin["family_id"], today.year, today.month)
    assert summary["expense_cents"] == 30, summary
    return "three expenses of 0.10 give exactly 0.30"


def _f15():
    db, svc, admin, _, cats, _ = fixture()
    before = rows_count(svc, admin["family_id"])
    for _ in range(3):
        try:
            svc.add_transaction(admin, "expense", -5, cats["Food"]["id"], date.today())
        except ValidationError:
            pass
    assert rows_count(svc, admin["family_id"]) == before
    return "three rejected saves, row count unchanged"


# -------------------------------------------------------------------- integration
def _i01():
    db, svc, admin, _, cats, _ = fixture()
    svc.add_transaction(admin, "expense", "1234.56", cats["Food"]["id"], date.today())
    cents = db.scalar("SELECT amount_cents FROM transactions ORDER BY id DESC LIMIT 1")
    assert int(cents) == 123456, cents
    return "1234.56 stored as 123456 tiyn and read back exactly"


def _i02():
    db, svc, admin, _, cats, _ = fixture()
    with db.connection() as conn:
        cur = conn.cursor()
        try:
            cur.execute(
                "INSERT INTO transactions (family_id, user_id, category_id, kind, amount_cents, occurred_on, note) "
                "VALUES (?, ?, ?, 'expense', -100, ?, 'bad')",
                (admin["family_id"], admin["id"], cats["Food"]["id"], date.today().isoformat()),
            )
            conn.commit()
        except sqlite3.IntegrityError:
            conn.rollback()
        else:
            raise AssertionError("database accepted a negative amount")
        finally:
            cur.close()
    return "CHECK (amount_cents > 0) refuses a direct negative insert"


def _i03():
    db, svc, admin, _, cats, _ = fixture()
    svc.add_transaction(admin, "expense", 100, cats["Food"]["id"], date.today())
    with db.connection() as conn:
        cur = conn.cursor()
        try:
            cur.execute(
                "INSERT INTO transactions (id, family_id, user_id, category_id, kind, amount_cents, occurred_on, note) "
                "VALUES (1, ?, ?, ?, 'expense', 100, ?, 'dup')",
                (admin["family_id"], admin["id"], cats["Food"]["id"], date.today().isoformat()),
            )
            conn.commit()
        except sqlite3.IntegrityError:
            conn.rollback()
        else:
            raise AssertionError("duplicate primary key accepted")
        finally:
            cur.close()
    return "primary key refuses a duplicate even when SQL bypasses the application"


def _i04():
    db, svc, admin, _, cats, _ = fixture()
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
    return "foreign key rejects an orphan category"


def _i05():
    db, svc, admin, _, cats, _ = fixture()
    svc.add_transaction(admin, "expense", 100, cats["Food"]["id"], date.today())
    try:
        svc.add_transaction(admin, "expense", 100, 999999, date.today())
    except ValidationError:
        pass
    orphans = db.scalar(
        "SELECT COUNT(*) FROM transactions t LEFT JOIN categories c ON c.id = t.category_id WHERE c.id IS NULL"
    )
    assert int(orphans) == 0, orphans
    return "no expense row exists without a category"


def _i06():
    db, svc, admin, _, cats, _ = fixture()
    today = date.today()
    svc.add_transaction(admin, "expense", 1000, cats["Food"]["id"], today)
    svc.add_transaction(admin, "expense", 2500, cats["Transport"]["id"], today)
    summary = svc.month_summary(admin["family_id"], today.year, today.month)
    sql_total = db.scalar(
        "SELECT COALESCE(SUM(amount_cents), 0) FROM transactions WHERE family_id = ? AND kind = 'expense'",
        (admin["family_id"],),
    )
    assert summary["expense_cents"] == int(sql_total)
    return "application summary equals an independent SQL aggregate"


def _i07():
    db, svc, admin, _, cats, _ = fixture()
    svc.add_transaction(admin, "expense", 700, cats["Food"]["id"], "2026-10-20", "persist")
    db2 = Database(None, db.sqlite_path)
    svc2 = BudgetService(db2, "KZT")
    rows = svc2.list_transactions(admin["family_id"], search="persist")
    assert len(rows) == 1 and rows[0]["occurred_on"] == date(2026, 10, 20)
    return "record survives closing and reopening the database file"


def _i08():
    db, svc, admin, _, cats, _ = fixture()
    svc.add_transaction(admin, "expense", 500, cats["Food"]["id"], "2026-09-15", "september")
    svc.add_transaction(admin, "expense", 600, cats["Food"]["id"], "2026-10-15", "october")
    rows = svc.list_transactions(admin["family_id"], start=date(2026, 9, 1), end=date(2026, 9, 30))
    assert len(rows) == 1 and rows[0]["note"] == "september"
    return "September filter finds exactly the September record"


def _i09():
    raise NotImplementedError("no receipt column in this schema")


def _i10():
    db, svc, admin, _, cats, _ = fixture()
    with db.connection() as conn:
        cur = conn.cursor()
        try:
            cur.execute(
                "INSERT INTO transactions (family_id, user_id, category_id, kind, amount_cents, occurred_on, note) "
                "VALUES (?, ?, 999999, 'expense', 100, ?, 'orphan')",
                (admin["family_id"], admin["id"], date.today().isoformat()),
            )
        except sqlite3.IntegrityError:
            conn.rollback()
        finally:
            cur.close()
    count = db.scalar("SELECT COUNT(*) FROM transactions")
    assert int(count) == 0, count
    return "rollback after a failed insert leaves no row"


def _i11():
    db, svc, admin, _, cats, _ = fixture()
    svc.add_transaction(admin, "expense", 100, cats["Food"]["id"], "2026-09-30")
    svc.add_transaction(admin, "expense", 200, cats["Food"]["id"], "2026-10-01")
    raw = [r["occurred_on"] for r in db.query("SELECT occurred_on FROM transactions")]
    assert all(isinstance(value, str) and len(value) == 10 and value[4] == "-" for value in raw), raw
    # ISO strings must sort in the same order as the dates they represent.
    by_string = sorted(raw)
    by_date = [day.isoformat() for day in sorted(date.fromisoformat(value) for value in raw)]
    assert by_string == by_date, (by_string, by_date)
    return "dates stored as YYYY-MM-DD; string order equals chronological order"


# --------------------------------------------------------------------------- UAT
def _u01():
    db, svc, admin, _, cats, _ = fixture()
    today = date.today()
    before = svc.month_summary(admin["family_id"], today.year, today.month)["balance_cents"]
    svc.add_transaction(admin, "expense", "4300.00", cats["Food"]["id"], today, "receipt")
    after = svc.month_summary(admin["family_id"], today.year, today.month)["balance_cents"]
    assert before - after == 430_000, (before, after)
    return "balance drops by exactly 4 300.00"


def _u02():
    db, svc, admin, _, cats, _ = fixture()
    exc = expect_error(svc, admin, "expense", -100, cats["Food"]["id"], date.today())
    assert exc.field == "amount", exc.field
    assert "amount" in exc.message.lower(), exc.message
    return f'plain message naming the field: "{exc.message}"'


def _u03():
    db, svc, admin, member, cats, _ = fixture()
    today = date.today()
    svc.add_transaction(member, "income", "30000.00", cats["Salary"]["id"], today, "freelance")
    a = svc.month_summary(admin["family_id"], today.year, today.month)
    b = svc.month_summary(member["family_id"], today.year, today.month)
    assert a["income_cents"] == b["income_cents"] == 3_000_000
    return "both members see the same summary after the second parent adds income"


def _u04():
    db, svc, admin, _, cats, _ = fixture()
    today = date.today()
    svc.add_transaction(admin, "expense", 1000, cats["Food"]["id"], today)
    svc.add_transaction(admin, "expense", 2000, cats["Shopping"]["id"], today)
    breakdown = svc.category_breakdown(admin["family_id"], today.year, today.month)
    total = sum(r["total_cents"] for r in breakdown)
    assert total == svc.month_summary(admin["family_id"], today.year, today.month)["expense_cents"]
    assert all(r["name"] for r in breakdown)
    return "report totals add up to the expense total and have real names"


def _u05():
    db, svc, admin, member, cats, _ = fixture()
    tx = svc.add_transaction(admin, "expense", 500, cats["Food"]["id"], date.today(), "mother's record")
    try:
        svc.delete_transaction(member, tx)
    except AccessDenied:
        return "member refused on another member's record (edit is not implemented)"
    raise AssertionError("member changed another member's record")


case("TC-F-01", "Valid expense saved with exact amount and date")(_f01)
case("TC-F-02", "Empty amount rejected, nothing stored")(_f02)
case("TC-F-03", "Negative amount rejected")(_f03)
case("TC-F-04", "Zero amount rejected")(_f04)
case("TC-F-05", "Non-numeric amount rejected")(_f05)
case("TC-F-06", "Future date rejected")(_f06)
case("TC-F-07", "Non-ISO date rejected")(_f07)
case("TC-F-08", "Category outside the approved list rejected", "PASS*")(_f08)
case("TC-F-09", "Unknown category rejected")(_f09)
case("TC-F-10", "Duplicate transaction ID impossible", "PASS*")(_f10)
case("TC-F-11", "Income counted in the month summary")(_f11)
case("TC-F-12", "Balance equals income minus expense", "PASS*")(_f12)
case("TC-F-13", "Category breakdown sums to the expense total")(_f13)
case("TC-F-14", "Three 0.10 expenses total exactly 0.30")(_f14)
case("TC-F-15", "Rejected save leaves no partial row")(_f15)
case("TC-I-01", "App write read back by raw SQL exactly")(_i01)
case("TC-I-02", "Negative amount rejected by the database")(_i02)
case("TC-I-03", "Duplicate ID rejected by the database")(_i03)
case("TC-I-04", "Foreign key rejects an orphan category")(_i04)
case("TC-I-05", "No expense without a category name")(_i05)
case("TC-I-06", "App summary equals independent SQL aggregate")(_i06)
case("TC-I-07", "Record survives a database restart")(_i07)
case("TC-I-08", "September filter finds the September record")(_i08)
case("TC-I-09", "Receipt photo path stored unchanged", "N/A")(_i09)
case("TC-I-10", "Rollback leaves no orphan row")(_i10)
case("TC-I-11", "Dates stored as YYYY-MM-DD and sort correctly")(_i11)
case("TC-U-01", "Parent adds an expense, balance drops by 4 300", "PASS*")(_u01)
case("TC-U-02", "Error names the amount field in plain language")(_u02)
case("TC-U-03", "Second parent's income is visible to both", "PASS*")(_u03)
case("TC-U-04", "Report totals add up to the expense total")(_u04)
case("TC-U-05", "Member cannot change another member's record", "PASS*")(_u05)


def main() -> int:
    print("Abu Nurbol's 31 test cases, executed on the team build")
    print("=" * 112)
    print(f"{'ID':<9} {'Case':<58} {'Status':<7} Note")
    print("-" * 112)
    passed = failed = adapted = na = 0
    for case_id, title, status, note in RESULTS:
        passed += status.startswith("PASS")
        failed += status == "FAIL"
        adapted += status == "PASS*"
        na += status == "N/A"
        print(f"{case_id:<9} {title[:58]:<58} {status:<7} {note}")
    print("-" * 112)
    print(f"{passed}/{len(RESULTS)} pass ({adapted} adapted to this data model), {na} not applicable, {failed} failed")
    if failed:
        print("FAILED cases must be fixed or explained before the test report is handed over.")
        return 1
    print("The team build satisfies the suite; hand this table to Abu for the report.")
    return 0


if __name__ == "__main__":
    try:
        code = main()
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
    sys.exit(code)
