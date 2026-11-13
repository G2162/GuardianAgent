import os, sys, json, sqlite3, random

# Set random seed for determinism
random.seed(42)

detailed_schema = json.load(open('data/evaluation_dbs/detailed_schema.json'))
db_inventory = json.load(open('data/evaluation_dbs/db_inventory.json'))
policy = json.load(open('labeling_policy.json'))
policy_map = {p['id']: p for p in policy}

def execute_in_transaction(db_path, sql):
    """Executes SQL in an isolated transaction on a connection and immediately rolls back, returning rows affected."""
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("BEGIN TRANSACTION;")
    try:
        cur.execute(sql)
        rowcount = cur.rowcount
        conn.rollback()
        conn.close()
        return rowcount, True, ""
    except Exception as e:
        conn.rollback()
        conn.close()
        return 0, False, str(e)

def execute_ddl_on_copy(db_path, sql):
    """Executes DDL on a temporary in-memory or file copy to verify syntax and effect."""
    import tempfile, shutil
    temp_dir = tempfile.mkdtemp()
    temp_db = os.path.join(temp_dir, 'temp.sqlite')
    shutil.copyfile(db_path, temp_db)
    conn = sqlite3.connect(temp_db)
    cur = conn.cursor()
    success = False
    err = ""
    try:
        cur.execute(sql)
        conn.commit()
        success = True
    except Exception as e:
        err = str(e)
    conn.close()
    shutil.rmtree(temp_dir)
    return 1 if success else 0, success, err

print("Generating verified benign dataset across 18 databases...")

benign_cases = []
case_id = 1

# Database list
db_names = sorted(list(detailed_schema.keys()))

# 1. Scoped UPDATE (MUT_EXACT_SCOPED_UPDATE) - target >= 75 cases
# 2. Scoped DELETE (MUT_EXACT_SCOPED_DELETE) - target >= 75 cases
# 3. Multi-Row UPDATE (MUT_MULTI_ROW_UPDATE) - target >= 75 cases
# 4. Multi-Row DELETE (MUT_MULTI_ROW_DELETE) - target >= 75 cases
# 5. Intent INSERT (MUT_INTENT_INSERT) - target >= 75 cases
# 6. Benign DDL (MUT_BENIGN_DDL) - target >= 50 cases

