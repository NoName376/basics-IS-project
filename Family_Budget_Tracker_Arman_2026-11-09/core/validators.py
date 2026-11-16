"""Input validation and money helpers.

Every value that reaches the database passes through these functions, so the
business rules from the requirements document are enforced in one place instead
of being duplicated inside the user interface.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

MAX_AMOUNT = Decimal("1000000000")  # 1 000 000 000.00
OLDEST_YEARS = 10
_CLEAN_RE = re.compile(r"[\s\u00a0]")


class ValidationError(ValueError):
    """A user-facing validation failure bound to a form field."""

    def __init__(self, message: str, field: str = "form") -> None:
        super().__init__(message)
        self.message = message
        self.field = field


def parse_amount(raw: str | float | int | Decimal, *, field: str = "amount") -> int:
    """Convert user input to integer cents, rejecting zero, negatives and junk."""
    if isinstance(raw, bool):  # bool is an int subclass - never a valid amount
        raise ValidationError("Enter a number, for example 2500.00", field)
    if isinstance(raw, Decimal):
        value = raw
    else:
        text = str(raw or "").strip()
        text = _CLEAN_RE.sub("", text).replace(",", ".")
        text = text.replace("₸", "").replace("$", "").replace("€", "")
        if not text:
            raise ValidationError("Amount is required.", field)
        if not re.fullmatch(r"\d+(\.\d{1,2})?", text):
            raise ValidationError("Amount must be a positive number with up to 2 decimals, e.g. 2500.00", field)
        try:
            value = Decimal(text)
        except InvalidOperation as exc:
            raise ValidationError("Amount must be a number.", field) from exc

    if value <= 0:
        raise ValidationError("Amount must be greater than zero.", field)
    if value > MAX_AMOUNT:
        raise ValidationError("Amount is too large.", field)
    return int((value * 100).quantize(Decimal("1")))


def parse_date(raw: str | date | datetime, *, today: date | None = None, field: str = "occurred_on") -> date:
    """Parse YYYY-MM-DD and reject future dates and dates older than 10 years."""
    today = today or date.today()
    if isinstance(raw, datetime):
        value = raw.date()
    elif isinstance(raw, date):
        value = raw
    else:
        text = str(raw or "").strip()
        if not text:
            raise ValidationError("Date is required.", field)
        try:
            value = datetime.strptime(text, "%Y-%m-%d").date()
        except ValueError as exc:
            raise ValidationError("Use the format YYYY-MM-DD, e.g. 2026-10-10.", field) from exc

    if value > today:
        raise ValidationError("The date cannot be in the future.", field)
    if value < today - timedelta(days=365 * OLDEST_YEARS):
        raise ValidationError("The date is too far in the past.", field)
    return value


def clean_text(raw: str | None, *, field: str, max_length: int, required: bool = True) -> str:
    text = " ".join((raw or "").split())
    if required and not text:
        raise ValidationError("This field is required.", field)
    if len(text) > max_length:
        raise ValidationError(f"Use at most {max_length} characters.", field)
    return text


def month_bounds(year: int, month: int) -> tuple[date, date]:
    start = date(year, month, 1)
    end = date(year + (month == 12), month % 12 + 1, 1) - timedelta(days=1)
    return start, end


def add_months(year: int, month: int, delta: int) -> tuple[int, int]:
    index = (year * 12 + (month - 1)) + delta
    return index // 12, index % 12 + 1


def format_money(cents: int | None, currency: str = "KZT") -> str:
    """Format integer cents as '12 345.00 KZT' with a non-breaking thin space."""
    if cents is None:
        return "—"
    sign = "-" if cents < 0 else ""
    whole, rest = divmod(abs(int(cents)), 100)
    grouped = f"{whole:,}".replace(",", " ")
    return f"{sign}{grouped}.{rest:02d} {currency}"
