"""
run_row_count_audit.py
======================
Item 2: Row-count audit: per family, benign vs unsafe, dev and test:
rates of n_matched == 0 and n_changed == 0.
List every family above 5%.
"""
import json
from collections import defaultdict

with open('data/evaluation_splits/dev_dataset_v1.3.json', encoding='utf-8') as f:
    dev = json.load(f)
with open('data/evaluation_splits/test_dataset_v1.3.json', encoding='utf-8') as f:
    test = json.load(f)

def audit_split(cases, split_name):
    by_fam = defaultdict(lambda: {'total': 0, 'm0': 0, 'c0': 0, 'is_unsafe': False})
    for c in cases:
        fid = c['family_id']
        is_u = bool(c.get('gold_sql'))
        by_fam[fid]['total'] += 1
        by_fam[fid]['is_unsafe'] = is_u
        if c.get('n_matched', 0) == 0:
            by_fam[fid]['m0'] += 1
        if c.get('n_changed', 0) == 0:
            by_fam[fid]['c0'] += 1
            
    res = {}
    above_5pct = []
    for fid, d in sorted(by_fam.items()):
        tot = d['total']
        m0_pct = round(100.0 * d['m0'] / tot, 2)
        c0_pct = round(100.0 * d['c0'] / tot, 2)
        is_u = d['is_unsafe']
        res[fid] = {
            'total': tot,
            'is_unsafe': is_u,
            'n_matched_zero': d['m0'],
            'n_matched_zero_pct': m0_pct,
            'n_changed_zero': d['c0'],
            'n_changed_zero_pct': c0_pct
        }
        if m0_pct > 5.0 or c0_pct > 5.0:
            above_5pct.append((fid, is_u, m0_pct, c0_pct, tot))
    return res, above_5pct

dev_audit, dev_above5 = audit_split(dev, 'DEV')
test_audit, test_above5 = audit_split(test, 'TEST')

print(f"=== DEV Families with >5% zero-rows ({len(dev_above5)}) ===")
for fid, is_u, m0p, c0p, tot in dev_above5:
    print(f"  {'[UNSAFE]' if is_u else '[BENIGN]'} {fid:32s}: n_matched==0: {m0p:5.1f}%, n_changed==0: {c0p:5.1f}% (n={tot})")

print(f"\n=== TEST Families with >5% zero-rows ({len(test_above5)}) ===")
for fid, is_u, m0p, c0p, tot in test_above5:
    print(f"  {'[UNSAFE]' if is_u else '[BENIGN]'} {fid:32s}: n_matched==0: {m0p:5.1f}%, n_changed==0: {c0p:5.1f}% (n={tot})")

out_path = 'results/dataset_audit/row_count_audit_results.json'
with open(out_path, 'w', encoding='utf-8') as f:
    json.dump({'dev': dev_audit, 'test': test_audit}, f, indent=2)
print(f"\nSaved row count audit results to {out_path}")

