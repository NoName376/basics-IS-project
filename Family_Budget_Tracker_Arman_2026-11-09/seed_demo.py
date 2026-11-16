"""Create a realistic demo family so the application can be shown at the weekly check.

Usage:
    python seed_demo.py            # create the demo family if it does not exist
    python seed_demo.py --reset    # delete the demo family and recreate it
"""

from __future__ import annotations

import random
import sys
from datetime import date, timedelta

from core.config import load_settings
from core.db import Database
from core.services import BudgetService
from core.validators import add_months, month_bounds

DEMO_FAMILY = "Akhmetshiev Family"
ADMIN_EMAIL = "arman@family.kz"
MEMBER_EMAIL = "aigerim@family.kz"
DEMO_PASSWORD = "Demo1234"

EXPENSE_PLAN = {
    "Food": (6, 9_000, 26_000),
    "Transport": (4, 1_200, 7_500),
    "Housing & utilities": (2, 45_000, 75_000),
    "Health": (1, 4_000, 18_000),
    "Education": (1, 12_000, 30_000),
    "Entertainment": (2, 3_500, 14_000),
    "Shopping": (2, 6_000, 32_000),
}
NOTES = {
    "Food": ["Magnum weekly shop", "Small market", "Bakery", "Meat and vegetables"],
    "Transport": ["Fuel", "City bus card", "Taxi to clinic"],
    "Housing & utilities": ["Electricity", "Water and heating", "Internet"],
    "Health": ["Pharmacy", "Dentist visit"],
    "Education": ["English course", "School supplies"],
    "Entertainment": ["Cinema", "Cafe with friends"],
    "Shopping": ["Winter jacket", "Household items"],
}


def reset_demo(service: BudgetService, db: Database) -> None:
    row = db.query_one("SELECT id FROM families WHERE name = ?", (DEMO_FAMILY,))
    if not row:
        return
    db.execute("DELETE FROM transactions WHERE family_id = ?", (row["id"],))
    db.execute("DELETE FROM categories WHERE family_id = ?", (row["id"],))
    db.execute("DELETE FROM users WHERE family_id = ?", (row["id"],))
    db.execute("DELETE FROM families WHERE id = ?", (row["id"],))
    print("Demo family removed.")


def build(service: BudgetService, rng: random.Random) -> None:
    admin = service.register_family(DEMO_FAMILY, "Arman Akhmetshiev", ADMIN_EMAIL, DEMO_PASSWORD)
    family = service.get_family(admin["family_id"])
    member = service.join_family(family["invite_code"], "Aigerim Akhmetshieva", MEMBER_EMAIL, DEMO_PASSWORD)
    print(f"Family created. Invite code: {family['invite_code']}")

    cats = {c["name"]: c["id"] for c in service.list_categories(admin["family_id"])}
    today = date.today()

    for offset in range(5, -1, -1):
        year, month = add_months(today.year, today.month, -offset)
        _, last_day = month_bounds(year, month)
        # The current month is only filled up to today, otherwise the demo
        # would try to create transactions with future dates.
        limit_day = min(last_day.day, today.day) if (year, month) == (today.year, today.month) else last_day.day

        service.add_transaction(admin, "income", 620_000, cats["Salary"], date(year, month, min(5, limit_day)),
                                "Monthly salary")
        service.add_transaction(member, "income", 280_000, cats["Salary"], date(year, month, min(10, limit_day)),
                                "Part-time salary")
        if offset % 3 == 0:
            service.add_transaction(admin, "income", rng.randrange(40_000, 90_000), cats["Freelance"],
                                    date(year, month, min(18, limit_day)), "Freelance project")

        for name, (times, low, high) in EXPENSE_PLAN.items():
            if limit_day < last_day.day:  # partial current month
                times = max(1, round(times * limit_day / 28))
            for _ in range(times):
                day = rng.randint(1, limit_day)
                amount = rng.randrange(low, high, 100)
                note = rng.choice(NOTES[name])
                user = member if rng.random() < 0.45 else admin
                service.add_transaction(user, "expense", amount, cats[name], date(year, month, day), note)

    print("Demo transactions inserted.")


def main() -> None:
    settings = load_settings()
    db = Database(settings.database_url, settings.sqlite_path)
    db.init_schema()
    service = BudgetService(db, settings.currency)

    if "--reset" in sys.argv:
        reset_demo(service, db)

    if db.query_one("SELECT id FROM users WHERE email = ?", (ADMIN_EMAIL,)):
        print("Demo family already exists. Use --reset to rebuild it.")
        return

    build(service, random.Random(42))
    print()
    print("Sign in with:")
    print(f"  admin  {ADMIN_EMAIL} / {DEMO_PASSWORD}")
    print(f"  member {MEMBER_EMAIL} / {DEMO_PASSWORD}")
    print(f"Backend: {db.label}")


if __name__ == "__main__":
    main()
