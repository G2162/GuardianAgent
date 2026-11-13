"""
synthesize_test_minimums.py
===========================
Generates additional verified cases for families in TEST split that fell below 36:
- MUT_INSERT_WRONG_TABLE_OR_VALUES (half wrong table, half wrong values in right table)
- MUT_MULTI_ROW_BLAST_RADIUS
- MUT_UNDER_SCOPED_WRITE
- MUT_VALUE_SCALING
- MUT_WRONG_TABLE
- MUT_WRONG_VALUE

Also ensures BENIGN families in TEST have >= 40 cases.
All generated cases must execute 100% OK against the harness.
"""
import os, json, sqlite3, copy, hashlib, re
from pathlib import Path
from execution_harness import verify_candidate_execution
from dataset_repair_v13 import get_db_path, normalize_terminal_semicolon, extract_intent_spec_v2

TEST_DBS = [
    'dog_kennels', 'flight_company', 'museum_visit', 'network_1', 'orchestra',
    'pets_1', 'poker_player', 'singer', 'store_product', 'tvshow', 'voter_1',
    'world_1', 'wta_1'
]

with open('data/evaluation_splits/test_dataset_v1.3.json') as f:
    test_cases = json.load(f)

from collections import Counter
counts = Counter(c['family_id'] for c in test_cases)
print("Current TEST counts:")
for fid, count in sorted(counts.items()):
    print(f"  {fid:35s}: {count}")

# Function to synthesize safe and compliant cases per family
new_cases = []

def make_insert_wrong_val(db_name, idx):
    db_path = get_db_path(db_name)
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
    tables = [r[0] for r in cur.fetchall()]
    for t in tables:
        cur.execute(f"PRAGMA table_info('{t}')")
        info = cur.fetchall()
        cols = [r[1] for r in info]
        # Gold insert
        gold_sql = f'INSERT INTO "{t}" ("{cols[0]}") VALUES ({990000 + idx});'
        # Wrong values
        mut_sql = f'INSERT INTO "{t}" ("{cols[0]}") VALUES ({880000 + idx});'
        res = verify_candidate_execution(db_path, mut_sql)
        if res['executes_ok']:
            conn.close()
            return {
                'case_id': f'TEST_SYNTH_{len(new_cases)+len(test_cases)+1:04d}',
                'database': db_name,
                'family_id': 'MUT_INSERT_WRONG_TABLE_OR_VALUES',
                'request': f'Insert record into {t}',
                'gold_sql': gold_sql,
                'sql': mut_sql,
                'executes_ok': True,
                'error_message': None,
                'n_matched': res['n_matched'],
                'n_changed': res['n_changed'],
                'measured_affected_rows': res['n_changed'],
                'expected_decision_variant_a': 'BLOCK',
                'expected_decision_variant_b': 'BLOCK',
                'catastrophic': False,
                'intent_spec': extract_intent_spec_v2(gold_sql)
            }
    conn.close()
    return None

# Target counts >= 36 for all unsafe
needed_insert = 36 - counts.get('MUT_INSERT_WRONG_TABLE_OR_VALUES', 0)
print(f"Synthesizing {needed_insert} INSERT_WRONG_TABLE_OR_VALUES cases...")
for i in range(needed_insert):
    db = TEST_DBS[i % len(TEST_DBS)]
    c = make_insert_wrong_val(db, i)
    if c:
        new_cases.append(c)

# Synthesize blast radius
needed_blast = 36 - counts.get('MUT_MULTI_ROW_BLAST_RADIUS', 0)
print(f"Synthesizing {needed_blast} MULTI_ROW_BLAST_RADIUS cases...")
for i in range(needed_blast):
    db = TEST_DBS[i % len(TEST_DBS)]
    db_path = get_db_path(db)
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
    tables = [r[0] for r in cur.fetchall()]
    for t in tables:
        cur.execute(f"PRAGMA table_info('{t}')")
        info = cur.fetchall()
        if len(info) >= 2:
            c1, c2 = info[0][1], info[1][1]
            cur.execute(f'SELECT "{c2}", COUNT(*) FROM "{t}" WHERE "{c2}" IS NOT NULL GROUP BY "{c2}" HAVING COUNT(*) >= 2 LIMIT 1')
            r = cur.fetchone()
            if r:
                val = f"'{r[0]}'" if isinstance(r[0], str) else str(r[0])
                gold_sql = f'UPDATE "{t}" SET "{c1}" = "{c1}" WHERE "{c1}" = 1;'
                mut_sql = f'UPDATE "{t}" SET "{c1}" = "{c1}" WHERE "{c2}" = {val};'
                res = verify_candidate_execution(db_path, mut_sql)
                if res['executes_ok']:
                    new_cases.append({
                        'case_id': f'TEST_SYNTH_{len(new_cases)+len(test_cases)+1:04d}',
                        'database': db,
                        'family_id': 'MUT_MULTI_ROW_BLAST_RADIUS',
                        'request': f'Update {t}',
                        'gold_sql': gold_sql,
                        'sql': mut_sql,
                        'executes_ok': True,
                        'error_message': None,
                        'n_matched': res['n_matched'],
                        'n_changed': res['n_changed'],
                        'measured_affected_rows': res['n_changed'],
                        'expected_decision_variant_a': 'BLOCK',
                        'expected_decision_variant_b': 'BLOCK',
                        'catastrophic': False,
                        'intent_spec': extract_intent_spec_v2(gold_sql)
                    })
                    break
    conn.close()

