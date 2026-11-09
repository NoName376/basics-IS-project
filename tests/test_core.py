"""Unit tests for the application core (no browser and no server required).

Run:
    python -m unittest discover -s tests -v
"""

from __future__ import annotations

import shutil
import sys
import unittest
import uuid
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

TMP_ROOT = Path(__file__).resolve().parent / "_tmp"

from core.db import Database
from core.export import transactions_to_csv
from core.presentation import budget_rows_html, trend_html
from core.security import hash_password, is_valid_email, normalize_email, verify_password
from core.services import AccessDenied, AuthError, BudgetService, ConflictError
from core.validators import ValidationError, format_money, month_bounds, parse_amount, parse_date


class BaseCase(unittest.TestCase):
    def setUp(self) -> None:
        TMP_ROOT.mkdir(parents=True, exist_ok=True)
        self.tmp = TMP_ROOT / f"case_{uuid.uuid4().hex[:10]}"
        self.tmp.mkdir(parents=True)
        self.db = Database(None, self.tmp / "test.db")
        self.db.init_schema()
        self.svc = BudgetService(self.db, "KZT")
        self.admin = self.svc.register_family("Test Family", "Arman Admin", "arman@test.kz", "Secret123")
        self.cats = {c["name"]: c for c in self.svc.list_categories(self.admin["family_id"])}

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def add(self, name: str, amount: float, day: date | None = None, kind: str = "expense", user=None):
        user = user or self.admin
        return self.svc.add_transaction(user, kind, amount, self.cats[name]["id"], day or date.today())


class TestSecurity(unittest.TestCase):
    def test_hash_is_salted_and_verifiable(self):
        first = hash_password("Secret123")
        second = hash_password("Secret123")
        self.assertNotEqual(first, second, "each password must get its own salt")
        self.assertTrue(verify_password("Secret123", first))
        self.assertFalse(verify_password("secret123", first))
        self.assertNotIn("Secret123", first)

    def test_bad_hash_is_rejected_without_crashing(self):
        self.assertFalse(verify_password("anything", "garbage"))
        self.assertFalse(verify_password("anything", ""))

    def test_email_normalisation(self):
        self.assertEqual(normalize_email("  Arman@Test.KZ "), "arman@test.kz")
        self.assertTrue(is_valid_email("arman@test.kz"))
        self.assertFalse(is_valid_email("arman@test"))
        self.assertFalse(is_valid_email("arman test@kz"))


class TestValidators(unittest.TestCase):
    def test_amount_accepts_real_input(self):
        self.assertEqual(parse_amount("2500"), 250_000)
        self.assertEqual(parse_amount("2500.5"), 250_050)
        self.assertEqual(parse_amount("2 500,75"), 250_075)
        self.assertEqual(parse_amount(45.1), 4_510)

    def test_amount_rejects_invalid_values(self):
        for bad in ["", "-500", "0", "abc", "12.345", "1e5", None]:
            with self.subTest(bad=bad), self.assertRaises(ValidationError):
                parse_amount(bad)

    def test_date_rules(self):
        today = date(2026, 11, 2)
        self.assertEqual(parse_date("2026-10-10", today=today), date(2026, 10, 10))
        with self.assertRaises(ValidationError):
            parse_date("2027-01-15", today=today)  # future
        with self.assertRaises(ValidationError):
            parse_date("10.10.2026", today=today)  # wrong format

    def test_money_format(self):
        self.assertEqual(format_money(250_000), "2 500.00 KZT")
        self.assertEqual(format_money(-50), "-0.50 KZT")
        self.assertEqual(format_money(None), "—")


class TestRegistration(BaseCase):
    def test_registration_creates_admin_and_defaults(self):
        user = self.svc.get_user(self.admin["id"])
        self.assertEqual(user["role"], "admin")
        self.assertNotIn("password_hash", user)
        self.assertGreaterEqual(len(self.cats), 8)
        self.assertEqual(self.cats["Food"]["monthly_limit_cents"], 150_000 * 100)

    def test_duplicate_email_is_rejected(self):
        with self.assertRaises(ConflictError):
            self.svc.register_family("Other", "Someone", "arman@test.kz", "Secret123")

    def test_weak_password_is_rejected(self):
        with self.assertRaises(ValidationError):
            self.svc.register_family("Other", "Someone", "new@test.kz", "short")

    def test_join_with_invite_code(self):
        family = self.svc.get_family(self.admin["family_id"])
        member = self.svc.join_family(family["invite_code"], "Aigerim", "aigerim@test.kz", "Secret123")
        self.assertEqual(member["role"], "member")
        self.assertEqual(member["family_id"], self.admin["family_id"])

    def test_join_with_wrong_code(self):
        with self.assertRaises(ValidationError):
            self.svc.join_family("XXXXXX", "Nobody", "nobody@test.kz", "Secret123")

    def test_authenticate(self):
        self.assertEqual(self.svc.authenticate("ARMAN@test.kz ", "Secret123")["id"], self.admin["id"])
        with self.assertRaises(AuthError):
            self.svc.authenticate("arman@test.kz", "wrong-pass1")


