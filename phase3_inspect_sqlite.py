"""
The MTGA .mtga files are SQLite databases. List the tables in each so
we can see the schema and figure out which tables hold the card data
and the localized names.
"""

import sqlite3
from pathlib import Path

DATA_DIR = Path(r"C:\Program Files\Wizards of the Coast\MTGA\MTGA_Data\Downloads\Raw")
FILES = [
    "Raw_ClientLocalization_405e991af0a27c163db2b7a0e0a09c07.mtga",
    "Raw_CardDatabase_c8cab57af7d1f0182cab54633c99f859.mtga",
]


def inspect(path: Path) -> None:
    print("=" * 70)
    print(f"File: {path.name}")
    # Open read-only via URI to avoid creating a journal
    uri = f"file:{path.as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    cur = conn.cursor()

    cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    tables = [r[0] for r in cur.fetchall()]
    print(f"Tables ({len(tables)}): {tables}")
    print()

    for t in tables:
        try:
            cur.execute(f"SELECT count(*) FROM '{t}'")
            n = cur.fetchone()[0]
        except Exception as e:
            n = f"?? ({e})"
        # Get column names
        try:
            cur.execute(f"PRAGMA table_info('{t}')")
            cols = [(r[1], r[2]) for r in cur.fetchall()]
        except Exception:
            cols = []
        print(f"  table '{t}': {n} rows")
        for col_name, col_type in cols:
            print(f"     - {col_name} ({col_type})")
        # Show one sample row
        try:
            cur.execute(f"SELECT * FROM '{t}' LIMIT 1")
            row = cur.fetchone()
            if row:
                # truncate values for readability
                pretty = []
                for v in row:
                    s = str(v)
                    if len(s) > 60:
                        s = s[:60] + "…"
                    pretty.append(s)
                print(f"     sample: {pretty}")
        except Exception as e:
            print(f"     (could not sample: {e})")
        print()
    conn.close()


if __name__ == "__main__":
    for fn in FILES:
        p = DATA_DIR / fn
        if p.exists():
            inspect(p)
