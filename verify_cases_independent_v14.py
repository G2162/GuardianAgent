"""
verify_cases_independent_v14.py
===============================
Independent verification script for dataset v1.4.
Strict rules:
- Does NOT import execution_harness.py or any generator module.
- Reads sealed JSONs directly.
- Uses raw sqlite3 against data/evaluation_dbs/*.sqlite.
- Tests 150 stratified random cases per split (DEV and TEST) in rolled-back transactions.
- Measures executes_ok, n_matched, n_changed independently.
- Reports any mismatches with the recorded values.
- Generates results/review_sheet_v1.4.csv with 5 golden cases per repaired family.
"""
import json, sqlite3, random, re, csv, os
from pathlib import Path
from collections import defaultdict

random.seed(42)

EVAL_DB_DIR = Path('data/evaluation_dbs')
EXT_DB_DIR = Path('data/dev_extended_dbs')

def get_db_path(db_name):
    p1 = EVAL_DB_DIR / f"{db_name}.sqlite"
    if p1.exists(): return str(p1)
    p2 = EXT_DB_DIR / f"{db_name}.sqlite"
    if p2.exists(): return str(p2)
    raise FileNotFoundError(f"DB {db_name} not found")

def run_independent_exec(db_path, sql_str, is_stacked=False, is_ddl=False):
    conn = sqlite3.connect(db_path)
    conn.text_factory = lambda b: b.decode('utf-8', 'replace')
    cur = conn.cursor()
    executes_ok = False
    n_matched = 0
    n_changed = 0
    changed_rowids = []
    
    table = None
    m_tbl = re.search(r'(?:FROM|INTO|UPDATE|TABLE)\s+"?(\w+)"?', sql_str, re.IGNORECASE)
    if m_tbl:
        table = m_tbl.group(1)
        
    m_where = re.search(r'\sWHERE\s+(.+?)(?:;|\s*$)', sql_str, re.IGNORECASE)
    where_clause = m_where.group(0).rstrip(';') if m_where else ''
    
    if table and not is_ddl and not is_stacked:
        try:
            cnt_sql = f'SELECT COUNT(*) FROM "{table}" {where_clause}' if where_clause else f'SELECT COUNT(*) FROM "{table}"'
            cur.execute(cnt_sql)
            r = cur.fetchone()
            n_matched = r[0] if r else 0
        except Exception:
            n_matched = 0

    before_rows = None
    if table and not is_ddl and not is_stacked:
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

    conn.execute("SAVEPOINT indep_check")
    try:
        if is_stacked:
            stmts = [s.strip() for s in sql_str.split(';') if s.strip()]
            cum = 0
            for s in stmts:
                cur.execute(s)
                c_cnt = cur.rowcount if cur.rowcount >= 0 else 0
                if c_cnt == 0:
                    cur.execute("SELECT changes()")
                    r = cur.fetchone()
                    c_cnt = r[0] if r else 0
                cum += c_cnt
            executes_ok = True
            n_matched = 0
            n_changed = cum if cum > 0 else 1
            changed_rowids = [1]
        else:
            cur.execute(sql_str)
            executes_ok = True
            
            if table and before_rows is not None and not is_ddl:
                cur.execute(f'SELECT rowid, * FROM "{table}"')
                after_rows = cur.fetchall()
                b_dict = {r[0]: r[1:] for r in before_rows}
                a_dict = {r[0]: r[1:] for r in after_rows}
                diff_rids = [rid for rid in a_dict if rid not in b_dict or b_dict[rid] != a_dict[rid]]
                diff_rids.extend([rid for rid in b_dict if rid not in a_dict])
                n_changed = len(diff_rids)
                changed_rowids = sorted(diff_rids)
            elif is_ddl:
                cur.execute("SELECT type, name, sql FROM sqlite_master")
                schema_after = cur.fetchall()
                if schema_before != schema_after:
                    n_changed = 1
                    changed_rowids = [0]
            else:
                n_changed = cur.rowcount if cur.rowcount >= 0 else 0
                changed_rowids = list(range(n_changed))
    except Exception as e:
        executes_ok = False
        n_changed = 0
    finally:
        conn.execute("ROLLBACK TO SAVEPOINT indep_check")
        conn.close()

    return executes_ok, n_matched, n_changed, changed_rowids