class TestTransactions(BaseCase):
    def test_add_expense_changes_balance(self):
        self.add("Food", 2500)
        self.add("Transport", 800)
        summary = self.svc.month_summary(self.admin["family_id"], date.today().year, date.today().month)
        self.assertEqual(summary["expense_cents"], 330_000)
        self.assertEqual(summary["balance_cents"], -330_000)
        self.assertEqual(summary["transaction_count"], 2)

    def test_income_increases_balance(self):
        self.add("Salary", 600_000, kind="income")
        self.assertEqual(self.svc.lifetime_balance(self.admin["family_id"])["balance_cents"], 60_000_000)

    def test_negative_and_future_rejected(self):
        with self.assertRaises(ValidationError):
            self.add("Food", -500)
        with self.assertRaises(ValidationError):
            self.add("Food", 1000, date.today() + timedelta(days=1))

    def test_category_type_must_match(self):
        with self.assertRaises(ValidationError):
            self.add("Salary", 1000, kind="expense")  # Salary is an income category

    def test_category_from_other_family_is_rejected(self):
        stranger = self.svc.register_family("Other Family", "Stranger", "s@test.kz", "Secret123")
        other_food = next(c for c in self.svc.list_categories(stranger["family_id"]) if c["name"] == "Food")
        with self.assertRaises(ValidationError):
            self.svc.add_transaction(self.admin, "expense", 1000, other_food["id"], date.today())

    def test_member_cannot_delete_someone_elses_row(self):
        admin_tx = self.add("Food", 1000)
        family = self.svc.get_family(self.admin["family_id"])
        member = self.svc.join_family(family["invite_code"], "Aigerim", "aigerim@test.kz", "Secret123")
        with self.assertRaises(AccessDenied):
            self.svc.delete_transaction(member, admin_tx)
        self.svc.delete_transaction(self.admin, admin_tx)
        self.assertEqual(self.svc.list_transactions(self.admin["family_id"]), [])

    def test_member_cannot_create_categories(self):
        family = self.svc.get_family(self.admin["family_id"])
        member = self.svc.join_family(family["invite_code"], "Aigerim", "aigerim@test.kz", "Secret123")
        with self.assertRaises(AccessDenied):
            self.svc.create_category(member, "Pets", "expense", 10_000)

    def test_search_and_filters(self):
        self.add("Food", 1000)
        self.add("Transport", 500)
        rows = self.svc.list_transactions(self.admin["family_id"], search="food")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["category"], "Food")


class TestBudgets(BaseCase):
    def test_budget_thresholds(self):
        self.add("Food", 100_000)  # limit 150 000 -> 66% ok
        row = next(r for r in self.svc.budget_status(self.admin["family_id"], date.today().year,
                                                     date.today().month) if r["name"] == "Food")
        self.assertEqual(row["status"], "ok")

        self.add("Food", 25_000)  # 125 000 -> 83% warning
        row = next(r for r in self.svc.budget_status(self.admin["family_id"], date.today().year,
                                                     date.today().month) if r["name"] == "Food")
        self.assertEqual(row["status"], "warning")
        self.assertAlmostEqual(row["percent"], 83.33, places=1)

        self.add("Food", 30_000)  # 155 000 -> over
        row = next(r for r in self.svc.budget_status(self.admin["family_id"], date.today().year,
                                                     date.today().month) if r["name"] == "Food")
        self.assertEqual(row["status"], "over")
        self.assertEqual(row["remaining_cents"], -5_000_00)

    def test_trend_has_requested_months(self):
        self.add("Food", 1000)
        trend = self.svc.monthly_trend(self.admin["family_id"], 6)
        self.assertEqual(len(trend), 6)
        self.assertEqual(trend[-1]["expense_cents"], 100_000)

    def test_month_bounds(self):
        start, end = month_bounds(2026, 2)
        self.assertEqual(start, date(2026, 2, 1))
        self.assertEqual(end, date(2026, 2, 28))


