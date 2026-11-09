"""Family Budget Tracker - web application (Streamlit).

Information Systems team project, Team 38.
Application & Development: Akhmetshiev Arman (24B030051).

Run locally:
    streamlit run app.py
With PostgreSQL:
    set DATABASE_URL=postgresql://budget_user:password@localhost:5432/family_budget
"""

from __future__ import annotations

import html
from datetime import date
from typing import Any

import pandas as pd
import streamlit as st

from core.config import load_settings
from core.db import Database
from core.export import transactions_to_csv
from core.presentation import budget_rows_html, trend_html
from receipt_feature.service import (
    ReceiptError, attach_receipt, delete_receipt, list_receipts, read_receipt,
)
from core.services import (
    AccessDenied,
    AuthError,
    BudgetService,
    ConflictError,
    NotFound,
)
from core.validators import ValidationError, add_months, format_money, month_bounds

settings = load_settings()

PAGE_ICON = "💰"
NAV_ITEMS = [
    "Dashboard",
    "Add transaction",
    "History",
    "Categories & budgets",
    "Family members",
]

CSS = """
<style>
:root {
    --fbt-ink: #101828;
    --fbt-muted: #667085;
    --fbt-line: #E4E7EC;
    --fbt-brand: #0F766E;
}
.block-container {padding-top: 2.2rem; padding-bottom: 3rem; max-width: 1180px;}
h1, h2, h3 {letter-spacing: -0.02em; color: var(--fbt-ink);}
[data-testid="stMetric"] {
    background: #FFFFFF;
    border: 1px solid var(--fbt-line);
    border-radius: 14px;
    padding: 16px 18px 12px 18px;
    box-shadow: 0 1px 2px rgba(16, 24, 40, .04);
}
[data-testid="stMetricLabel"] p {color: var(--fbt-muted); font-size: .82rem; letter-spacing: .02em;}
[data-testid="stMetricValue"] {font-size: 1.55rem;}
.fbt-hero {
    background: linear-gradient(135deg, #0F766E 0%, #115E59 55%, #134E4A 100%);
    color: #FFFFFF; border-radius: 22px; padding: 34px 34px 30px 34px;
    box-shadow: 0 18px 40px -18px rgba(15, 118, 110, .55);
}
.fbt-hero h1 {color: #FFFFFF; font-size: 2.05rem; margin: 0 0 .4rem 0;}
.fbt-hero p {color: #CCFBF1; margin: 0; font-size: .98rem; line-height: 1.55;}
.fbt-pill {
    display: inline-block; background: rgba(255,255,255,.14); border: 1px solid rgba(255,255,255,.25);
    color: #F0FDFA; border-radius: 999px; padding: 4px 12px; font-size: .74rem;
    letter-spacing: .06em; text-transform: uppercase; margin-bottom: 16px;
}
.fbt-sub {color: var(--fbt-muted); font-size: .84rem; margin: 0 0 14px 0;}
.budget-head {display:flex; justify-content:space-between; font-size:.86rem; color:var(--fbt-ink); margin: 12px 0 5px 0;}
.budget-head span:last-child {color: var(--fbt-muted); font-variant-numeric: tabular-nums;}
.budget-track {background:#F2F4F7; border-radius:999px; height:9px; overflow:hidden;}
.budget-fill {height:100%; border-radius:999px;}
.fill-ok {background: #12B76A;}
.fill-warning {background: #F79009;}
.fill-over {background: #F04438;}
.budget-note {font-size:.76rem; color:var(--fbt-muted); margin-top:4px;}
.fbt-empty {border:1px dashed var(--fbt-line); border-radius:14px; padding:34px; text-align:center; color:var(--fbt-muted);}
[data-testid="stSidebar"] {background:#FCFCFD; border-right:1px solid var(--fbt-line);}
.fbt-brand {font-weight:700; font-size:1.02rem; color:var(--fbt-ink); letter-spacing:-.01em;}
.fbt-brand small {display:block; font-weight:500; color:var(--fbt-muted); font-size:.76rem; letter-spacing:.04em;}
.trend-plot {display:flex; align-items:flex-end; gap:10px; height:190px; padding-top:8px;}
.trend-col {flex:1; display:flex; flex-direction:column; align-items:center; height:100%;}
.trend-bars {flex:1; display:flex; align-items:flex-end; gap:4px; width:100%; justify-content:center;}
.trend-bar {width:15px; border-radius:4px 4px 0 0; min-height:2px;}
.trend-bar.income {background:#0F766E;}
.trend-bar.expense {background:#F04438;}
.trend-label {font-size:.72rem; color:#667085; margin-top:6px;}
.trend-legend {display:flex; gap:16px; font-size:.76rem; color:#667085; margin-top:10px;}
.legend-dot {width:9px;height:9px;border-radius:3px;display:inline-block;margin-right:5px;}
</style>
"""