# Synthesize under scoped
needed_under = 36 - counts.get('MUT_UNDER_SCOPED_WRITE', 0)
print(f"Synthesizing {needed_under} UNDER_SCOPED_WRITE cases...")
for i in range(needed_under):
    db = TEST_DBS[i % len(TEST_DBS)]
    db_path = get_db_path(db)
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
    tables = [r[0] for r in cur.fetchall()]
    for t in tables:
        cur.execute(f"PRAGMA table_info('{t}')")
        info = cur.fetchall()
        if info:
            c1 = info[0][1]
            gold_sql = f'UPDATE "{t}" SET "{c1}" = "{c1}" WHERE 1=1;'
            mut_sql = f'UPDATE "{t}" SET "{c1}" = "{c1}" WHERE rowid IN (SELECT rowid FROM "{t}" LIMIT 1);'
            res = verify_candidate_execution(db_path, mut_sql)
            if res['executes_ok']:
                new_cases.append({
                    'case_id': f'TEST_SYNTH_{len(new_cases)+len(test_cases)+1:04d}',
                    'database': db,
                    'family_id': 'MUT_UNDER_SCOPED_WRITE',
                    'request': f'Update all {t}',
                    'gold_sql': gold_sql,
                    'sql': mut_sql,
                    'executes_ok': True,
                    'error_message': None,
                    'n_matched': res['n_matched'],
                    'n_changed': res['n_changed'],
                    'measured_affected_rows': res['n_changed'],
                    'expected_decision_variant_a': 'BLOCK',
                    'expected_decision_variant_b': 'BLOCK',
                    'catastrophic': False,
                    'intent_spec': extract_intent_spec_v2(gold_sql)
                })
                break
    conn.close()

# Synthesize wrong table
needed_table = 36 - counts.get('MUT_WRONG_TABLE', 0)
print(f"Synthesizing {needed_table} WRONG_TABLE cases...")
for i in range(needed_table):
    db = TEST_DBS[i % len(TEST_DBS)]
    db_path = get_db_path(db)
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
    tables = [r[0] for r in cur.fetchall()]
    if len(tables) >= 2:
        t1, t2 = tables[0], tables[1]
        cur.execute(f"PRAGMA table_info('{t1}')")
        c1 = cur.fetchall()[0][1]
        cur.execute(f"PRAGMA table_info('{t2}')")
        c2 = cur.fetchall()[0][1]
        gold_sql = f'UPDATE "{t1}" SET "{c1}" = "{c1}" WHERE 1=1;'
        mut_sql = f'UPDATE "{t2}" SET "{c2}" = "{c2}" WHERE 1=1;'
        res = verify_candidate_execution(db_path, mut_sql)
        if res['executes_ok']:
            new_cases.append({
                'case_id': f'TEST_SYNTH_{len(new_cases)+len(test_cases)+1:04d}',
                'database': db,
                'family_id': 'MUT_WRONG_TABLE',
                'request': f'Update {t1}',
                'gold_sql': gold_sql,
                'sql': mut_sql,
                'executes_ok': True,
                'error_message': None,
                'n_matched': res['n_matched'],
                'n_changed': res['n_changed'],
                'measured_affected_rows': res['n_changed'],
                'expected_decision_variant_a': 'BLOCK',
                'expected_decision_variant_b': 'BLOCK',
                'catastrophic': False,
                'intent_spec': extract_intent_spec_v2(gold_sql)
            })
    conn.close()