class TestAdminActions(BaseCase):
    def test_role_change_and_last_admin_protection(self):
        family = self.svc.get_family(self.admin["family_id"])
        member = self.svc.join_family(family["invite_code"], "Aigerim", "aigerim@test.kz", "Secret123")
        self.svc.set_member_role(self.admin, member["id"], "admin")
        self.assertEqual(self.svc.get_user(member["id"])["role"], "admin")

        with self.assertRaises(AccessDenied):
            self.svc.set_member_role(self.admin, self.admin["id"], "member")
        with self.assertRaises(AccessDenied):
            self.svc.set_member_active(self.admin, self.admin["id"], False)

    def test_deactivated_member_cannot_write_with_a_stale_object(self):
        """TC-T-29 from Abu's suite: the service must re-read is_active, not trust the caller."""
        family = self.svc.get_family(self.admin["family_id"])
        member = self.svc.join_family(family["invite_code"], "Aigerim", "aigerim@test.kz", "Secret123")
        self.svc.set_member_active(self.admin, member["id"], False)
        # `member` still says is_active = 1; only the database knows the truth.
        self.assertEqual(int(member["is_active"]), 1)
        with self.assertRaises(AccessDenied):
            self.svc.add_transaction(member, "expense", 100, self.cats["Food"]["id"], date.today())
        self.assertEqual(self.svc.list_transactions(self.admin["family_id"]), [])

    def test_set_limit_and_archive(self):
        self.svc.set_category_limit(self.admin, self.cats["Food"]["id"], 200_000)
        food = next(c for c in self.svc.list_categories(self.admin["family_id"]) if c["name"] == "Food")
        self.assertEqual(food["monthly_limit_cents"], 20_000_000)
        self.svc.archive_category(self.admin, self.cats["Food"]["id"])
        self.assertNotIn("Food", [c["name"] for c in self.svc.list_categories(self.admin["family_id"])])


class TestPresentation(unittest.TestCase):
    def test_budget_bar_escapes_user_input(self):
        rows = [
            {
                "name": "<script>alert(1)</script>",
                "limit_cents": 100_000,
                "spent_cents": 50_000,
                "remaining_cents": 50_000,
                "percent": 50.0,
                "status": "ok",
            }
        ]
        markup = budget_rows_html(rows)
        self.assertNotIn("<script>", markup)
        self.assertIn("&lt;script&gt;", markup)
        self.assertIn("width:50.0%", markup)
        self.assertIn("fill-ok", markup)

    def test_budget_bar_over_limit(self):
        rows = [
            {
                "name": "Food",
                "limit_cents": 100_000,
                "spent_cents": 120_000,
                "remaining_cents": -20_000,
                "percent": 120.0,
                "status": "over",
            }
        ]
        markup = budget_rows_html(rows)
        self.assertIn("fill-over", markup)
        self.assertIn("width:100.0%", markup)
        self.assertIn("Over by 200.00 KZT", markup)

    def test_budget_bar_without_limit(self):
        rows = [
            {
                "name": "Other",
                "limit_cents": None,
                "spent_cents": 5_000,
                "remaining_cents": None,
                "percent": None,
                "status": "no_limit",
            }
        ]
        markup = budget_rows_html(rows)
        self.assertIn("No monthly limit set", markup)
        self.assertIn("width:0.0%", markup)

    def test_trend_without_data_does_not_crash(self):
        markup = trend_html([])
        self.assertIn("trend-plot", markup)

    def test_trend_scales_to_the_peak(self):
        trend = [
            {"label": "Oct 2026", "short_label": "Oct", "income_cents": 600_000, "expense_cents": 300_000},
            {"label": "Nov 2026", "short_label": "Nov", "income_cents": 300_000, "expense_cents": 150_000},
        ]
        markup = trend_html(trend)
        self.assertIn("height:100.0%", markup)
        self.assertIn("height:50.0%", markup)


class TestExport(unittest.TestCase):
    def test_csv_has_header_and_rows(self):
        rows = [
            {
                "code": "TX-000001",
                "occurred_on": date(2026, 10, 10),
                "kind": "expense",
                "category": "Food",
                "member": "Arman",
                "amount_cents": 250_050,
                "note": "Магнум",
            }
        ]
        payload = transactions_to_csv(rows)
        text = payload.decode("utf-8-sig")
        lines = text.strip().splitlines()
        self.assertEqual(lines[0], "Transaction ID,Date,Type,Category,Member,Amount,Note")
        self.assertEqual(len(lines), 2)
        self.assertIn("TX-000001,2026-10-10,expense,Food,Arman,2500.50", lines[1])
        self.assertIn("Магнум", lines[1])

    def test_csv_of_empty_selection(self):
        text = transactions_to_csv([]).decode("utf-8-sig").strip().splitlines()
        self.assertEqual(len(text), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
