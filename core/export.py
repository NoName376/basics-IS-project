"""CSV export used by the History screen.

Kept outside the user interface so it can be unit-tested without Streamlit.
"""

from __future__ import annotations

import csv
import io
from typing import Any

HEADER = ["Transaction ID", "Date", "Type", "Category", "Member", "Amount", "Note"]


def transactions_to_csv(rows: list[dict[str, Any]]) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(HEADER)
    for row in rows:
        writer.writerow(
            [
                row.get("code", ""),
                row["occurred_on"].isoformat(),
                row["kind"],
                row["category"],
                row["member"],
                f'{row["amount_cents"] / 100:.2f}',
                row["note"],
            ]
        )
    # utf-8-sig so Excel opens Kazakh and Russian notes correctly.
    return buffer.getvalue().encode("utf-8-sig")
