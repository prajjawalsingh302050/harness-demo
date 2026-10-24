"""Build data/shop.db from migrations/*.sql plus deterministic seed data.

Run this after adding or changing a migration:
    python scripts/build_db.py
Check that the committed database matches the migrations (used by CI):
    python scripts/build_db.py --check
"""
import random
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# The database file the app reads.
DB = ROOT / "data" / "shop.db"

# How many fake people to create.
N_PEOPLE = 10_000

# Name and city pools; picked with a fixed random seed so every build is identical.
FIRST = ["Aarav", "Vivaan", "Aditya", "Ishaan", "Kabir", "Ananya", "Diya", "Saanvi", "Myra", "Aisha",
         "Rohan", "Arjun", "Meera", "Kavya", "Nikhil", "Priya", "Rahul", "Sneha", "Vikram", "Zara"]
LAST = ["Sharma", "Verma", "Singh", "Gupta", "Iyer", "Reddy", "Nair", "Das", "Mehta", "Kapoor",
        "Joshi", "Patel", "Rao", "Bose", "Khan", "Malhotra", "Chopra", "Menon", "Pillai", "Saxena"]
CITIES = ["Delhi", "Mumbai", "Bengaluru", "Chennai", "Kolkata", "Hyderabad", "Pune", "Jaipur",
          "Lucknow", "Kochi", "Indore", "Bhopal", "Surat", "Nagpur", "Patna", "Guwahati"]


def fingerprint(path):
    """Schema plus row counts. Bytes differ between SQLite versions, so compare this instead."""
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    schema = sorted(r[0] for r in con.execute("SELECT sql FROM sqlite_master WHERE sql IS NOT NULL"))
    counts = {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("people",)}
    con.close()
    return schema, counts


def main():
    """Build the database into a temp file, then either replace data/shop.db or, with --check, compare."""
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
    """Apply every migration in name order, then insert the seeded people."""
    con = sqlite3.connect(tmp)
    for migration in sorted((ROOT / "migrations").glob("*.sql")):
        con.executescript(migration.read_text())

    rnd = random.Random(42)
    people = []
    for pid in range(1, N_PEOPLE + 1):
        first, last = rnd.choice(FIRST), rnd.choice(LAST)
        people.append((pid, f"{first} {last}", f"{first}.{last}{pid}@example.com".lower(), rnd.choice(CITIES)))
    con.executemany("INSERT INTO people (id, name, email, city) VALUES (?, ?, ?, ?)", people)

    con.commit()
    con.execute("VACUUM")
    con.close()
    print(f"Built {DB.relative_to(ROOT)}: {N_PEOPLE} people")


if __name__ == "__main__":
    main()
