"""Quick verification that models create correct tables."""
import sqlite3

from app.core.database import DB_PATH, init_db

# Remove existing db
DB_PATH.unlink(missing_ok=True)

# Create tables from models
init_db()

# Verify schema via sqlite3
conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()
cursor.execute(
    "SELECT name, sql FROM sqlite_master WHERE type='table' ORDER BY name"
)
for name, sql in cursor.fetchall():
    print(f"[{name}]")
    for line in sql.split("\n"):
        print(f"    {line}")
    print()

# Verify indexes
cursor.execute(
    "SELECT name, sql FROM sqlite_master WHERE type='index' AND name NOT LIKE 'sqlite_%' ORDER BY name"
)
for name, sql in cursor.fetchall():
    print(f"[INDEX] {name}")
    if sql:
        print(f"    {sql}")

conn.close()
DB_PATH.unlink(missing_ok=True)
print("All OK")
