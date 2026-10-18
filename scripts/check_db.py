# scripts/check_db.py - Inspects SQLite database tables, row counts, and schema
import sqlite3
from pathlib import Path

# Resolve expenses.db at repository root
repo_root = Path(__file__).resolve().parent.parent
db_path = repo_root / "expenses.db" if (repo_root / "expenses.db").exists() else Path("expenses.db")

con = sqlite3.connect(db_path)
con.row_factory = sqlite3.Row
tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
print(f"DATABASE: {db_path.resolve()}")
print("TABLES:", tables)
for t in tables:
    count = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
    cols = [r[1] for r in con.execute(f"PRAGMA table_info({t})").fetchall()]
    print(f"\nTABLE {t} ({count} rows):")
    print("  Columns:", ", ".join(cols))
