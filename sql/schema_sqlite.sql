-- Family Budget Tracker - SQLite schema (used for the offline demo and unit tests).
-- Mirrors sql/schema_postgres.sql. Money is stored as integer cents.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS families (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL,
    invite_code TEXT    NOT NULL UNIQUE,
    currency    TEXT    NOT NULL DEFAULT 'KZT',
    created_at  TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    family_id     INTEGER NOT NULL REFERENCES families (id) ON DELETE CASCADE,
    full_name     TEXT    NOT NULL,
    email         TEXT    NOT NULL UNIQUE,
    password_hash TEXT    NOT NULL,
    role          TEXT    NOT NULL DEFAULT 'member'
                          CHECK (role IN ('admin', 'member')),
    is_active     INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    created_at    TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS categories (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    family_id           INTEGER NOT NULL REFERENCES families (id) ON DELETE CASCADE,
    name                TEXT    NOT NULL,
    kind                TEXT    NOT NULL CHECK (kind IN ('expense', 'income')),
    monthly_limit_cents INTEGER CHECK (monthly_limit_cents IS NULL OR monthly_limit_cents > 0),
    is_active           INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    UNIQUE (family_id, name, kind)
);

CREATE TABLE IF NOT EXISTS transactions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    family_id    INTEGER NOT NULL REFERENCES families (id) ON DELETE CASCADE,
    user_id      INTEGER NOT NULL REFERENCES users (id),
    category_id  INTEGER NOT NULL REFERENCES categories (id),
    kind         TEXT    NOT NULL CHECK (kind IN ('expense', 'income')),
    amount_cents INTEGER NOT NULL CHECK (amount_cents > 0),
    occurred_on  TEXT    NOT NULL,
    note         TEXT    NOT NULL DEFAULT '',
    created_at   TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_transactions_family_date
    ON transactions (family_id, occurred_on DESC);

CREATE INDEX IF NOT EXISTS ix_transactions_category
    ON transactions (category_id);

CREATE INDEX IF NOT EXISTS ix_users_family
    ON users (family_id);

-- Same compatibility view as in schema_postgres.sql.
CREATE VIEW IF NOT EXISTS user_balance AS
SELECT
    u.id AS user_id,
    u.full_name,
    ROUND(COALESCE(SUM(CASE WHEN t.kind = 'income' THEN t.amount_cents ELSE 0 END), 0) / 100.0, 2) AS total_income,
    ROUND(COALESCE(SUM(CASE WHEN t.kind = 'expense' THEN t.amount_cents ELSE 0 END), 0) / 100.0, 2) AS total_expenses,
    ROUND(COALESCE(SUM(CASE WHEN t.kind = 'income' THEN t.amount_cents ELSE -t.amount_cents END), 0) / 100.0, 2) AS balance
FROM users u
LEFT JOIN transactions t ON t.user_id = u.id
GROUP BY u.id, u.full_name;
