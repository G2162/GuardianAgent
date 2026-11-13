"""
verify_cases_independent.py
===========================
Independent verification script.
Strict rules:
- Does NOT import execution_harness.py or any generator module.
- Reads sealed JSONs directly.
- Uses raw sqlite3 against data/evaluation_dbs/*.sqlite.
- Tests 100 stratified random cases per split (DEV and TEST) in rolled-back transactions.
- Measures executes_ok, n_matched, n_changed independently.
- Reports any mismatches with the recorded values.
"""
import json, sqlite3, random, re
from pathlib import Path
from collections import defaultdict

random.seed(42)

EVAL_DB_DIR = Path('data/evaluation_dbs')

def run_independent_exec(db_path, sql_str, is_stacked=False, is_ddl=False):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    executes_ok = False
    n_matched = 0
    n_changed = 0
    
    # 1. Parse simple table name and where clause
    table = None
    m_tbl = re.search(r'(?:FROM|INTO|UPDATE|TABLE)\s+"?(\w+)"?', sql_str, re.IGNORECASE)
    if m_tbl:
        table = m_tbl.group(1)
        
    m_where = re.search(r'\sWHERE\s+(.+?)(?:;|\s*$)', sql_str, re.IGNORECASE)
    where_clause = m_where.group(0).rstrip(';') if m_where else ''
    
    # Measure n_matched
    if table and not is_ddl:
        try:
            cnt_sql = f'SELECT COUNT(*) FROM "{table}" {where_clause}' if where_clause else f'SELECT COUNT(*) FROM "{table}"'
            cur.execute(cnt_sql)
            n_matched = cur.fetchone()[0]
        except Exception:
            n_matched = 0

    # Snapshot before
    before_rows = None
    if table and not is_ddl:
        try:
            cur.execute(f'SELECT rowid, * FROM "{table}"')
            before_rows = cur.fetchall()
        except Exception:
            pass

    schema_before = None
    if is_ddl:
        try:
            cur.execute("SELECT type, name, sql FROM sqlite_master")
            schema_before = cur.fetchall()
        except Exception:
            pass

    # Execute inside transaction and rollback
    conn.execute("SAVEPOINT indep_check")
    try:
        if is_stacked:
            stmts = [s.strip() for s in sql_str.split(';') if s.strip()]
            for s in stmts:
                cur.execute(s)
            executes_ok = True
            n_matched = 0
            n_changed = 0
        else:
            cur.execute(sql_str)
            executes_ok = True
            
            if table and before_rows is not None and not is_ddl:
                cur.execute(f'SELECT rowid, * FROM "{table}"')
                after_rows = cur.fetchall()
                b_dict = {r[0]: r[1:] for r in before_rows}
                a_dict = {r[0]: r[1:] for r in after_rows}
                diff = 0
                for rid, vals in a_dict.items():
                    if rid not in b_dict or b_dict[rid] != vals:
                        diff += 1
                for rid in b_dict:
                    if rid not in a_dict:
                        diff += 1
                n_changed = diff
            elif is_ddl:
                cur.execute("SELECT type, name, sql FROM sqlite_master")
                schema_after = cur.fetchall()
                n_changed = 1 if schema_before != schema_after else 0
            else:
                n_changed = cur.rowcount if cur.rowcount >= 0 else 0
    except Exception as e:
        executes_ok = False
    finally:
        conn.execute("ROLLBACK TO SAVEPOINT indep_check")
        conn.execute("RELEASE SAVEPOINT indep_check")
        conn.close()

    return executes_ok, n_matched, n_changed

def verify_split(split_name, json_path):
    print(f"\n=======================================================")
    print(f"Independent Re-Execution Verification: {split_name}")
    print(f"=======================================================")
    with open(json_path, encoding='utf-8') as f:
        cases = json.load(f)

    # Stratified sample of 100 cases
    by_family = defaultdict(list)
    for c in cases:
        by_family[c['family_id']].append(c)

    sample = []
    # Take round-robin across families to reach exactly 100
    fam_keys = sorted(by_family.keys())
    idx = 0
    while len(sample) < 100 and any(by_family.values()):
        k = fam_keys[idx % len(fam_keys)]
        if by_family[k]:
            sample.append(by_family[k].pop(0))
        idx += 1

    print(f"Sampled {len(sample)} stratified cases across {len(fam_keys)} families.")

    mismatches = []
    exec_failures = []

    for i, c in enumerate(sample):
        db_path = EVAL_DB_DIR / f"{c['database']}.sqlite"
        is_stacked = (c['family_id'] == 'MUT_STACKED_SQL')
        is_ddl = c['family_id'] in ('MUT_BENIGN_DDL', 'MUT_UNREQUESTED_DDL_DROP', 'MUT_UNREQUESTED_DDL_ALTER')

        ok, nm, nc = run_independent_exec(db_path, c['sql'], is_stacked=is_stacked, is_ddl=is_ddl)

        if not ok:
            exec_failures.append({
                'case_id': c['case_id'],
                'family_id': c['family_id'],
                'sql': c['sql']
            })

        # Compare with recorded
        rec_ok = c.get('executes_ok', True)
        rec_nm = c.get('n_matched', 0)
        rec_nc = c.get('n_changed', 0)

        # Flag discrepancies
        if ok != rec_ok or nm != rec_nm or nc != rec_nc:
            mismatches.append({
                'case_id': c['case_id'],
                'family_id': c['family_id'],
                'independent': (ok, nm, nc),
                'recorded': (rec_ok, rec_nm, rec_nc),
                'sql': c['sql']
            })

    print(f"Results for {split_name}:")
    print(f"  Execution Failures: {len(exec_failures)} / {len(sample)}")
    print(f"  Recorded Mismatches: {len(mismatches)} / {len(sample)}")
    if mismatches:
        print("  Sample Mismatches:")
        for m in mismatches[:5]:
            print(f"    - {m['case_id']} ({m['family_id']}): indep={m['independent']} vs rec={m['recorded']}")

    return {
        'split': split_name,
        'sample_size': len(sample),
        'exec_failures': exec_failures,
        'mismatches': mismatches
    }

if __name__ == '__main__':
    dev_res = verify_split('DEV', 'data/evaluation_splits/dev_dataset_v1.3.json')
    test_res = verify_split('TEST', 'data/evaluation_splits/test_dataset_v1.3.json')
    
    out_path = 'results/dataset_audit/independent_verification_results.json'
    Path('results/dataset_audit').mkdir(parents=True, exist_ok=True)
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump({'dev': dev_res, 'test': test_res}, f, indent=2)
    print(f"\nSaved independent verification results to {out_path}")
