"""HTML fragments for the dashboard (kept out of app.py so they can be tested).

Only the small visual parts that need custom markup live here: budget progress
bars and the six-month income/expense chart. Everything is escaped, because
category names and notes are typed by users.
"""

from __future__ import annotations

import html
from typing import Any

from .validators import format_money

STATUS_CLASS = {"ok": "fill-ok", "warning": "fill-warning", "over": "fill-over"}


def budget_rows_html(rows: list[dict[str, Any]], currency: str = "KZT") -> str:
    blocks: list[str] = []
    for row in rows:
        if row["limit_cents"]:
            percent = row["percent"] or 0
            width = min(percent, 100)
            css = STATUS_CLASS.get(row["status"], "fill-ok")
            right = f'{format_money(row["spent_cents"], currency)} / {format_money(row["limit_cents"], currency)}'
            if row["remaining_cents"] is not None and row["remaining_cents"] < 0:
                note = f'Over by {format_money(abs(row["remaining_cents"]), currency)}'
            else:
                note = f'{format_money(row["remaining_cents"] or 0, currency)} left · {percent:.0f}% used'
        else:
            width = 0
            css = "fill-ok"
            right = format_money(row["spent_cents"], currency)
            note = "No monthly limit set"
        blocks.append(
            '<div class="budget-head">'
            f'<span>{html.escape(str(row["name"]))}</span><span>{html.escape(right)}</span></div>'
            f'<div class="budget-track"><div class="budget-fill {css}" style="width:{width:.1f}%"></div></div>'
            f'<div class="budget-note">{html.escape(note)}</div>'
        )
    return "".join(blocks)


def trend_html(trend: list[dict[str, Any]], currency: str = "KZT") -> str:
    peak = max((max(row["income_cents"], row["expense_cents"]) for row in trend), default=0) or 1
    columns: list[str] = []
    for row in trend:
        income_height = row["income_cents"] / peak * 100
        expense_height = row["expense_cents"] / peak * 100
        tooltip = (
            f'{row["label"]}: income {format_money(row["income_cents"], currency)}, '
            f'expenses {format_money(row["expense_cents"], currency)}'
        )
        columns.append(
            f'<div class="trend-col" title="{html.escape(tooltip)}">'
            '<div class="trend-bars">'
            f'<div class="trend-bar income" style="height:{income_height:.1f}%"></div>'
            f'<div class="trend-bar expense" style="height:{expense_height:.1f}%"></div>'
            "</div>"
            f'<div class="trend-label">{html.escape(str(row["short_label"]))}</div>'
            "</div>"
        )
    return (
        '<div class="trend-plot">' + "".join(columns) + "</div>"
        '<div class="trend-legend">'
        '<span><span class="legend-dot" style="background:#0F766E"></span>Income</span>'
        '<span><span class="legend-dot" style="background:#F04438"></span>Expenses</span>'
        "</div>"
    )