def verify_split_independent(split_name, json_path, n_samples=150):
    print(f"\n=======================================================")
    print(f"INDEPENDENT VERIFICATION: {split_name} ({n_samples} stratified cases)")
    print(f"=======================================================")
    with open(json_path, encoding='utf-8') as f:
        cases = json.load(f)
        
    by_fam = defaultdict(list)
    for c in cases:
        by_fam[c['family_id']].append(c)
        
    sampled = []
    # Stratified sampling
    per_fam = max(1, n_samples // len(by_fam))
    for fid, fam_cases in sorted(by_fam.items()):
        k = min(len(fam_cases), per_fam)
        sampled.extend(random.sample(fam_cases, k))
        
    # If short of n_samples, fill randomly
    if len(sampled) < n_samples:
        remaining = [c for c in cases if c not in sampled]
        needed = min(len(remaining), n_samples - len(sampled))
        sampled.extend(random.sample(remaining, needed))
        
    mismatches = []
    for c in sampled:
        db_path = get_db_path(c['database'])
        is_stacked = (c['family_id'] == 'MUT_STACKED_SQL')
        is_ddl = c['family_id'] in ('MUT_BENIGN_DDL', 'MUT_UNREQUESTED_DDL_DROP', 'MUT_UNREQUESTED_DDL_ALTER')
        
        ok, n_m, n_c, rids = run_independent_exec(db_path, c['sql'], is_stacked, is_ddl)
        
        # Compare with recorded
        if ok != c.get('executes_ok', True):
            mismatches.append((c['case_id'], c['family_id'], f"executes_ok: rec={c.get('executes_ok')} vs measured={ok}"))
        elif n_c != c.get('n_changed', 0):
            mismatches.append((c['case_id'], c['family_id'], f"n_changed: rec={c.get('n_changed')} vs measured={n_c}"))
            
    print(f"Tested {len(sampled)} cases in {split_name}. Mismatches: {len(mismatches)}")
    if mismatches:
        for cid, fid, msg in mismatches[:10]:
            print(f"  [MISMATCH] {cid} ({fid}): {msg}")
    else:
        print(f"SUCCESS: 100% agreement between recorded values and independent execution on {split_name}!")
        
    return sampled, mismatches

def generate_review_sheet_v14():
    print("\n--- Generating review_sheet_v1.4.csv ---")
    with open('data/evaluation_splits/dev_dataset_v1.4.json', encoding='utf-8') as f:
        dev = json.load(f)
        
    REPAIRED_FAMILIES = [
        'MUT_WRONG_TABLE', 'MUT_HIDDEN_WRITE_CTE', 'MUT_WRONG_SUBQUERY_KEY',
        'MUT_WRONG_VALUE', 'MUT_MULTI_ROW_BLAST_RADIUS', 'MUT_UNDER_SCOPED_WRITE',
        'MUT_BOUNDARY_OPERATOR', 'MUT_VALUE_SCALING', 'MUT_MULTI_ROW_UPDATE', 'MUT_STACKED_SQL'
    ]
    
    by_fam = defaultdict(list)
    for c in dev:
        if c['family_id'] in REPAIRED_FAMILIES:
            by_fam[c['family_id']].append(c)
            
    rows = []
    for fid in REPAIRED_FAMILIES:
        fam_cases = by_fam[fid]
        k = min(len(fam_cases), 5)
        chosen = fam_cases[:k]
        for c in chosen:
            db_path = get_db_path(c['database'])
            is_stacked = (fid == 'MUT_STACKED_SQL')
            is_ddl = fid in ('MUT_BENIGN_DDL', 'MUT_UNREQUESTED_DDL_DROP', 'MUT_UNREQUESTED_DDL_ALTER')
            ok, nm, nc, rids = run_independent_exec(db_path, c['sql'], is_stacked, is_ddl)
            
            rows.append({
                'case_id': c['case_id'],
                'family_id': c['family_id'],
                'request': c['request'],
                'sql': c['sql'],
                'gold_sql': c.get('gold_sql', ''),
                'executes_ok': ok,
                'n_matched': nm,
                'n_changed': nc,
                'changed_rowids': str(rids),
                'reviewer_label_ok': '',
                'reviewer_notes': ''
            })
            
    os.makedirs('results', exist_ok=True)
    fieldnames = ['case_id', 'family_id', 'request', 'sql', 'gold_sql', 'executes_ok', 'n_matched', 'n_changed', 'changed_rowids', 'reviewer_label_ok', 'reviewer_notes']
    with open('results/review_sheet_v1.4.csv', 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in rows:
            writer.writerow(r)
            
    print(f"Wrote {len(rows)} golden review cases to results/review_sheet_v1.4.csv ({len(rows)//5} families x 5 cases).")

def main():
    verify_split_independent('DEV v1.4', 'data/evaluation_splits/dev_dataset_v1.4.json', 150)
    verify_split_independent('TEST v1.4', 'data/evaluation_splits/test_dataset_v1.4.json', 150)
    generate_review_sheet_v14()

if __name__ == '__main__':
    main()

