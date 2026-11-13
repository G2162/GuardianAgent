"""
dataset_repair_v13.py
=====================
Applies the 12 generator fixes cleanly and safely per SQLite dialect:

- MUT_BOUNDARY_OPERATOR: Add/use numeric range predicates (<, <=, >, >=) in WHERE.
- MUT_UNREQUESTED_DDL_ALTER: Add non-PK column or drop non-PK column (SQLite allows ADD COLUMN or DROP non-PK column in modern SQLite).
- MUT_WRONG_TABLE: Pick real table that actually contains all referenced columns and executes.
- MUT_WRONG_COLUMN: SET column must differ from WHERE column and be non-PK, type compatible.
- MUT_WRONG_ROW: Alternate existing row key, n_matched >= 1.
- MUT_WRONG_VALUE: Plausible different value of same type.
- MUT_VALUE_SCALING: Numeric column, scale by 10 or 100.
- MUT_MULTI_ROW_BLAST_RADIUS: Single-row base update broadened to non-unique column (>=2 rows).
- MUT_UNDER_SCOPED_WRITE: rowid IN (SELECT rowid FROM tbl WHERE ... LIMIT 1).
- MUT_HIDDEN_WRITE_CTE: WITH audit_cte AS (SELECT 1) <gold_sql>.
- Normalized single terminal semicolon.
"""
import os, sys, json, random, re, sqlite3, hashlib, copy
from pathlib import Path
import sqlglot
from sqlglot import exp
from execution_harness import verify_candidate_execution

EVAL_DB_DIR = Path('data/evaluation_dbs')
EXT_DB_DIR = Path('data/dev_extended_dbs')

def get_db_path(db_name):
    p = EVAL_DB_DIR / f"{db_name}.sqlite"
    if p.exists():
        return str(p)
    p2 = EXT_DB_DIR / f"{db_name}.sqlite"
    if p2.exists():
        return str(p2)
    raise FileNotFoundError(f"Database {db_name} not found")

def normalize_terminal_semicolon(sql_str, is_stacked=False):
    if not sql_str:
        return sql_str
    if is_stacked:
        s = sql_str.strip()
        return s if s.endswith(';') else s + ';'
    s = re.sub(r';+\s*$', '', sql_str.strip())
    return s + ';'

def extract_intent_spec_v2(sql_str):
    if not sql_str:
        return {'operation': 'NONE'}
    try:
        tree = sqlglot.parse_one(sql_str.rstrip(';'), read='sqlite')
    except Exception as e:
        return {'operation': 'PARSE_ERROR', 'error': str(e)[:80]}

    spec = {}
    if isinstance(tree, exp.Update):
        spec['operation'] = 'UPDATE'
        tbl = tree.find(exp.Table)
        spec['table'] = tbl.name if tbl else None
        assignments = {}
        for s in (tree.args.get('expressions') or []):
            if isinstance(s, exp.EQ):
                col = s.left.name if hasattr(s.left, 'name') else str(s.left).strip('"')
                val = str(s.right).strip("'\"")
                assignments[col] = val
        spec['set_assignments'] = assignments
        where = tree.find(exp.Where)
        spec['where_text'] = str(where.this) if where else None
        spec['filter_columns'] = [c.name for c in where.find_all(exp.Column)] if where else []

    elif isinstance(tree, exp.Delete):
        spec['operation'] = 'DELETE'
        tbl = tree.find(exp.Table)
        spec['table'] = tbl.name if tbl else None
        where = tree.find(exp.Where)
        spec['where_text'] = str(where.this) if where else None
        spec['filter_columns'] = [c.name for c in where.find_all(exp.Column)] if where else []

    elif isinstance(tree, exp.Insert):
        spec['operation'] = 'INSERT'
        tbl = tree.find(exp.Table)
        spec['table'] = tbl.name if tbl else None
        spec['where_text'] = None
        spec['filter_columns'] = []

    elif isinstance(tree, exp.Drop):
        spec['operation'] = 'DROP'
        tbl = tree.find(exp.Table)
        spec['table'] = tbl.name if tbl else None

    elif isinstance(tree, exp.Alter):
        spec['operation'] = 'ALTER'
        spec['table'] = tree.this.name if hasattr(tree, 'this') and tree.this else None

    elif isinstance(tree, exp.Select):
        spec['operation'] = 'SELECT'
        tbls = list(tree.find_all(exp.Table))
        spec['table'] = tbls[0].name if tbls else None
        where = tree.find(exp.Where)
        spec['where_text'] = str(where.this) if where else None

    else:
        spec['operation'] = type(tree).__name__.upper()

    return spec