# --------------------------------------------------------------------------- runtime
@st.cache_resource(show_spinner=False)
def get_runtime(database_url: str | None, sqlite_path: str, currency: str) -> tuple[Database, BudgetService]:
    db = Database(database_url, sqlite_path)
    db.init_schema()
    return db, BudgetService(db, currency)


def get_service() -> tuple[Database, BudgetService]:
    return get_runtime(settings.database_url, str(settings.sqlite_path), settings.currency)


# --------------------------------------------------------------------------- helpers
def money(cents: int | None) -> str:
    return format_money(cents, settings.currency)


def full_date(day: date) -> str:
    return day.strftime("%d %b %Y")


def flash(kind: str, message: str) -> None:
    st.session_state["flash"] = (kind, message)


def show_flash() -> None:
    payload = st.session_state.pop("flash", None)
    if not payload:
        return
    kind, message = payload
    {"success": st.success, "error": st.error, "warning": st.warning}.get(kind, st.info)(message)


def recent_months(count: int = 12) -> list[tuple[int, int, str]]:
    today = date.today()
    options = []
    for offset in range(count):
        year, month = add_months(today.year, today.month, -offset)
        options.append((year, month, f"{date(year, month, 1):%B %Y}"))
    return options


def month_picker(key: str, count: int = 12) -> tuple[int, int]:
    options = recent_months(count)
    labels = [label for _, _, label in options]
    index = st.selectbox("Month", list(range(len(options))), format_func=lambda i: labels[i], key=key)
    year, month, _ = options[index]
    return year, month


