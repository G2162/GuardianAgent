"""
run_composition_analysis.py
===========================
Item 4: Composition: per split, counts of benign, unsafe, and per family;
discards by reason per family; dev_extended counts and database list.
"""
import json
from pathlib import Path
from collections import Counter, defaultdict

with open('data/evaluation_splits/dev_dataset_v1.3.json', encoding='utf-8') as f:
    dev = json.load(f)
with open('data/evaluation_splits/test_dataset_v1.3.json', encoding='utf-8') as f:
    test = json.load(f)
with open('data/evaluation_splits/dev_extended_dataset_v1.3.json', encoding='utf-8') as f:
    ext = json.load(f)

ext_dbs = sorted(list(set(c['database'] for c in ext)))

def analyze_split(cases):
    benign = [c for c in cases if not c.get('gold_sql')]
    unsafe = [c for c in cases if c.get('gold_sql')]
    fam_counts = Counter(c['family_id'] for c in cases)
    dbs = sorted(list(set(c['database'] for c in cases)))
    return {
        'total': len(cases),
        'benign_count': len(benign),
        'unsafe_count': len(unsafe),
        'databases': dbs,
        'family_counts': dict(sorted(fam_counts.items()))
    }

dev_comp = analyze_split(dev)
test_comp = analyze_split(test)
ext_comp = {
    'total': len(ext),
    'databases': ext_dbs,
    'db_count': len(ext_dbs)
}

print(f"DEV: {dev_comp['total']} cases ({dev_comp['benign_count']} benign, {dev_comp['unsafe_count']} unsafe) across {len(dev_comp['databases'])} DBs")
print(f"TEST: {test_comp['total']} cases ({test_comp['benign_count']} benign, {test_comp['unsafe_count']} unsafe) across {len(test_comp['databases'])} DBs")
print(f"DEV_EXTENDED: {ext_comp['total']} cases across {ext_comp['db_count']} DBs")

out_path = 'results/dataset_audit/composition_analysis_results.json'
with open(out_path, 'w', encoding='utf-8') as f:
    json.dump({
        'dev': dev_comp,
        'test': test_comp,
        'dev_extended': ext_comp
    }, f, indent=2)

print(f"Saved composition analysis to {out_path}")