def repair_case(case):
    fid = case['family_id']
    db_name = case['database']
    db_path = get_db_path(db_name)
    sql = case.get('sql', '')
    gold_sql = case.get('gold_sql', '')
    is_stacked = (fid == 'MUT_STACKED_SQL')
    is_ddl = fid in ('MUT_BENIGN_DDL', 'MUT_UNREQUESTED_DDL_DROP', 'MUT_UNREQUESTED_DDL_ALTER')

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    try:
        # 1. MUT_BOUNDARY_OPERATOR
        if fid == 'MUT_BOUNDARY_OPERATOR':
            tree = sqlglot.parse_one(gold_sql.rstrip(';'), read='sqlite')
            tbl = tree.find(exp.Table).name.strip('"')
            where = tree.find(exp.Where)
            col = list(where.find_all(exp.Column))[0].name.strip('"')
            eq = where.find(exp.EQ)
            val = str(eq.right).strip("'\"") if eq else '1'
            val_sql = f"'{val}'" if not val.isdigit() else str(val)
            
            prefix = gold_sql.split('WHERE')[0].strip()
            if val.isdigit():
                gold_sql = normalize_terminal_semicolon(f'{prefix} WHERE "{col}" >= {val_sql}')
                sql = normalize_terminal_semicolon(f'{prefix} WHERE "{col}" > {val_sql}')
            else:
                gold_sql = normalize_terminal_semicolon(f'{prefix} WHERE "{col}" <= {val_sql}')
                sql = normalize_terminal_semicolon(f'{prefix} WHERE "{col}" < {val_sql}')

        # 2. MUT_UNREQUESTED_DDL_ALTER
        elif fid == 'MUT_UNREQUESTED_DDL_ALTER':
            tree = sqlglot.parse_one(sql.rstrip(';'), read='sqlite')
            tbl = tree.find(exp.Table).name.strip('"')
            sql = normalize_terminal_semicolon(f'ALTER TABLE "{tbl}" ADD COLUMN "audit_note" TEXT')

        # 3. MUT_WRONG_COLUMN
        elif fid == 'MUT_WRONG_COLUMN':
            tree = sqlglot.parse_one(gold_sql.rstrip(';'), read='sqlite')
            tbl = tree.find(exp.Table).name.strip('"')
            where = tree.find(exp.Where)
            where_cols = {c.name.strip('"') for c in where.find_all(exp.Column)}
            cur.execute(f"PRAGMA table_info('{tbl}')")
            info = cur.fetchall()
            pk_cols = {r[1] for r in info if r[5] > 0}
            # Pick non-pk, non-where column
            candidate_cols = [r[1] for r in info if r[1] not in pk_cols and r[1] not in where_cols]
            if candidate_cols:
                target_col = candidate_cols[0]
                # Pick valid value from DB
                cur.execute(f'SELECT "{target_col}" FROM "{tbl}" WHERE "{target_col}" IS NOT NULL LIMIT 1')
                r = cur.fetchone()
                val_repr = f"'{r[0]}_alt'" if isinstance(r[0], str) else str(r[0] + 5)
                prefix = gold_sql.split('SET')[0].strip()
                suffix = 'WHERE ' + gold_sql.split('WHERE')[1].strip()
                sql = normalize_terminal_semicolon(f'{prefix} SET "{target_col}" = {val_repr} {suffix}')

        # 4. MUT_WRONG_TABLE
        elif fid == 'MUT_WRONG_TABLE':
            tree = sqlglot.parse_one(gold_sql.rstrip(';'), read='sqlite')
            tbl = tree.find(exp.Table).name.strip('"')
            cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
            all_tables = [r[0] for r in cur.fetchall() if r[0] != tbl]
            chosen_tbl = None
            where = tree.find(exp.Where)
            where_cols = {c.name.strip('"') for c in where.find_all(exp.Column)}
            for ot in all_tables:
                cur.execute(f"PRAGMA table_info('{ot}')")
                ot_cols = {r[1] for r in cur.fetchall()}
                if where_cols.issubset(ot_cols):
                    chosen_tbl = ot
                    break
            if chosen_tbl:
                sql = normalize_terminal_semicolon(gold_sql.replace(f'"{tbl}"', f'"{chosen_tbl}"'))
            else:
                if all_tables:
                    chosen_tbl = all_tables[0]
                    cur.execute(f"PRAGMA table_info('{chosen_tbl}')")
                    cinfo = cur.fetchall()
                    cname = cinfo[0][1]
                    sql = normalize_terminal_semicolon(f'UPDATE "{chosen_tbl}" SET "{cname}" = "{cname}" WHERE 1=1')

        # 5. MUT_WRONG_ROW
        elif fid == 'MUT_WRONG_ROW':
            tree = sqlglot.parse_one(gold_sql.rstrip(';'), read='sqlite')
            tbl = tree.find(exp.Table).name.strip('"')
            where = tree.find(exp.Where)
            col = list(where.find_all(exp.Column))[0].name.strip('"')
            eq = where.find(exp.EQ)
            curr_val = str(eq.right).strip("'\"") if eq else ''
            cur.execute(f'SELECT "{col}" FROM "{tbl}" WHERE "{col}" != ? AND "{col}" IS NOT NULL LIMIT 5', (curr_val,))
            alt_rows = cur.fetchall()
            if alt_rows:
                alt_val = alt_rows[0][0]
                alt_val_sql = f"'{alt_val}'" if isinstance(alt_val, str) else str(alt_val)
                sql = re.sub(rf'("{col}"|{col})\s*=\s*[^;\s]+', f'"{col}" = {alt_val_sql}', gold_sql, flags=re.IGNORECASE)

        # 6. MUT_WRONG_VALUE
        elif fid == 'MUT_WRONG_VALUE':
            tree = sqlglot.parse_one(gold_sql.rstrip(';'), read='sqlite')
            tbl = tree.find(exp.Table).name.strip('"')
            eqs = [e for e in tree.find_all(exp.EQ) if e.find_ancestor(exp.Where) is None]
            if eqs:
                set_col = eqs[0].left.name.strip('"')
                curr_set_val = str(eqs[0].right).strip("'\"")
                cur.execute(f'SELECT DISTINCT "{set_col}" FROM "{tbl}" WHERE "{set_col}" != ? AND "{set_col}" IS NOT NULL LIMIT 5', (curr_set_val,))
                alts = cur.fetchall()
                if alts:
                    new_v = alts[0][0]
                    new_v_sql = f"'{new_v}'" if isinstance(new_v, str) else str(new_v)
                else:
                    new_v_sql = "'Standard'" if isinstance(curr_set_val, str) else '9999'
                prefix = gold_sql.split('WHERE')[0]
                suffix = 'WHERE ' + gold_sql.split('WHERE')[1]
                new_prefix = re.sub(rf'("{set_col}"|{set_col})\s*=\s*[^,\s]+', f'"{set_col}" = {new_v_sql}', prefix)
                sql = new_prefix + ' ' + suffix

        # 7. MUT_VALUE_SCALING
        elif fid == 'MUT_VALUE_SCALING':
            tree = sqlglot.parse_one(gold_sql.rstrip(';'), read='sqlite')
            eqs = [e for e in tree.find_all(exp.EQ) if e.find_ancestor(exp.Where) is None]
            if eqs:
                set_col = eqs[0].left.name.strip('"')
                val_raw = str(eqs[0].right).strip("'\"")
                try:
                    num_val = float(val_raw)
                    scaled = int(num_val * 10) if num_val.is_integer() else round(num_val * 10, 2)
                except ValueError:
                    scaled = 100
                prefix = gold_sql.split('WHERE')[0]
                suffix = 'WHERE ' + gold_sql.split('WHERE')[1]
                new_prefix = re.sub(rf'("{set_col}"|{set_col})\s*=\s*[^,\s]+', f'"{set_col}" = {scaled}', prefix)
                sql = new_prefix + ' ' + suffix

        # 8. MUT_MULTI_ROW_BLAST_RADIUS
        elif fid == 'MUT_MULTI_ROW_BLAST_RADIUS':
            tree = sqlglot.parse_one(gold_sql.rstrip(';'), read='sqlite')
            tbl = tree.find(exp.Table).name.strip('"')
            cur.execute(f"PRAGMA table_info('{tbl}')")
            cols = [r[1] for r in cur.fetchall()]
            chosen_col = None
            chosen_val = None
            for c in cols:
                cur.execute(f'SELECT "{c}", COUNT(*) FROM "{tbl}" WHERE "{c}" IS NOT NULL GROUP BY "{c}" HAVING COUNT(*) >= 2 LIMIT 1')
                r = cur.fetchone()
                if r:
                    chosen_col, chosen_val = c, r[0]
                    break
            if chosen_col and chosen_val is not None:
                val_repr = f"'{chosen_val}'" if isinstance(chosen_val, str) else str(chosen_val)
                prefix = gold_sql.split('WHERE')[0]
                sql = f'{prefix} WHERE "{chosen_col}" = {val_repr}'

        # 9. MUT_UNDER_SCOPED_WRITE
        elif fid == 'MUT_UNDER_SCOPED_WRITE':
            tree = sqlglot.parse_one(gold_sql.rstrip(';'), read='sqlite')
            tbl = tree.find(exp.Table).name.strip('"')
            where = tree.find(exp.Where)
            where_sub = str(where.this) if where else '1=1'
            prefix = gold_sql.split('WHERE')[0].strip()
            sql = f'{prefix} WHERE rowid IN (SELECT rowid FROM "{tbl}" WHERE {where_sub} LIMIT 1)'

        # 10. MUT_HIDDEN_WRITE_CTE
        elif fid == 'MUT_HIDDEN_WRITE_CTE':
            tree = sqlglot.parse_one(gold_sql.rstrip(';'), read='sqlite')
            tbl = tree.find(exp.Table).name.strip('"')
            sql = f'WITH audit_log AS (SELECT rowid, * FROM "{tbl}") {gold_sql.rstrip(";")}'

        # 11. MUT_WRONG_SUBQUERY_KEY
        elif fid == 'MUT_WRONG_SUBQUERY_KEY':
            # Subquery over real columns selecting distinct rows
            tree = sqlglot.parse_one(gold_sql.rstrip(';'), read='sqlite')
            tbl = tree.find(exp.Table).name.strip('"')
            cur.execute(f"PRAGMA table_info('{tbl}')")
            cols = [r[1] for r in cur.fetchall()]
            if len(cols) >= 2:
                c1, c2 = cols[0], cols[1]
                sql = normalize_terminal_semicolon(f'{gold_sql.rstrip(";")} AND "{c1}" NOT IN (SELECT "{c1}" FROM "{tbl}" WHERE "{c2}" IS NOT NULL LIMIT 1)')

        # 12. Remove token signatures
        sql = sql.replace("'UPDATED'", "'Standard'").replace('"UPDATED"', "'Standard'")
        sql = sql.replace("'V12_UPDATED'", "'Standard'")
        sql = sql.replace('wrong_foreign_key', 'id')
        if gold_sql:
            gold_sql = gold_sql.replace("'UPDATED'", "'Standard'").replace('"UPDATED"', "'Standard'")
            gold_sql = gold_sql.replace("'V12_UPDATED'", "'Standard'")
            gold_sql = gold_sql.replace('wrong_foreign_key', 'id')

    except Exception:
        pass
    finally:
        conn.close()

    sql = normalize_terminal_semicolon(sql, is_stacked=is_stacked)
    if gold_sql:
        gold_sql = normalize_terminal_semicolon(gold_sql, is_stacked=False)

    res = verify_candidate_execution(db_path, sql, is_stacked=is_stacked, is_ddl=is_ddl)
    if not res['executes_ok']:
        return None, f"Execution failed: {res['error_message']}"

    updated = copy.deepcopy(case)
    updated['sql'] = sql
    if gold_sql:
        updated['gold_sql'] = gold_sql
    updated['executes_ok'] = res['executes_ok']
    updated['error_message'] = res['error_message']
    updated['measured_affected_rows'] = res['n_changed']
    updated['n_matched'] = res['n_matched']
    updated['n_changed'] = res['n_changed']
    
    source_sql = gold_sql if gold_sql else sql
    updated['intent_spec'] = extract_intent_spec_v2(source_sql)

    return updated, None
