import sqlite3, json, os

inventory = json.load(open('data/evaluation_dbs/db_inventory.json'))
print(f"Total databases: {len(inventory)}")
summary = {}

for db_name, info in inventory.items():
    conn = sqlite3.connect(info['path'])
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%';")
    tables = [r[0] for r in cur.fetchall()]
    summary[db_name] = {}
    for t in tables:
        cur.execute(f'PRAGMA table_info("{t}");')
        cols = [c[1] for c in cur.fetchall()]
        cur.execute(f'SELECT COUNT(*) FROM "{t}";')
        cnt = cur.fetchone()[0]
        cur.execute(f'SELECT * FROM "{t}" LIMIT 3;')
        sample = cur.fetchall()
        summary[db_name][t] = {
            'count': cnt,
            'cols': cols,
            'sample': sample
        }
    conn.close()

with open('data/evaluation_dbs/detailed_schema.json', 'w') as f:
    json.dump(summary, f, indent=2, default=str)
print("Saved detailed schemas to data/evaluation_dbs/detailed_schema.json")

