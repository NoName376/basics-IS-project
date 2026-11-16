"""Monthly report for the dashboard, downloadable as CSV.

One click on the dashboard produces a small report with the totals, the budget
bars and the category table of the selected month. CSV opens in Excel and uses
UTF-8 with a byte-order mark, so Cyrillic notes are readable.
"""

from __future__ import annotations

import csv
import io
from typing import Any

STATUS_TEXT = {
    "ok": "within limit",
    "warning": "80% reached",
    "over": "over limit",
    "no_limit": "no limit",
}


def monthly_report_csv(
    summary: dict[str, Any],
    budgets: list[dict[str, Any]],
    currency: str = "KZT",
) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer)

    writer.writerow(["Family Budget Tracker — monthly report"])
    writer.writerow(["Month", summary["label"]])
    writer.writerow(["Income, " + currency, f'{summary["income_cents"] / 100:.2f}'])
    writer.writerow(["Expenses, " + currency, f'{summary["expense_cents"] / 100:.2f}'])
    writer.writerow(["Balance, " + currency, f'{summary["balance_cents"] / 100:.2f}'])
    rate = summary.get("savings_rate")
    writer.writerow(["Savings rate", "—" if rate is None else f"{rate * 100:.1f}%"])
    writer.writerow(["Transactions", summary.get("transaction_count", 0)])
    writer.writerow([])

    writer.writerow(["Category", f"Limit, {currency}", f"Spent, {currency}", f"Left, {currency}", "Used %", "Status"])
    for row in budgets:
        limit = row["limit_cents"]
        percent = row["percent"]
        writer.writerow(
            [
                row["name"],
                "" if limit is None else f"{limit / 100:.2f}",
                f'{row["spent_cents"] / 100:.2f}',
                "" if row["remaining_cents"] is None else f'{row["remaining_cents"] / 100:.2f}',
                "" if percent is None else f"{percent:.0f}%",
                STATUS_TEXT.get(row["status"], row["status"]),
            ]
        )

    return buffer.getvalue().encode("utf-8-sig")