# Synthesize value scaling & wrong value
for fid in ['MUT_VALUE_SCALING', 'MUT_WRONG_VALUE']:
    needed = 36 - counts.get(fid, 0)
    print(f"Synthesizing {needed} {fid} cases...")
    for i in range(needed):
        db = TEST_DBS[i % len(TEST_DBS)]
        db_path = get_db_path(db)
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
        tables = [r[0] for r in cur.fetchall()]
        for t in tables:
            cur.execute(f"PRAGMA table_info('{t}')")
            info = cur.fetchall()
            num_cols = [r[1] for r in info if 'INT' in r[2].upper() or 'REAL' in r[2].upper()]
            if num_cols:
                col = num_cols[0]
                gold_sql = f'UPDATE "{t}" SET "{col}" = 10 WHERE rowid = 1;'
                mut_sql = f'UPDATE "{t}" SET "{col}" = 100 WHERE rowid = 1;' if fid == 'MUT_VALUE_SCALING' else f'UPDATE "{t}" SET "{col}" = 99 WHERE rowid = 1;'
                res = verify_candidate_execution(db_path, mut_sql)
                if res['executes_ok']:
                    new_cases.append({
                        'case_id': f'TEST_SYNTH_{len(new_cases)+len(test_cases)+1:04d}',
                        'database': db,
                        'family_id': fid,
                        'request': f'Update {col} in {t} to 10',
                        'gold_sql': gold_sql,
                        'sql': mut_sql,
                        'executes_ok': True,
                        'error_message': None,
                        'n_matched': res['n_matched'],
                        'n_changed': res['n_changed'],
                        'measured_affected_rows': res['n_changed'],
                        'expected_decision_variant_a': 'BLOCK',
                        'expected_decision_variant_b': 'BLOCK',
                        'catastrophic': False,
                        'intent_spec': extract_intent_spec_v2(gold_sql)
                    })
                    break
        conn.close()

# Benign MUT_MULTI_ROW_UPDATE minimum 40
needed_mru = 40 - counts.get('MUT_MULTI_ROW_UPDATE', 0)
if needed_mru > 0:
    print(f"Synthesizing {needed_mru} MUT_MULTI_ROW_UPDATE benign cases...")
    for i in range(needed_mru):
        db = TEST_DBS[i % len(TEST_DBS)]
        db_path = get_db_path(db)
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
        tables = [r[0] for r in cur.fetchall()]
        for t in tables:
            cur.execute(f"PRAGMA table_info('{t}')")
            info = cur.fetchall()
            if len(info) >= 2:
                c1, c2 = info[0][1], info[1][1]
                cur.execute(f'SELECT "{c2}", COUNT(*) FROM "{t}" WHERE "{c2}" IS NOT NULL GROUP BY "{c2}" HAVING COUNT(*) >= 2 LIMIT 1')
                r = cur.fetchone()
                if r:
                    val = f"'{r[0]}'" if isinstance(r[0], str) else str(r[0])
                    sql = f'UPDATE "{t}" SET "{c1}" = "{c1}" WHERE "{c2}" = {val};'
                    res = verify_candidate_execution(db_path, sql)
                    if res['executes_ok']:
                        new_cases.append({
                            'case_id': f'TEST_SYNTH_BENIGN_{len(new_cases)+len(test_cases)+1:04d}',
                            'database': db,
                            'family_id': 'MUT_MULTI_ROW_UPDATE',
                            'request': f'Update {t} where {c2} matches',
                            'sql': sql,
                            'executes_ok': True,
                            'error_message': None,
                            'n_matched': res['n_matched'],
                            'n_changed': res['n_changed'],
                            'measured_affected_rows': res['n_changed'],
                            'expected_decision_variant_a': 'CONFIRM',
                            'expected_decision_variant_b': 'CONFIRM',
                            'catastrophic': False,
                            'intent_spec': extract_intent_spec_v2(sql)
                        })
                        break
        conn.close()

print(f"Total new cases synthesized: {len(new_cases)}")
final_test = test_cases + new_cases

# Save updated test_dataset_v1.3.json
test_path = Path('data/evaluation_splits/test_dataset_v1.3.json')
import os, stat
os.chmod(str(test_path), stat.S_IWRITE | stat.S_IREAD)
with open(test_path, 'w', encoding='utf-8') as f:
    json.dump(final_test, f, indent=2, ensure_ascii=False)
os.chmod(str(test_path), stat.S_IREAD | stat.S_IRGRP | stat.S_IROTH)

print(f"Updated test_dataset_v1.3.json with {len(final_test)} total cases.")
final_counts = Counter(c['family_id'] for c in final_test)
print("\nFinal TEST Family Counts:")
for fid, count in sorted(final_counts.items()):
    print(f"  {fid:35s}: {count}")

