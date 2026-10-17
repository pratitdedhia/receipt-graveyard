import sqlite3

con = sqlite3.connect("expenses.db")
con.row_factory = sqlite3.Row
tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
print("TABLES:", tables)
for t in tables:
    count = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
    cols = [r[1] for r in con.execute(f"PRAGMA table_info({t})").fetchall()]
    print(f"\nTABLE {t} ({count} rows):")
    print("  Columns:", ", ".join(cols))
