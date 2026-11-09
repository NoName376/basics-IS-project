# Family Budget Tracker

Information Systems team project — **Team 38**.
Application & Development: **Akhmetshiev Arman (24B030051)**.

A shared family budget: every member signs in to one family workspace, records income and
expenses, and immediately sees the same balance, category budgets and history.

---

## 1. What is implemented

| Assigned item (my part) | Where it lives | Status |
|---|---|---|
| User interface | `app.py` (5 screens, one visual language) | Done |
| Registration (new family + invite code) | `core/services.py` → `register_family`, `join_family` | Done |
| Login / session / lockout | `core/security.py`, `render_auth` in `app.py` | Done |
| Add transaction (income & expense) | `render_add_transaction`, `BudgetService.add_transaction` | Done |
| Business logic (balance, budgets, savings rate) | `core/services.py` | Done |
| Database connection (PostgreSQL + SQLite demo) | `core/db.py`, `sql/schema_postgres.sql` | Done |
| Transaction history (filters, search, CSV) | `render_history`, `core/export.py` | Done |

Extra, because the neighbours need it: family members and roles (Abdulaziz's access-control
section), category limits and monthly analytics (Abu's analytics section), and validation
rules (Ali's requirements section).

## 2. Run it

Windows, one click (installs everything on the first run):

```bat
START.bat
```

`CHECK.bat` runs the 34 unit tests and the 10 end-to-end checks — use it before the lesson.

Manual way:

```bat
python -m pip install -r requirements.txt
streamlit run app.py
```

The browser opens at `http://localhost:8501`.

Without `DATABASE_URL` the app creates `data/family_budget.db` (SQLite) — same tables, same
queries, so the demo works even if PostgreSQL is not installed on the presentation laptop.

### Demo data

```bat
python seed_demo.py --reset
```

| Role | E-mail | Password |
|---|---|---|
| Family admin | `arman@family.kz` | `Demo1234` |
| Family member | `aigerim@family.kz` | `Demo1234` |

Six months of realistic transactions, 111 records, budgets already partly used.

## 3. Connect PostgreSQL (team database)

1. Install PostgreSQL 18 and remember the `postgres` password.
2. Create `postgres_url.txt` in this folder with one line:
   `postgresql://postgres:YOUR_PASSWORD@localhost:5432/family_budget`
   (special characters in the password must be percent-encoded: `%` → `%25`, `@` → `%40`).
3. Double-click **`SETUP_POSTGRES.bat`**. It creates the database, loads `sql/schema_postgres.sql`,
   imports Alibek's records from his `data.sql` and writes `postgres_url.txt`.
4. Check: `python tools/db_check.py` → OK, `python selfcheck.py` → 10/10, `START.bat` → the
   sidebar shows **Backend: PostgreSQL**.

Manual alternative:

```bat
createdb -U postgres family_budget
psql -U postgres -d family_budget -f sql\schema_postgres.sql
set /p DATABASE_URL=<postgres_url.txt
python tools\import_alibek.py --schema "schema.sql" --data "data.sql"
```

The schema is created automatically on start (`Database.init_schema`), so the `psql` step is
optional. The sidebar shows which backend is active, so it is obvious during the demo.

## 4. How the code is organised

```
app.py                  Streamlit screens; no SQL, no business rules
core/
  config.py             environment settings (DATABASE_URL, currency)
  db.py                 one SQL dialect for two backends, integer cents
  security.py           PBKDF2 hashing, password policy, invite codes
  validators.py         amount/date/text rules, money formatting
  services.py           use cases, permissions, balance and budget queries
  export.py             CSV export
  presentation.py       HTML for budget bars and the 6-month chart
sql/
  schema_postgres.sql   production schema
  schema_sqlite.sql     identical schema for the demo
tools/
  db_check.py           checks any database against the schema contract
  abu_conformance.py    re-runs Abu's 9 defects against this build
  abu_cases.py          runs all 31 of Abu's test cases against this build
  import_alibek.py      imports Alibek's dump into the application schema
docs/
  DB_CONTRACT.md        tables and columns the application expects
  ABU_31_CASES_RU.md    result of the 31-case run on the team build
  ABU_TEAM_SUITE_RU.md  result of Abu's 36-case suite and the TC-T-29 fix
  ALIBEK_INTEGRATION_RU.md  schema differences, connection string, migration plan
  TEAM_REQUESTS_RU.md   ready-to-send messages to Alibek and Abu
  DEMO_SCENARIO_RU.md   what to click and say at the weekly check
tests/test_core.py      34 unit tests
selfcheck.py            10 end-to-end checks of the data path
seed_demo.py            demo family generator
```

The application never builds SQL in the user interface. Screens call `BudgetService`, the
service calls the database layer, and every statement uses parameters (`?` → `%s`), so user
text can never change the query.

## 5. Data model (4 tables)

```
families 1 ──< users
    │            │
    │            └──< transactions >── categories
    └──────────────────────────────────┘
```

* `families` — one budget per family, 6-character invite code.
* `users` — e-mail (unique), PBKDF2 hash, role `admin`/`member`, active flag.
* `categories` — `expense` or `income`, optional monthly limit in cents.
* `transactions` — amount in **integer cents**, date, note, author, category.

Money is stored as `BIGINT` cents instead of `FLOAT`. `0.1 + 0.2` in floating point is not
`0.3`; with integers the balance is exact at any number of records. That decision is also
documented for the data-dictionary section of the team report.

## 6. Rules enforced before a write

| Rule | Implemented in | Message shown to the user |
|---|---|---|
| Amount > 0, max 2 decimals | `parse_amount` | "Amount must be greater than zero." |
| Date not in the future, not older than 10 years | `parse_date` | "The date cannot be in the future." |
| Category belongs to the family and matches the type | `add_transaction` | "…is a income category, not expense." |
| Only admin changes categories, limits, members | `_require_admin` | "Only the family admin can do this." |
| Member deletes only own rows | `delete_transaction` | "You can delete only your own transactions." |
| Last active admin cannot be removed | `set_member_active` | "The family must keep at least one active admin." |
| E-mail unique, password ≥ 8 chars with letter + digit | `_check_identity` | listed problems |

## 7. Security decisions (hand-over to Abdulaziz)

* PBKDF2-HMAC-SHA256, 260 000 iterations, 16-byte random salt per user → a stolen table
  cannot be reversed with a rainbow table.
* `hmac.compare_digest` for hash comparison; the login always hashes, so a wrong e-mail and a
  wrong password take the same time (no user enumeration).
* Five failed attempts lock the form for 60 seconds.
* Session holds the user **without** the password hash; the role is re-read from the database
  on every rerun, so a deactivated member is locked out immediately.
* All SQL is parameterised; category names and notes are HTML-escaped before rendering.
* The invite code is the only way into a family; it is generated from an alphabet without
  ambiguous characters.

Not done yet (next iteration): TLS termination, database backups, audit log of deletions.

## 8. Tests

```bat
python -m unittest discover -s tests -v   :: 34 tests
python selfcheck.py                       :: 10 end-to-end checks
python tools/abu_conformance.py           :: Abu's 9 defects, re-checked here
python tools/db_check.py                  :: database matches the schema contract
```

Both run without Streamlit, PostgreSQL or a browser. `selfcheck.py` walks the same sequence
the screens perform and prints PASS/FAIL for each step — useful right before the lesson.

## 9. Known limitations

* SQLite is a demo fallback; the team database is PostgreSQL.
* No password reset by e-mail (no mail server in the project scope).
* CSV export only; PDF report is a later task.
* The UI is optimised for a laptop browser, not for a phone.

## 10. Team interfaces

* **Alibek (database):** needs `DATABASE_URL` and must run `schema_postgres.sql`. Column names
  in section 5 are the contract between the ERD and the application.
* **Abdulaziz (architecture/security):** section 7 is the implemented part of his security
  description; the data flow is UI → service → repository → PostgreSQL.
* **Abu (testing):** `selfcheck.py` and section 6 give ready test cases with expected messages.
* **Ali (requirements):** section 6 maps FR-01…FR-04 to code locations for the acceptance
  criteria.
