# Database contract — what the application expects from Alibek's database

This is the single list of tables and columns the application reads and writes.
If Alibek's schema matches it, the switch to PostgreSQL is one environment
variable and nothing else changes.

Check any database against this contract with:

```
python tools/db_check.py --sqlite data/family_budget.db
set DATABASE_URL=postgresql://user:pass@host:5432/family_budget
python tools/db_check.py
```

---

## 1. Tables

### `families` — one row per family workspace

| Column | Type | Rules |
|---|---|---|
| `id` | BIGINT identity / INTEGER PK | primary key |
| `name` | TEXT | not null |
| `invite_code` | TEXT | not null, **unique**, 6 characters |
| `currency` | TEXT | not null, default `KZT` |
| `created_at` | TIMESTAMP | default now |

### `users` — family members

| Column | Type | Rules |
|---|---|---|
| `id` | BIGINT / INTEGER | primary key |
| `family_id` | BIGINT / INTEGER | **FK → families.id**, cascade delete |
| `full_name` | TEXT | not null |
| `email` | TEXT | not null, **unique**, stored lowercase |
| `password_hash` | TEXT | not null, `pbkdf2_sha256$…` |
| `role` | TEXT | `admin` or `member` |
| `is_active` | SMALLINT / INTEGER | `1` active, `0` deactivated |
| `created_at` | TIMESTAMP | default now |

### `categories` — the shared category table

| Column | Type | Rules |
|---|---|---|
| `id` | BIGINT / INTEGER | primary key |
| `family_id` | BIGINT / INTEGER | **FK → families.id**, cascade delete |
| `name` | TEXT | not null, unique per family and kind |
| `kind` | TEXT | `expense` or `income` |
| `monthly_limit_cents` | BIGINT / INTEGER | nullable; if set, **> 0** |
| `is_active` | SMALLINT / INTEGER | `1` visible, `0` archived |

Unique key: `(family_id, name, kind)`.

### `transactions` — every income and expense

| Column | Type | Rules |
|---|---|---|
| `id` | BIGINT / INTEGER | primary key; the UI shows it as `TX-000123` |
| `family_id` | BIGINT / INTEGER | **FK → families.id**, cascade delete |
| `user_id` | BIGINT / INTEGER | **FK → users.id** |
| `category_id` | BIGINT / INTEGER | **FK → categories.id** |
| `kind` | TEXT | `expense` or `income` |
| `amount_cents` | BIGINT / INTEGER | **CHECK > 0**; money in tiyn, never float |
| `occurred_on` | DATE | `YYYY-MM-DD`, not in the future |
| `note` | TEXT | not null, default `''` |
| `created_at` | TIMESTAMP | default now |

Index: `(family_id, occurred_on DESC)` for the history screen, `(category_id)` for joins.

---

## 2. What still has to come from Alibek

The file `Family_Budget_Tracker_beta.sql` contains only four `SELECT` statements —
there is no `CREATE TABLE` and no data, so it cannot be imported. Please ask for:

1. **Schema**

   ```bat
   pg_dump -U budget_user -d family_budget --schema-only --no-owner -f schema.sql
   ```

2. **Reference data** (families, users, categories — not the transactions)

   ```bat
   pg_dump -U budget_user -d family_budget --data-only --inserts ^
       --table=families --table=users --table=categories -f data.sql
   ```

3. **The connection string** in the form
   `postgresql://budget_user:password@host:5432/family_budget`
   (or a screenshot of `\d transactions` in psql if the server is not reachable from my laptop).

4. **What `User_Balance` returns.** It is referenced in his file but is not part of this
   contract. If it is a view `(user_id, balance_cents, ...)`, the dashboard can read it
   instead of recomputing the balance — that would be a useful addition, but its columns
   must be known first.

---

## 3. If his column names differ

The application touches only the columns in section 1. If his schema uses other names
(for example `amount` instead of `amount_cents`, or `txn_id` instead of `id`), there are
two ways to align:

* **Preferred:** change his dump to this contract — one schema for the whole team, and
  Abu's analytics queries keep working.
* **Fallback:** add a compatibility view in his database:

  ```sql
  CREATE VIEW transactions_app AS
  SELECT txn_id AS id, family_id, user_id, category_id, type AS kind,
         amount * 100 AS amount_cents, tx_date AS occurred_on, note, created_at
  FROM transactions;
  ```

  This needs a one-line change in the application, so it is a temporary solution only.

---

## 4. Acceptance for the switch

The migration is done when all four statements are true:

1. `python tools/db_check.py` prints `RESULT: the database matches the application schema`.
2. `python seed_demo.py --reset` fills the PostgreSQL database without errors.
3. `python selfcheck.py` prints `10/10 checks passed` on PostgreSQL.
4. The sidebar of the running application shows **Backend: PostgreSQL**.
