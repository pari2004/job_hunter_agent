import sqlite3, json
from pathlib import Path

con = sqlite3.connect('jobs.db')
con.row_factory = sqlite3.Row

tables = con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
print("=== TABLES ===")
for t in tables:
    name = t['name']
    cols = con.execute(f"PRAGMA table_info({name})").fetchall()
    count = con.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
    print(f"  {name}: {count} rows | cols: {[c['name'] for c in cols]}")

print()
src = json.loads(Path('sources.json').read_text())
print(f"GH tokens: {len(src.get('greenhouse',[]))}: {src.get('greenhouse',[])[:5]}")
print(f"LV sites:  {len(src.get('lever',[]))}: {src.get('lever',[])}")
print(f"RemoteOK:  {src.get('remoteok',False)}")
