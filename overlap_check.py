import os, json, sys

def run_overlap_check():
    existing_dbs = set()
    sources = {}

    def add_db(db, src):
        if db:
            existing_dbs.add(db)
            sources.setdefault(db, []).append(src)

    # 1. BIRD mutations
    p1 = 'bird_eval/results/bird_mutations_dataset.json'
    if os.path.exists(p1):
        data = json.load(open(p1))
        muts = data.get('mutations', data if isinstance(data, list) else [])
        for item in muts:
            add_db(item.get('db_id') or item.get('database'), 'bird_342_mutations')

    # 2. 50 benign queries
    p2 = 'bird_eval/results/bird_mini_dev_50_eval.json'
    if os.path.exists(p2):
        data = json.load(open(p2))
        for item in (data if isinstance(data, list) else data.get('results', [])):
            add_db(item.get('db_id') or item.get('database'), 'benign_50')

    # 3. V1 / V2
    for p3 in ['benchmark/heldout_v1_1500_dataset.json', 'benchmark/adversarial_v2_1500_dataset.json']:
        if os.path.exists(p3):
            data = json.load(open(p3))
            items = data if isinstance(data, list) else data.get('cases', [])
            for item in items:
                add_db(item.get('db_id') or item.get('database') or item.get('db'), os.path.basename(p3))

    # 4. BIRD mini-dev
    p4 = 'bird_eval/databases/data_minidev/MINIDEV/mini_dev_sqlite.json'
    if os.path.exists(p4):
        data = json.load(open(p4))
        for item in (data if isinstance(data, list) else []):
            add_db(item.get('db_id') or item.get('database'), 'bird_mini_dev')

    # 5. DBBench
    p5 = 'benchmark/dbbench_cleaned/tasks_cleaned.json'
    if os.path.exists(p5):
        data = json.load(open(p5))
        for item in (data if isinstance(data, list) else []):
            add_db(item.get('db_id') or item.get('database'), 'dbbench')

    # 6. Additional benchmark files
    for p6 in ['benchmark/benchmark_dataset.json', 'benchmark/heldout_dataset.json', 'benchmark/heldout_v2_dataset.json']:
        if os.path.exists(p6):
            data = json.load(open(p6))
            items = data if isinstance(data, list) else data.get('cases', [])
            for item in items:
                add_db(item.get('db_id') or item.get('database') or item.get('db'), os.path.basename(p6))

    print(f"Total existing/prior evaluation database schemas identified: {len(existing_dbs)}")
    for db in sorted(existing_dbs):
        print(f"  - {db} (sources: {set(sources.get(db, []))})")

    return existing_dbs

if __name__ == '__main__':
    os.makedirs('results', exist_ok=True)
    existing = run_overlap_check()
    with open('results/overlap_existing_dbs.json', 'w') as f:
        json.dump(sorted(list(existing)), f, indent=2)
    print("Saved existing databases to results/overlap_existing_dbs.json")
