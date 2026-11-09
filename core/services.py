"""Business logic of the Family Budget Tracker.

The user interface never talks to SQL directly: every rule (who may do what,
which amount is valid, how the balance is calculated) lives here, so it can be
tested without a browser and reused by any future client.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Iterable, Sequence

from . import security
from .db import Database
from .validators import (
    ValidationError,
    add_months,
    clean_text,
    format_money,
    month_bounds,
    parse_amount,
    parse_date,
)

# Whole tenge per month; converted to cents when the family is created.
DEFAULT_CATEGORIES: list[tuple[str, str, int | None]] = [
    ("Food", "expense", 150_000),
    ("Transport", "expense", 60_000),
    ("Housing & utilities", "expense", 200_000),
    ("Health", "expense", 40_000),
    ("Education", "expense", 50_000),
    ("Entertainment", "expense", 40_000),
    ("Shopping", "expense", 80_000),
    ("Other", "expense", 30_000),
    ("Salary", "income", None),
    ("Freelance", "income", None),
    ("Gift", "income", None),
    ("Other income", "income", None),
]

BUDGET_WARNING_PERCENT = 80
VALID_ROLES = ("admin", "member")


class AppError(Exception):
    """Base class for expected, user-facing errors."""


class ConflictError(AppError):
    pass


class AuthError(AppError):
    pass


class AccessDenied(AppError):
    pass


class NotFound(AppError):
    pass


def _as_date(value: Any) -> date:
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _public_user(row: dict[str, Any]) -> dict[str, Any]:
    """Strip the password hash before a user object leaves the service layer."""
    user = dict(row)
    user.pop("password_hash", None)
    return user


class BudgetService:
    def __init__(self, db: Database, currency: str = "KZT") -> None:
        self.db = db
        self.currency = currency

    # ------------------------------------------------------------------ setup
    def ensure_default_categories(self, family_id: int) -> None:
        for name, kind, limit_tenge in DEFAULT_CATEGORIES:
            exists = self.db.query_one(
                "SELECT id FROM categories WHERE family_id = ? AND name = ? AND kind = ?",
                (family_id, name, kind),
            )
            if exists:
                continue
            self.db.insert(
                "INSERT INTO categories (family_id, name, kind, monthly_limit_cents) VALUES (?, ?, ?, ?)",
                (family_id, name, kind, None if limit_tenge is None else limit_tenge * 100),
            )

    # ------------------------------------------------------------------- auth
    def register_family(
        self,
        family_name: str,
        full_name: str,
        email: str,
        password: str,
    ) -> dict[str, Any]:
        family_name = clean_text(family_name, field="family_name", max_length=80)
        full_name = clean_text(full_name, field="full_name", max_length=80)
        email = self._check_identity(email, password)

        if self.db.query_one("SELECT id FROM users WHERE email = ?", (email,)):
            raise ConflictError("An account with this e-mail already exists. Please sign in instead.")

        family_id = self.db.insert(
            "INSERT INTO families (name, invite_code, currency) VALUES (?, ?, ?)",
            (family_name, security.generate_invite_code(), self.currency),
        )
        user_id = self.db.insert(
            "INSERT INTO users (family_id, full_name, email, password_hash, role) "
            "VALUES (?, ?, ?, ?, 'admin')",
            (family_id, full_name, email, security.hash_password(password)),
        )
        self.ensure_default_categories(family_id)
        return _public_user(self.db.query_one("SELECT * FROM users WHERE id = ?", (user_id,)) or {})

    def join_family(
        self,
        invite_code: str,
        full_name: str,
        email: str,
        password: str,
    ) -> dict[str, Any]:
        code = clean_text(invite_code, field="invite_code", max_length=12).upper()
        full_name = clean_text(full_name, field="full_name", max_length=80)
        email = self._check_identity(email, password)

        family = self.db.query_one("SELECT * FROM families WHERE UPPER(invite_code) = ?", (code,))
        if not family:
            raise ValidationError("This invite code does not exist.", "invite_code")
        if self.db.query_one("SELECT id FROM users WHERE email = ?", (email,)):
            raise ConflictError("An account with this e-mail already exists. Please sign in instead.")

        user_id = self.db.insert(
            "INSERT INTO users (family_id, full_name, email, password_hash, role) "
            "VALUES (?, ?, ?, ?, 'member')",
            (family["id"], full_name, email, security.hash_password(password)),
        )
        return _public_user(self.db.query_one("SELECT * FROM users WHERE id = ?", (user_id,)) or {})

    def _check_identity(self, email: str, password: str) -> str:
        email = security.normalize_email(email)
        if not security.is_valid_email(email):
            raise ValidationError("Enter a valid e-mail address, e.g. name@mail.com.", "email")
        problems = security.password_problems(password)
        if problems:
            raise ValidationError(" ".join(problems), "password")
        return email

    def authenticate(self, email: str, password: str) -> dict[str, Any]:
        email = security.normalize_email(email)
        row = self.db.query_one("SELECT * FROM users WHERE email = ?", (email,))
        # Always run a hash comparison so a wrong e-mail and a wrong password
        # take the same time (protection against user enumeration).
        stored = row["password_hash"] if row else security.hash_password("dummy-value")
        ok = security.verify_password(password, stored)
        if not row or not ok:
            raise AuthError("Wrong e-mail or password.")
        if not int(row.get("is_active", 1)):
            raise AuthError("This account has been deactivated. Ask the family admin.")
        return _public_user(row)

    def get_user(self, user_id: int) -> dict[str, Any]:
        row = self.db.query_one("SELECT * FROM users WHERE id = ?", (user_id,))
        if not row:
            raise NotFound("User not found.")
        return _public_user(row)

    def get_family(self, family_id: int) -> dict[str, Any]:
        row = self.db.query_one("SELECT * FROM families WHERE id = ?", (family_id,))
        if not row:
            raise NotFound("Family not found.")
        return dict(row)

    # ------------------------------------------------------------------- role
    def _fresh(self, actor: dict[str, Any]) -> dict[str, Any]:
        """Re-read the actor from the database before a write.

        A caller may hold a user object obtained earlier (a session dict, a test
        fixture). Trusting it would let a deactivated member keep writing, so
        the role and the active flag always come from the database.
        """
        row = self.db.query_one(
            "SELECT id, family_id, role, is_active, full_name FROM users WHERE id = ?",
            (int(actor["id"]),),
        )
        if not row:
            raise AccessDenied("This account no longer exists.")
        if not int(row["is_active"]):
            raise AccessDenied("This account has been deactivated. Ask the family admin.")
        return dict(row)

    def _require_admin(self, actor: dict[str, Any]) -> dict[str, Any]:
        fresh = self._fresh(actor)
        if fresh["role"] != "admin":
            raise AccessDenied("Only the family admin can do this.")
        return fresh

    def list_members(self, family_id: int) -> list[dict[str, Any]]:
        rows = self.db.query(
            "SELECT id, full_name, email, role, is_active, created_at FROM users "
            "WHERE family_id = ? ORDER BY role, full_name",
            (family_id,),
        )
        return [dict(r) for r in rows]

    def set_member_role(self, actor: dict[str, Any], user_id: int, role: str) -> None:
        actor = self._require_admin(actor)
        if role not in VALID_ROLES:
            raise ValidationError("Unknown role.", "role")
        if int(user_id) == int(actor["id"]) and role != "admin":
            raise AccessDenied("You cannot remove your own admin role. Ask another admin first.")
        target = self.db.query_one("SELECT * FROM users WHERE id = ? AND family_id = ?", (user_id, actor["family_id"]))
        if not target:
            raise NotFound("Member not found in your family.")
        self.db.execute("UPDATE users SET role = ? WHERE id = ?", (role, user_id))

    def set_member_active(self, actor: dict[str, Any], user_id: int, active: bool) -> None:
        actor = self._require_admin(actor)
        if int(user_id) == int(actor["id"]):
            raise AccessDenied("You cannot deactivate your own account.")
        target = self.db.query_one("SELECT * FROM users WHERE id = ? AND family_id = ?", (user_id, actor["family_id"]))
        if not target:
            raise NotFound("Member not found in your family.")
        if not active:
            admins = self.db.scalar(
                "SELECT COUNT(*) FROM users WHERE family_id = ? AND role = 'admin' AND is_active = 1",
                (actor["family_id"],),
                default=0,
            )
            if target["role"] == "admin" and int(admins) <= 1:
                raise AccessDenied("The family must keep at least one active admin.")
        self.db.execute("UPDATE users SET is_active = ? WHERE id = ?", (1 if active else 0, user_id))

    # ------------------------------------------------------------ categories
    def list_categories(self, family_id: int, kind: str | None = None, include_archived: bool = False) -> list[dict[str, Any]]:
        sql = "SELECT * FROM categories WHERE family_id = ?"
        params: list[Any] = [family_id]
        if kind:
            sql += " AND kind = ?"
            params.append(kind)
        if not include_archived:
            sql += " AND is_active = 1"
        sql += " ORDER BY kind, name"
        return [dict(r) for r in self.db.query(sql, params)]

    def create_category(
        self,
        actor: dict[str, Any],
        name: str,
        kind: str,
        monthly_limit: str | None = None,
    ) -> int:
        actor = self._require_admin(actor)
        name = clean_text(name, field="name", max_length=40)
        if kind not in ("expense", "income"):
            raise ValidationError("Category type must be expense or income.", "kind")
        if self.db.query_one(
            "SELECT id FROM categories WHERE family_id = ? AND name = ? AND kind = ?",
            (actor["family_id"], name, kind),
        ):
            raise ConflictError(f'Category "{name}" already exists.')
        limit_cents = None
        if kind == "expense" and monthly_limit not in (None, ""):
            limit_cents = parse_amount(monthly_limit, field="monthly_limit")
        return self.db.insert(
            "INSERT INTO categories (family_id, name, kind, monthly_limit_cents) VALUES (?, ?, ?, ?)",
            (actor["family_id"], name, kind, limit_cents),
        )

    def set_category_limit(self, actor: dict[str, Any], category_id: int, monthly_limit: str | None) -> None:
        actor = self._require_admin(actor)
        category = self.db.query_one(
            "SELECT * FROM categories WHERE id = ? AND family_id = ?", (category_id, actor["family_id"])
        )
        if not category:
            raise NotFound("Category not found.")
        if category["kind"] != "expense":
            raise ValidationError("Only expense categories can have a monthly limit.", "monthly_limit")
        limit_cents = None
        if monthly_limit not in (None, ""):
            limit_cents = parse_amount(monthly_limit, field="monthly_limit")
        self.db.execute("UPDATE categories SET monthly_limit_cents = ? WHERE id = ?", (limit_cents, category_id))

    def archive_category(self, actor: dict[str, Any], category_id: int) -> None:
        actor = self._require_admin(actor)
        category = self.db.query_one(
            "SELECT * FROM categories WHERE id = ? AND family_id = ?", (category_id, actor["family_id"])
        )
        if not category:
            raise NotFound("Category not found.")
        used = self.db.scalar("SELECT COUNT(*) FROM transactions WHERE category_id = ?", (category_id,), default=0)
        if used:
            # Keep history readable: hide the category instead of deleting it.
            self.db.execute("UPDATE categories SET is_active = 0 WHERE id = ?", (category_id,))
        else:
            self.db.execute("DELETE FROM categories WHERE id = ?", (category_id,))

    # ------------------------------------------------------------ transactions
    def add_transaction(
        self,
        actor: dict[str, Any],
        kind: str,
        amount: str | float,
        category_id: int,
        occurred_on: str | date,
        note: str | None = "",
    ) -> int:
        if kind not in ("expense", "income"):
            raise ValidationError("Choose expense or income.", "kind")
        actor = self._fresh(actor)
        amount_cents = parse_amount(amount)
        day = parse_date(occurred_on)
        note = clean_text(note, field="note", max_length=280, required=False)

        category = self.db.query_one(
            "SELECT * FROM categories WHERE id = ? AND family_id = ? AND is_active = 1",
            (category_id, actor["family_id"]),
        )
        if not category:
            raise ValidationError("Choose a category from your family list.", "category_id")
        if category["kind"] != kind:
            article = "an" if category["kind"] == "income" else "a"
            raise ValidationError(
                f'"{category["name"]}" is {article} {category["kind"]} category, not {kind}.', "category_id"
            )

        return self.db.insert(
            "INSERT INTO transactions (family_id, user_id, category_id, kind, amount_cents, occurred_on, note) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (actor["family_id"], actor["id"], category_id, kind, amount_cents, day.isoformat(), note),
        )

    def delete_transaction(self, actor: dict[str, Any], transaction_id: int) -> None:
        actor = self._fresh(actor)
        row = self.db.query_one(
            "SELECT * FROM transactions WHERE id = ? AND family_id = ?",
            (transaction_id, actor["family_id"]),
        )
        if not row:
            raise NotFound("Transaction not found.")
        if actor.get("role") != "admin" and int(row["user_id"]) != int(actor["id"]):
            raise AccessDenied("You can delete only your own transactions.")
        self.db.execute("DELETE FROM transactions WHERE id = ?", (transaction_id,))

    def list_transactions(
        self,
        family_id: int,
        *,
        start: date | None = None,
        end: date | None = None,
        kind: str | None = None,
        category_id: int | None = None,
        search: str | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        sql = [
            "SELECT t.id, t.kind, t.amount_cents, t.occurred_on, t.note, t.created_at,",
            "       c.name AS category, c.id AS category_id,",
            "       u.full_name AS member, u.id AS user_id",
            "FROM transactions t",
            "JOIN categories c ON c.id = t.category_id",
            "JOIN users u ON u.id = t.user_id",
            "WHERE t.family_id = ?",
        ]
        params: list[Any] = [family_id]
        if start:
            sql.append("AND t.occurred_on >= ?")
            params.append(start.isoformat())
        if end:
            sql.append("AND t.occurred_on <= ?")
            params.append(end.isoformat())
        if kind in ("expense", "income"):
            sql.append("AND t.kind = ?")
            params.append(kind)
        if category_id:
            sql.append("AND t.category_id = ?")
            params.append(category_id)
        if search:
            sql.append("AND (LOWER(t.note) LIKE ? OR LOWER(c.name) LIKE ?)")
            needle = f"%{search.strip().lower()}%"
            params.extend([needle, needle])
        sql.append("ORDER BY t.occurred_on DESC, t.id DESC")
        sql.append("LIMIT ?")
        params.append(int(limit))

        rows = self.db.query(" ".join(sql), params)
        for row in rows:
            row["amount_cents"] = int(row["amount_cents"])
            row["occurred_on"] = _as_date(row["occurred_on"])
            # Human-readable transaction ID from the Task 7 data dictionary
            # (format TX001). It is derived from the primary key, so it cannot
            # repeat and no user input is needed to make it unique.
            row["code"] = f"TX-{int(row['id']):06d}"
        return rows

    # --------------------------------------------------------------- analytics
    def month_summary(self, family_id: int, year: int, month: int) -> dict[str, Any]:
        start, end = month_bounds(year, month)
        rows = self.db.query(
            "SELECT kind, SUM(amount_cents) AS total, COUNT(*) AS cnt FROM transactions "
            "WHERE family_id = ? AND occurred_on BETWEEN ? AND ? GROUP BY kind",
            (family_id, start.isoformat(), end.isoformat()),
        )
        totals = {row["kind"]: int(row["total"]) for row in rows}
        count = sum(int(row["cnt"]) for row in rows)
        income = totals.get("income", 0)
        expense = totals.get("expense", 0)

        prev_year, prev_month = add_months(year, month, -1)
        prev_start, prev_end = month_bounds(prev_year, prev_month)
        prev_rows = self.db.query(
            "SELECT kind, SUM(amount_cents) AS total FROM transactions "
            "WHERE family_id = ? AND occurred_on BETWEEN ? AND ? GROUP BY kind",
            (family_id, prev_start.isoformat(), prev_end.isoformat()),
        )
        prev = {row["kind"]: int(row["total"]) for row in prev_rows}

        return {
            "year": year,
            "month": month,
            "label": f"{start:%B %Y}",
            "start": start,
            "end": end,
            "income_cents": income,
            "expense_cents": expense,
            "balance_cents": income - expense,
            "savings_rate": (income - expense) / income if income else None,
            "transaction_count": count,
            "prev_income_cents": prev.get("income", 0),
            "prev_expense_cents": prev.get("expense", 0),
        }

    def budget_status(self, family_id: int, year: int, month: int) -> list[dict[str, Any]]:
        start, end = month_bounds(year, month)
        rows = self.db.query(
            "SELECT c.id, c.name, c.monthly_limit_cents,"
            "       COALESCE(SUM(t.amount_cents), 0) AS spent_cents,"
            "       COUNT(t.id) AS tx_count "
            "FROM categories c "
            "LEFT JOIN transactions t ON t.category_id = c.id AND t.occurred_on BETWEEN ? AND ? "
            "WHERE c.family_id = ? AND c.kind = 'expense' AND c.is_active = 1 "
            "GROUP BY c.id, c.name, c.monthly_limit_cents "
            "ORDER BY spent_cents DESC, c.name",
            (start.isoformat(), end.isoformat(), family_id),
        )
        result = []
        for row in rows:
            spent = int(row["spent_cents"])
            limit = int(row["monthly_limit_cents"]) if row["monthly_limit_cents"] is not None else None
            percent = (spent / limit * 100) if limit else None
            if limit is None:
                status = "no_limit"
            elif spent >= limit:
                status = "over"
            elif spent >= limit * BUDGET_WARNING_PERCENT / 100:
                status = "warning"
            else:
                status = "ok"
            result.append(
                {
                    "id": row["id"],
                    "name": row["name"],
                    "limit_cents": limit,
                    "spent_cents": spent,
                    "remaining_cents": (limit - spent) if limit is not None else None,
                    "percent": percent,
                    "status": status,
                    "tx_count": int(row["tx_count"]),
                }
            )
        return result

    def monthly_trend(self, family_id: int, months: int = 6, today: date | None = None) -> list[dict[str, Any]]:
        today = today or date.today()
        first_year, first_month = add_months(today.year, today.month, -(months - 1))
        start, _ = month_bounds(first_year, first_month)
        rows = self.db.query(
            "SELECT kind, amount_cents, occurred_on FROM transactions "
            "WHERE family_id = ? AND occurred_on >= ?",
            (family_id, start.isoformat()),
        )
        buckets: dict[tuple[int, int], dict[str, int]] = {}
        for offset in range(months):
            y, m = add_months(first_year, first_month, offset)
            buckets[(y, m)] = {"income": 0, "expense": 0}
        for row in rows:
            day = _as_date(row["occurred_on"])
            key = (day.year, day.month)
            if key in buckets:
                buckets[key][row["kind"]] += int(row["amount_cents"])
        trend = []
        for (y, m), totals in buckets.items():
            trend.append(
                {
                    "year": y,
                    "month": m,
                    "label": f"{date(y, m, 1):%b %Y}",
                    "short_label": f"{date(y, m, 1):%b}",
                    "income_cents": totals["income"],
                    "expense_cents": totals["expense"],
                    "balance_cents": totals["income"] - totals["expense"],
                }
            )
        return trend

    def category_breakdown(self, family_id: int, year: int, month: int) -> list[dict[str, Any]]:
        start, end = month_bounds(year, month)
        rows = self.db.query(
            "SELECT c.name, c.kind, SUM(t.amount_cents) AS total, COUNT(*) AS cnt "
            "FROM transactions t JOIN categories c ON c.id = t.category_id "
            "WHERE t.family_id = ? AND t.occurred_on BETWEEN ? AND ? "
            "GROUP BY c.name, c.kind ORDER BY total DESC",
            (family_id, start.isoformat(), end.isoformat()),
        )
        return [
            {"name": r["name"], "kind": r["kind"], "total_cents": int(r["total"]), "count": int(r["cnt"])}
            for r in rows
        ]

    def lifetime_balance(self, family_id: int) -> dict[str, int]:
        rows = self.db.query(
            "SELECT kind, SUM(amount_cents) AS total FROM transactions WHERE family_id = ? GROUP BY kind",
            (family_id,),
        )
        totals = {r["kind"]: int(r["total"]) for r in rows}
        income = totals.get("income", 0)
        expense = totals.get("expense", 0)
        return {"income_cents": income, "expense_cents": expense, "balance_cents": income - expense}

    # ------------------------------------------------------------------ helper
    def format(self, cents: int | None) -> str:
        return format_money(cents, self.currency)
