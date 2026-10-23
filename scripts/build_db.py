"""Build data/shop.db from migrations/*.sql plus deterministic seed data.

Run this after adding or changing a migration:
    python scripts/build_db.py
Check that the committed database matches the migrations (used by CI):
    python scripts/build_db.py --check
"""
import random
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "shop.db"

N_USERS = 2_000
N_ORDERS = 20_000
ITEMS_PER_ORDER = (4, 12)

FIRST = ["Aarav", "Vivaan", "Aditya", "Ishaan", "Kabir", "Ananya", "Diya", "Saanvi", "Myra", "Aisha",
         "Rohan", "Arjun", "Meera", "Kavya", "Nikhil", "Priya", "Rahul", "Sneha", "Vikram", "Zara"]
LAST = ["Sharma", "Verma", "Singh", "Gupta", "Iyer", "Reddy", "Nair", "Das", "Mehta", "Kapoor",
        "Joshi", "Patel", "Rao", "Bose", "Khan", "Malhotra", "Chopra", "Menon", "Pillai", "Saxena"]
CITIES = ["Delhi", "Mumbai", "Bengaluru", "Chennai", "Kolkata", "Hyderabad", "Pune", "Jaipur",
          "Lucknow", "Kochi", "Indore", "Bhopal", "Surat", "Nagpur", "Patna", "Guwahati"]
PRODUCTS = [("Keyboard", 1499.0), ("Mouse", 699.0), ("Monitor", 12999.0), ("USB-C Hub", 1999.0),
            ("Headphones", 3499.0), ("Webcam", 2799.0), ("Laptop Stand", 1299.0), ("SSD 1TB", 6499.0),
            ("Desk Lamp", 999.0), ("Router", 3999.0), ("Microphone", 4599.0), ("Cable Pack", 499.0)]
STATUSES = ["delivered", "delivered", "delivered", "shipped", "processing", "cancelled"]


def fingerprint(path):
    """Schema plus row counts. Bytes differ between SQLite versions, so compare this instead."""
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    schema = sorted(r[0] for r in con.execute("SELECT sql FROM sqlite_master WHERE sql IS NOT NULL"))
    counts = {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("users", "orders", "order_items")}
    con.close()
    return schema, counts


def main():
    DB.parent.mkdir(exist_ok=True)
    tmp = DB.with_suffix(".tmp")
    tmp.unlink(missing_ok=True)
    build(tmp)

    if "--check" in sys.argv:
        same = DB.exists() and fingerprint(DB) == fingerprint(tmp)
        tmp.unlink()
        if not same:
            sys.exit("data/shop.db does not match migrations/. Run: python scripts/build_db.py and commit it.")
        print("data/shop.db matches migrations/")
        return

    tmp.replace(DB)


def build(tmp):
    con = sqlite3.connect(tmp)
    for migration in sorted((ROOT / "migrations").glob("*.sql")):
        con.executescript(migration.read_text())

    rnd = random.Random(42)
    users = []
    for uid in range(1, N_USERS + 1):
        first, last = rnd.choice(FIRST), rnd.choice(LAST)
        users.append((uid, f"{first} {last}", f"{first}.{last}{uid}@example.com".lower(), rnd.choice(CITIES)))
    con.executemany("INSERT INTO users (id, name, email, city) VALUES (?, ?, ?, ?)", users)

    start = datetime(2026, 1, 1)
    orders, items = [], []
    for oid in range(1, N_ORDERS + 1):
        created = start + timedelta(minutes=rnd.randint(0, 60 * 24 * 290))
        orders.append((oid, rnd.randint(1, N_USERS), created.strftime("%Y-%m-%d %H:%M:%S"), rnd.choice(STATUSES)))
        for _ in range(rnd.randint(*ITEMS_PER_ORDER)):
            product, price = rnd.choice(PRODUCTS)
            items.append((oid, product, rnd.randint(1, 3), price))
    con.executemany("INSERT INTO orders (id, user_id, created_at, status) VALUES (?, ?, ?, ?)", orders)
    con.executemany("INSERT INTO order_items (order_id, product, qty, unit_price) VALUES (?, ?, ?, ?)", items)

    con.commit()
    con.execute("VACUUM")
    con.close()
    print(f"Built {DB.relative_to(ROOT)}: {N_USERS} users, {N_ORDERS} orders, {len(items)} order items")


if __name__ == "__main__":
    main()
