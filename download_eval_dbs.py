import os, urllib.request, sqlite3, json

# 18 diverse databases from Spider (none in the 11 excluded prior evaluation databases)
SELECTED_DBS = [
    'concert_singer',
    'cinema',
    'car_1',
    'store_product',
    'course_teach',
    'museum_visit',
    'wta_1',
    'battle_death',
    'dog_kennels',
    'network_1',
    'poker_player',
    'orchestra',
    'singer',
    'pets_1',
    'world_1',
    'tvshow',
    'voter_1',
    'flight_company'
]

os.makedirs('data/evaluation_dbs', exist_ok=True)

def download_and_inspect():
    print(f"Downloading {len(SELECTED_DBS)} fresh evaluation databases from Spider...")
    db_stats = {}
    for db in SELECTED_DBS:
        local_path = os.path.join('data/evaluation_dbs', f'{db}.sqlite')
        if not os.path.exists(local_path):
            u = f'https://huggingface.co/datasets/Chinastark/spider_datasets/resolve/main/database/{db}/{db}.sqlite'
            req = urllib.request.Request(u, headers={'User-Agent': 'Mozilla/5.0'})
            data = urllib.request.urlopen(req, timeout=30).read()
            with open(local_path, 'wb') as f:
                f.write(data)
            print(f"Downloaded {db}: {len(data)} bytes")
        else:
            print(f"Exists locally: {db}")

        # Inspect tables and row counts
        conn = sqlite3.connect(local_path)
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%';")
        tables = [r[0] for r in cur.fetchall()]
        table_counts = {}
        for t in tables:
            try:
                cur.execute(f'SELECT COUNT(*) FROM "{t}";')
                table_counts[t] = cur.fetchone()[0]
            except Exception as e:
                table_counts[t] = str(e)
        conn.close()
        db_stats[db] = {
            'path': local_path,
            'tables': table_counts
        }
        print(f"  {db}: {len(tables)} tables: {list(table_counts.keys())}")

    with open('data/evaluation_dbs/db_inventory.json', 'w') as f:
        json.dump(db_stats, f, indent=2)
    print("Database inspection complete! Saved inventory to data/evaluation_dbs/db_inventory.json")

if __name__ == '__main__':
    download_and_inspect()