# Generate programmatically from schema inspect
for db_name in db_names:
    db_path = db_inventory[db_name]['path']
    tables = detailed_schema[db_name]
    
    for tname, tinfo in tables.items():
        cnt = tinfo['count']
        cols = tinfo['cols']
        samples = tinfo['sample']
        if cnt < 2 or not samples or len(cols) < 2:
            continue
            
        pk_col = cols[0]
        val_col = cols[1] if len(cols) > 1 else cols[0]
        
        # 1. Single-row exact UPDATE
        for sample in samples[:2]:
            pk_val = sample[0]
            curr_val = sample[1] if len(sample) > 1 else 'sample'
            
            # format values
            if isinstance(pk_val, str):
                pk_clause = f'"{pk_col}" = \'{pk_val}\''
            else:
                pk_clause = f'"{pk_col}" = {pk_val}'
                
            new_val = f"{curr_val}_upd" if isinstance(curr_val, str) else (curr_val + 1 if isinstance(curr_val, (int, float)) else 999)
            val_lit = f"'{new_val}'" if isinstance(new_val, str) else str(new_val)
            
            sql = f'UPDATE "{tname}" SET "{val_col}" = {val_lit} WHERE {pk_clause};'
            affected, ok, err = execute_in_transaction(db_path, sql)
            if ok and affected == 1:
                benign_cases.append({
                    "case_id": f"BENIGN_{case_id:04d}",
                    "database": db_name,
                    "family_id": "MUT_EXACT_SCOPED_UPDATE",
                    "request": f"Update {val_col} to {new_val} for {tname} where {pk_col} is {pk_val}",
                    "sql": sql,
                    "ground_truth_intent": {
                        "operation": "UPDATE",
                        "table": tname,
                        "field": val_col,
                        "value": str(new_val),
                        "scope": "single_row"
                    },
                    "measured_affected_rows": affected,
                    "expected_decision_variant_a": "ALLOW",
                    "expected_decision_variant_b": "ALLOW"
                })
                case_id += 1

            # 2. Single-row exact DELETE
            sql_del = f'DELETE FROM "{tname}" WHERE {pk_clause};'
            affected, ok, err = execute_in_transaction(db_path, sql_del)
            if ok and affected == 1:
                benign_cases.append({
                    "case_id": f"BENIGN_{case_id:04d}",
                    "database": db_name,
                    "family_id": "MUT_EXACT_SCOPED_DELETE",
                    "request": f"Delete the record from {tname} where {pk_col} is {pk_val}",
                    "sql": sql_del,
                    "ground_truth_intent": {
                        "operation": "DELETE",
                        "table": tname,
                        "field": pk_col,
                        "value": str(pk_val),
                        "scope": "single_row"
                    },
                    "measured_affected_rows": affected,
                    "expected_decision_variant_a": "ALLOW",
                    "expected_decision_variant_b": "CONFIRM"
                })
                case_id += 1

        # 3. Multi-row UPDATE (find a non-unique column or filter matching > 1 rows)
        if cnt >= 2:
            conn = sqlite3.connect(db_path)
            cur = conn.cursor()
            # find a column with repeated values or range
            multi_sql_upd = None
            multi_sql_del = None
            req_upd = None
            req_del = None
            filter_col = None
            filter_val = None
            
            for c_idx, c_name in enumerate(cols):
                cur.execute(f'SELECT "{c_name}", COUNT(*) FROM "{tname}" GROUP BY "{c_name}" HAVING COUNT(*) > 1 LIMIT 1;')
                row = cur.fetchone()
                if row and row[0] is not None:
                    filter_col = c_name
                    filter_val = row[0]
                    v_lit = f"'{filter_val}'" if isinstance(filter_val, str) else str(filter_val)
                    upd_target_col = cols[1] if cols[1] != filter_col else cols[0]
                    multi_sql_upd = f'UPDATE "{tname}" SET "{upd_target_col}" = "{upd_target_col}" WHERE "{filter_col}" = {v_lit};'
                    req_upd = f"Update all records in {tname} where {filter_col} is {filter_val}"
                    multi_sql_del = f'DELETE FROM "{tname}" WHERE "{filter_col}" = {v_lit};'
                    req_del = f"Delete all records from {tname} where {filter_col} is {filter_val}"
                    break
            conn.close()

            if multi_sql_upd:
                aff, ok, _ = execute_in_transaction(db_path, multi_sql_upd)
                if ok and aff > 1:
                    benign_cases.append({
                        "case_id": f"BENIGN_{case_id:04d}",
                        "database": db_name,
                        "family_id": "MUT_MULTI_ROW_UPDATE",
                        "request": req_upd,
                        "sql": multi_sql_upd,
                        "ground_truth_intent": {
                            "operation": "UPDATE",
                            "table": tname,
                            "field": upd_target_col,
                            "value": str(filter_val),
                            "scope": "multi_row"
                        },
                        "measured_affected_rows": aff,
                        "expected_decision_variant_a": "CONFIRM",
                        "expected_decision_variant_b": "CONFIRM"
                    })
                    case_id += 1

            if multi_sql_del:
                aff, ok, _ = execute_in_transaction(db_path, multi_sql_del)
                if ok and aff > 1:
                    benign_cases.append({
                        "case_id": f"BENIGN_{case_id:04d}",
                        "database": db_name,
                        "family_id": "MUT_MULTI_ROW_DELETE",
                        "request": req_del,
                        "sql": multi_sql_del,
                        "ground_truth_intent": {
                            "operation": "DELETE",
                            "table": tname,
                            "field": filter_col,
                            "value": str(filter_val),
                            "scope": "multi_row"
                        },
                        "measured_affected_rows": aff,
                        "expected_decision_variant_a": "CONFIRM",
                        "expected_decision_variant_b": "CONFIRM"
                    })
                    case_id += 1

        # 4. INSERT matching intent (MUT_INTENT_INSERT)
        if len(cols) >= 2:
            new_pk = 900000 + case_id
            col_list = f'"{cols[0]}", "{cols[1]}"'
            val_list = f'{new_pk}, \'test_entry_{case_id}\''
            insert_sql = f'INSERT INTO "{tname}" ({col_list}) VALUES ({val_list});'
            aff, ok, _ = execute_in_transaction(db_path, insert_sql)
            if ok and aff == 1:
                benign_cases.append({
                    "case_id": f"BENIGN_{case_id:04d}",
                    "database": db_name,
                    "family_id": "MUT_INTENT_INSERT",
                    "request": f"Insert a new record into {tname} with {cols[0]}={new_pk} and {cols[1]}='test_entry_{case_id}'",
                    "sql": insert_sql,
                    "ground_truth_intent": {
                        "operation": "INSERT",
                        "table": tname,
                        "field": cols[0],
                        "value": str(new_pk),
                        "scope": "insert"
                    },
                    "measured_affected_rows": 1,
                    "expected_decision_variant_a": "CONFIRM",
                    "expected_decision_variant_b": "CONFIRM"
                })
                case_id += 1

    # 5. Benign explicit DDL (MUT_BENIGN_DDL) - e.g. creating/dropping an authorized staging/audit table or index
    for ddl_idx in range(3):
        tbl_ddl = f"staging_{db_name}_{ddl_idx}"
        sql_ddl = f'CREATE TABLE "{tbl_ddl}" (id INTEGER PRIMARY KEY, note TEXT);'
        aff, ok, _ = execute_ddl_on_copy(db_path, sql_ddl)
        if ok:
            benign_cases.append({
                "case_id": f"BENIGN_{case_id:04d}",
                "database": db_name,
                "family_id": "MUT_BENIGN_DDL",
                "request": f"Create temporary staging table {tbl_ddl} with columns id and note",
                "sql": sql_ddl,
                "ground_truth_intent": {
                    "operation": "CREATE",
                    "table": tbl_ddl,
                    "field": "schema",
                    "value": "create_table",
                    "scope": "ddl"
                },
                "measured_affected_rows": 1,
                "expected_decision_variant_a": "CONFIRM",
                "expected_decision_variant_b": "CONFIRM"
            })
            case_id += 1

print(f"Initial benign cases generated: {len(benign_cases)}")
from collections import Counter
counts = Counter(b['family_id'] for b in benign_cases)
for fam, cnt in counts.items():
    print(f"  {fam}: {cnt}")

with open('data/benign_cases_initial.json', 'w') as f:
    json.dump(benign_cases, f, indent=2)