# --------------------------------------------------------------------------- auth screen
def render_auth(svc: BudgetService) -> None:
    left, right = st.columns([1.05, 0.95], gap="large")

    with left:
        st.markdown(
            f"""
            <div class="fbt-hero">
                <div class="fbt-pill">{html.escape(settings.team)} · Information Systems</div>
                <h1>Family Budget Tracker</h1>
                <p>One shared record of the family money: every income and expense is stored in a
                single database, and every member sees the same balance immediately.</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.write("")
        c1, c2, c3 = st.columns(3)
        c1.metric("Tables", "4")
        c2.metric("Roles", "2")
        c3.metric("Members", "5")
        st.caption(
            "Registration creates a private family workspace. Other members join with a six-character "
            "invite code, so no stranger can read your financial history."
        )

    with right:
        st.write("")
        tab_login, tab_register = st.tabs(["Sign in", "Create account"])

        with tab_login:
            with st.form("login_form"):
                st.subheader("Welcome back")
                email = st.text_input("E-mail", placeholder="name@mail.com")
                password = st.text_input("Password", type="password")
                submitted = st.form_submit_button("Sign in", type="primary", use_container_width=True)

            if submitted:
                locked_until = st.session_state.get("locked_until", 0)
                now = pd.Timestamp.now().timestamp()
                if locked_until and now < locked_until:
                    st.error(f"Too many failed attempts. Try again in {int(locked_until - now)} seconds.")
                else:
                    try:
                        user = svc.authenticate(email, password)
                    except (AuthError, ValidationError) as exc:
                        attempts = st.session_state.get("failed_attempts", 0) + 1
                        st.session_state["failed_attempts"] = attempts
                        if attempts >= settings.max_login_attempts:
                            st.session_state["locked_until"] = now + settings.lockout_seconds
                            st.session_state["failed_attempts"] = 0
                            st.error("Too many failed attempts. Sign-in is locked for one minute.")
                        else:
                            st.error(str(exc))
                    else:
                        st.session_state.update(
                            {"user": user, "page": NAV_ITEMS[0], "failed_attempts": 0, "locked_until": 0}
                        )
                        st.rerun()

        with tab_register:
            mode = st.radio(
                "How do you join?",
                ["Create a new family", "Join with an invite code"],
                horizontal=True,
                label_visibility="collapsed",
            )
            creating = mode == "Create a new family"
            with st.form("register_form"):
                st.subheader("New family account" if creating else "Join your family")
                family_name = st.text_input("Family name", placeholder="Akhmetshiev Family") if creating else ""
                invite_code = "" if creating else st.text_input("Invite code", placeholder="A7K2QX", max_chars=6)
                full_name = st.text_input("Your name", placeholder="Arman Akhmetshiev")
                email = st.text_input("E-mail", placeholder="name@mail.com")
                password = st.text_input(
                    "Password", type="password", help="At least 8 characters, one letter and one digit."
                )
                submitted = st.form_submit_button("Create account", type="primary", use_container_width=True)

            if submitted:
                try:
                    if creating:
                        user = svc.register_family(family_name, full_name, email, password)
                    else:
                        user = svc.join_family(invite_code, full_name, email, password)
                except (ValidationError, ConflictError) as exc:
                    st.error(str(exc))
                else:
                    st.session_state.update({"user": user, "page": NAV_ITEMS[0]})
                    st.rerun()

        st.caption(
            f"Database: {settings.backend}. Passwords are stored as salted PBKDF2 hashes, never as plain text."
        )


# --------------------------------------------------------------------------- app shell
def render_sidebar(svc: BudgetService, db: Database, user: dict[str, Any]) -> str:
    family = svc.get_family(user["family_id"])
    counts = db.query_one(
        "SELECT COUNT(*) AS n FROM transactions WHERE family_id = ?", (user["family_id"],)
    ) or {"n": 0}

    with st.sidebar:
        st.markdown(
            f'<div class="fbt-brand">💰 {html.escape(settings.app_name)}<small>{html.escape(settings.team)}</small></div>',
            unsafe_allow_html=True,
        )
        st.write("")
        st.markdown(f"**{html.escape(user['full_name'])}**")
        role_label = "Family admin" if user["role"] == "admin" else "Family member"
        st.caption(f"{role_label} · {html.escape(family['name'])}")

        page = st.radio("Navigation", NAV_ITEMS, key="page", label_visibility="collapsed")

        st.divider()
        st.caption(f"Backend: {db.label}")
        st.caption(f"Transactions stored: {int(counts['n'])}")
        if st.button("Sign out", use_container_width=True):
            # Clearing session_state while widgets exist raises in Streamlit,
            # so the request is handled at the top of the next run.
            st.session_state["logout_requested"] = True
            st.rerun()
    return page


def render_app(svc: BudgetService, db: Database, user: dict[str, Any]) -> None:
    page = render_sidebar(svc, db, user)
    show_flash()
    if page == "Dashboard":
        render_dashboard(svc, user)
    elif page == "Add transaction":
        render_add_transaction(svc, user)
    elif page == "History":
        render_history(svc, user)
    elif page == "Categories & budgets":
        render_categories(svc, user)
    elif page == "Family members":
        render_members(svc, user)


# --------------------------------------------------------------------------- dashboard
def render_dashboard(svc: BudgetService, user: dict[str, Any]) -> None:
    year, month = month_picker("dash_month")
    summary = svc.month_summary(user["family_id"], year, month)
    lifetime = svc.lifetime_balance(user["family_id"])
    budgets = svc.budget_status(user["family_id"], year, month)
    trend = svc.monthly_trend(user["family_id"], 6)

    first_name = user["full_name"].split()[0]
    st.markdown(f"## {summary['label']}")
    st.caption(f"Shared view for the whole family · signed in as {first_name}")

    c1, c2, c3, c4 = st.columns(4)
    income_delta = summary["income_cents"] - summary["prev_income_cents"]
    expense_delta = summary["expense_cents"] - summary["prev_expense_cents"]
    c1.metric("Income", money(summary["income_cents"]), f"{money(income_delta)} vs previous month")
    c2.metric(
        "Expenses",
        money(summary["expense_cents"]),
        f"{money(expense_delta)} vs previous month",
        delta_color="inverse",
    )
    c3.metric("Month balance", money(summary["balance_cents"]))
    rate = summary["savings_rate"]
    c4.metric("Savings rate", "—" if rate is None else f"{rate * 100:.0f}%")

    st.caption(
        f"All-time balance: {money(lifetime['balance_cents'])}  ·  "
        f"{summary['transaction_count']} transactions this month  ·  "
        f"income {money(lifetime['income_cents'])} / expenses {money(lifetime['expense_cents'])}"
    )

    left, right = st.columns([1, 1], gap="large")
    with left, st.container(border=True):
        st.markdown("#### Category budgets")
        st.caption("Spending against the monthly limit set by the admin.")
        if budgets:
            st.markdown(budget_rows_html(budgets), unsafe_allow_html=True)
        else:
            st.info("No expense categories yet.")

    with right, st.container(border=True):
        st.markdown("#### Income and expenses")
        st.caption("Last six months. Hover a column to see exact values.")
        st.markdown(trend_html(trend), unsafe_allow_html=True)

    st.write("")
    st.markdown("### Recent activity")
    rows = svc.list_transactions(user["family_id"], limit=8)
    if not rows:
        st.markdown(
            '<div class="fbt-empty">No transactions yet. Add the first expense to start the history.</div>',
            unsafe_allow_html=True,
        )
    else:
        table = pd.DataFrame(
            [
                {
                    "Date": full_date(row["occurred_on"]),
                    "Type": row["kind"].title(),
                    "Category": row["category"],
                    "Member": row["member"],
                    "Amount": money(row["amount_cents"] * (1 if row["kind"] == "income" else -1)),
                    "Note": row["note"],
                }
                for row in rows
            ]
        )
        st.dataframe(table, use_container_width=True, hide_index=True)


# --------------------------------------------------------------------------- add transaction
def render_add_transaction(svc: BudgetService, user: dict[str, Any]) -> None:
    st.markdown("## Add transaction")
    st.caption("Record a purchase or an income. The rule check runs before anything is written to the database.")

    version = st.session_state.setdefault("tx_version", 0)
    categories = svc.list_categories(user["family_id"])
    expense = [c for c in categories if c["kind"] == "expense"]
    income = [c for c in categories if c["kind"] == "income"]

    left, right = st.columns([1.15, 0.85], gap="large")
    with left:
        with st.container(border=True):
            with st.form(f"tx_form_{version}"):
                kind = st.radio(
                    "Type", ["expense", "income"], horizontal=True, format_func=str.title, key=f"kind_{version}"
                )
                pool = expense if kind == "expense" else income
                amount = st.number_input(
                    "Amount, KZT", min_value=0.0, step=500.0, format="%.2f", key=f"amt_{version}"
                )
                category_id = st.selectbox(
                    "Category",
                    options=[c["id"] for c in pool] or [None],
                    format_func=lambda cid: next((c["name"] for c in pool if c["id"] == cid), "No categories"),
                    key=f"cat_{version}",
                )
                occurred = st.date_input("Date", value=date.today(), max_value=date.today(), key=f"day_{version}")
                note = st.text_input(
                    "Note (optional)", placeholder="Magnum, weekly groceries", max_chars=280, key=f"note_{version}"
                )
                submitted = st.form_submit_button("Save transaction", type="primary", use_container_width=True)

        if submitted:
            try:
                svc.add_transaction(user, kind, amount, category_id, occurred, note)
            except ValidationError as exc:
                st.error(exc.message)
            else:
                st.session_state["tx_version"] = version + 1
                selected = next((c["name"] for c in pool if c["id"] == category_id), "category")
                flash("success", f"Saved {kind} of {money(int(round(amount * 100)))} in {selected}.")
                st.rerun()

    with right:
        with st.container(border=True):
            st.markdown("#### Rules applied on save")
            st.caption("These checks come from the requirements document.")
            st.markdown(
                """
- Amount must be greater than zero and have at most two decimals.
- The date cannot be in the future and cannot be older than ten years.
- The category must belong to your family and match the transaction type.
- The member is taken from the signed-in session, not typed by hand.
- Money is stored as integer cents, so no rounding error reaches the balance.
"""
            )
        st.write("")
        with st.container(border=True):
            st.markdown("#### This month")
            summary = svc.month_summary(user["family_id"], date.today().year, date.today().month)
            st.metric("Expenses so far", money(summary["expense_cents"]))
            st.metric("Balance", money(summary["balance_cents"]))


# --------------------------------------------------------------------------- history
def render_history(svc: BudgetService, user: dict[str, Any]) -> None:
    st.markdown("## Transaction history")
    st.caption("Filter the shared record, check a single row and export it for a family meeting.")

    categories = svc.list_categories(user["family_id"])
    c1, c2, c3, c4 = st.columns([1, 1, 1, 1.2])
    period = c1.selectbox("Period", ["This month", "Last 3 months", "This year", "All time"], index=0)
    kind_filter = c2.selectbox("Type", ["All", "Expenses", "Income"])
    category_filter = c3.selectbox("Category", ["All"] + sorted({c["name"] for c in categories}))
    search = c4.text_input("Search", placeholder="Note or category")

    today = date.today()
    start: date | None = None
    end: date | None = today
    if period == "This month":
        start, end = month_bounds(today.year, today.month)
    elif period == "Last 3 months":
        year, month = add_months(today.year, today.month, -2)
        start = date(year, month, 1)
    elif period == "This year":
        start = date(today.year, 1, 1)

    kind = None if kind_filter == "All" else ("expense" if kind_filter == "Expenses" else "income")
    category_id = None
    if category_filter != "All":
        category_id = next((c["id"] for c in categories if c["name"] == category_filter), None)

    rows = svc.list_transactions(
        user["family_id"], start=start, end=end, kind=kind, category_id=category_id, search=search
    )
    income = sum(r["amount_cents"] for r in rows if r["kind"] == "income")
    expense = sum(r["amount_cents"] for r in rows if r["kind"] == "expense")

    m1, m2, m3 = st.columns(3)
    m1.metric("Rows found", len(rows))
    m2.metric("Income in selection", money(income))
    m3.metric("Expenses in selection", money(expense))

    if not rows:
        st.markdown('<div class="fbt-empty">Nothing matches these filters.</div>', unsafe_allow_html=True)
        return

    table = pd.DataFrame(
        [
            {
                "ID": row["code"],
                "Date": full_date(row["occurred_on"]),
                "Type": row["kind"].title(),
                "Category": row["category"],
                "Member": row["member"],
                "Amount": money(row["amount_cents"]),
                "Note": row["note"],
            }
            for row in rows
        ]
    )
    st.dataframe(table, use_container_width=True, hide_index=True, height=380)
    st.markdown("### Receipts")
    expense_rows = [r for r in rows if r["kind"] == "expense"]
    if not expense_rows:
        st.caption("There are no expenses in the current filtered history.")
    else:
        expense_options = {
            f'{r["code"]} · {full_date(r["occurred_on"])} · {r["category"]} · {money(r["amount_cents"])}': r["id"]
            for r in expense_rows
        }
        chosen_label = st.selectbox("Choose an expense", list(expense_options), key="receipt_expense_choice")
        chosen_transaction_id = expense_options[chosen_label]

        uploaded = st.file_uploader(
            "Attach receipt (JPG, PNG or PDF; max 10 MB)",
            type=["jpg", "jpeg", "png", "pdf"],
            key=f"receipt_upload_{chosen_transaction_id}",
        )
        if st.button("Attach file", key=f"attach_receipt_{chosen_transaction_id}", disabled=uploaded is None):
            try:
                attach_receipt(svc.db, user, chosen_transaction_id, uploaded)
            except ReceiptError as exc:
                st.error(str(exc))
            except Exception as exc:
                st.error(f"Could not save receipt: {exc}")
            else:
                st.success("Receipt attached successfully.")
                st.rerun()

        try:
            attached_receipts = list_receipts(svc.db, user, chosen_transaction_id)
        except ReceiptError as exc:
            st.error(str(exc))
            attached_receipts = []

        if attached_receipts:
            st.markdown("#### Attached files")
            for receipt in attached_receipts:
                with st.container(border=True):
                    st.write(f'**{receipt["original_name"]}** · {receipt["file_size"]:,} bytes')
                    try:
                        original_name, content_type, file_bytes = read_receipt(svc.db, user, receipt["id"])
                        if content_type.startswith("image/"):
                            st.image(file_bytes, caption=original_name, use_container_width=True)
                        st.download_button(
                            "Open / download receipt",
                            data=file_bytes,
                            file_name=original_name,
                            mime=content_type,
                            key=f'download_receipt_{receipt["id"]}',
                        )
                        if st.button("Delete receipt", key=f'delete_receipt_{receipt["id"]}'):
                            delete_receipt(svc.db, user, receipt["id"])
                            st.success("Receipt deleted.")
                            st.rerun()
                    except ReceiptError as exc:
                        st.error(str(exc))

    dl, manage = st.columns([1, 1.4])
    dl.download_button(
        "Download CSV",
        data=transactions_to_csv(rows),
        file_name=f"family-budget-{today.isoformat()}.csv",
        mime="text/csv",
        use_container_width=True,
    )
    with manage:
        with st.expander("Delete a transaction"):
            options = {
                f'{r["code"]} · {full_date(r["occurred_on"])} · {r["category"]} · {money(r["amount_cents"])}': r["id"]
                for r in rows
            }
            label = st.selectbox("Row", list(options), label_visibility="collapsed")
            if st.button("Delete selected", type="primary"):
                try:
                    svc.delete_transaction(user, options[label])
                except (AccessDenied, NotFound) as exc:
                    st.error(str(exc))
                else:
                    flash("success", "Transaction deleted.")
                    st.rerun()


# --------------------------------------------------------------------------- categories
def render_categories(svc: BudgetService, user: dict[str, Any]) -> None:
    st.markdown("## Categories & budgets")
    st.caption("Expense categories carry a monthly limit. Only the family admin can change the structure.")

    year, month = month_picker("cat_month")
    budgets = svc.budget_status(user["family_id"], year, month)
    categories = svc.list_categories(user["family_id"])

    left, right = st.columns([1.2, 0.8], gap="large")
    with left, st.container(border=True):
        st.markdown("#### Monthly limits")
        st.caption(date(year, month, 1).strftime("%B %Y"))
        st.markdown(
            budget_rows_html(budgets) or "<p class='fbt-sub'>No expense categories.</p>", unsafe_allow_html=True
        )

    with right:
        if user["role"] != "admin":
            st.info("Only the family admin can edit categories, limits and members.")
            return

        version = st.session_state.setdefault("cat_version", 0)
        with st.container(border=True):
            with st.form(f"limit_form_{version}"):
                st.markdown("#### Change a limit")
                options = {c["name"]: c["id"] for c in categories if c["kind"] == "expense"}
                if not options:
                    st.caption("Create an expense category first.")
                else:
                    target = st.selectbox("Category", list(options), label_visibility="collapsed")
                    current = next((c for c in categories if c["id"] == options[target]), None)
                    default = (current["monthly_limit_cents"] or 0) / 100 if current else 0.0
                    limit = st.number_input(
                        "New monthly limit, KZT (0 = no limit)", min_value=0.0, value=float(default), step=5000.0
                    )
                    if st.form_submit_button("Save limit", type="primary", use_container_width=True):
                        try:
                            svc.set_category_limit(user, options[target], None if limit == 0 else limit)
                        except ValidationError as exc:
                            st.error(exc.message)
                        else:
                            st.session_state["cat_version"] = version + 1
                            flash("success", f"Limit for {target} updated.")
                            st.rerun()

        st.write("")
        with st.expander("Add a category"):
            with st.form("new_category"):
                name = st.text_input("Name", placeholder="Pets")
                kind = st.radio("Type", ["expense", "income"], horizontal=True, format_func=str.title)
                initial = st.number_input("Monthly limit, KZT (optional)", min_value=0.0, step=1000.0)
                if st.form_submit_button("Add category", use_container_width=True):
                    try:
                        svc.create_category(user, name, kind, None if initial == 0 else initial)
                    except (ValidationError, ConflictError) as exc:
                        st.error(str(exc))
                    else:
                        flash("success", f'Category "{name}" added.')
                        st.rerun()

        active = [c for c in categories if c["kind"] == "expense"]
        if active:
            with st.expander("Archive a category"):
                st.caption("Categories with existing transactions are hidden, not deleted, so history stays correct.")
                labels = {c["name"]: c["id"] for c in active}
                chosen = st.selectbox("Category", list(labels))
                if st.button("Archive", key="archive_btn"):
                    try:
                        svc.archive_category(user, labels[chosen])
                    except NotFound as exc:
                        st.error(str(exc))
                    else:
                        flash("success", f'"{chosen}" archived.')
                        st.rerun()


# --------------------------------------------------------------------------- members
def render_members(svc: BudgetService, user: dict[str, Any]) -> None:
    st.markdown("## Family members")
    family = svc.get_family(user["family_id"])
    members = svc.list_members(user["family_id"])

    left, right = st.columns([1.25, 0.75], gap="large")
    with left:
        frame = pd.DataFrame(
            [
                {
                    "Name": m["full_name"],
                    "E-mail": m["email"],
                    "Role": "Admin" if m["role"] == "admin" else "Member",
                    "Status": "Active" if int(m["is_active"]) else "Deactivated",
                }
                for m in members
            ]
        )
        st.dataframe(frame, use_container_width=True, hide_index=True)
        st.caption(
            "Admin: manages categories, limits, members and may delete any transaction. "
            "Member: adds own transactions, sees the shared history, deletes only own rows."
        )

    with right:
        with st.container(border=True):
            st.markdown("#### Invite code")
            st.caption("Share it only with your family.")
            st.code(family["invite_code"], language=None)
            st.caption("A new member registers with this code and becomes a regular member.")

        if user["role"] == "admin":
            others = [m for m in members if int(m["id"]) != int(user["id"])]
            if others:
                st.write("")
                with st.expander("Manage a member", expanded=True):
                    labels = {f'{m["full_name"]} · {m["role"]}': m for m in others}
                    chosen = st.selectbox("Member", list(labels), label_visibility="collapsed")
                    member = labels[chosen]
                    new_role = st.radio(
                        "Role", ["member", "admin"], horizontal=True, index=0 if member["role"] == "member" else 1
                    )
                    if st.button("Save role", use_container_width=True):
                        try:
                            svc.set_member_role(user, member["id"], new_role)
                        except AccessDenied as exc:
                            st.error(str(exc))
                        else:
                            flash("success", f'Role for {member["full_name"]} updated.')
                            st.rerun()
                    active = bool(int(member["is_active"]))
                    if st.button("Deactivate" if active else "Reactivate", use_container_width=True):
                        try:
                            svc.set_member_active(user, member["id"], not active)
                        except AccessDenied as exc:
                            st.error(str(exc))
                        else:
                            flash("success", f'{member["full_name"]} updated.')
                            st.rerun()


# --------------------------------------------------------------------------- entry point
def main() -> None:
    st.set_page_config(
        page_title=settings.app_name,
        page_icon=PAGE_ICON,
        layout="wide",
        initial_sidebar_state="auto",
    )
    st.markdown(CSS, unsafe_allow_html=True)

    if st.session_state.pop("logout_requested", False):
        st.session_state.clear()
        st.rerun()

    try:
        db, svc = get_service()
    except Exception as exc:  # pragma: no cover - configuration problem
        st.error(f"Cannot start the application: {exc}")
        st.stop()
        return

    user = st.session_state.get("user")
    if user:
        try:
            user = svc.get_user(user["id"])  # refresh role and status on every run
        except NotFound:
            st.session_state.clear()
            st.rerun()
            return
        st.session_state["user"] = user
        render_app(svc, db, user)
    else:
        render_auth(svc)


main()
