"""
guardian_layer2.py
==================
Layer 2: Effect Check Engine.

Executes candidate statements in an isolated, rolled-back transaction on a copy/savepoint
of the database to observe actual state effects:
  - executes_ok: bool
  - error_message: str or None
  - n_matched: rows matching target predicate before execution
  - n_changed: rows actually altered (value diff) or affected
  - is_timeout: whether execution exceeded the 500 ms safety threshold
  - schema_changed: whether schema was modified

NOTE / IMPORTANT METHODOLOGICAL STATEMENT:
State in code comments and in the results that the labeling policy also uses
measured effects (n_matched, n_changed, executes_ok), so this layer is partly
circular with ground truth. In GuardianAgent v2, Layer 2 serves as a safety filter
and cardinality verifier. Any timeout (>500 ms) fails closed to CONFIRM (counted in R_timeout).
"""
import sqlite3
import time
import sqlglot
from sqlglot import exp

class TimeoutException(Exception):
    pass

def check_layer2_effect(db_path, sql_str, timeout_ms=500):
    """
    Executes sql_str on db_path in a rolled-back transaction.
    Enforces a strict timeout (default 500ms).
    """
    result = {
        'executes_ok': False,
        'error_message': None,
        'n_matched': 0,
        'n_changed': 0,
        'schema_changed': False,
        'is_timeout': False,
        'elapsed_ms': 0.0,
        'decision': None,
        'reason': None
    }

    if not sql_str or not sql_str.strip():
        result['error_message'] = "Empty SQL"
        return result

    start_time = time.perf_counter()

    try:
        conn = sqlite3.connect(db_path, timeout=timeout_ms / 1000.0)
    except Exception as e:
        result['error_message'] = f"DB Connection error: {e}"
        result['decision'] = "CONFIRM"
        result['reason'] = f"Failed to connect to DB: {e}"
        return result

    deadline = time.perf_counter() + (timeout_ms / 1000.0)
    
    def progress_callback():
        if time.perf_counter() > deadline:
            return 1 # Non-zero aborts query
        return 0

    conn.set_progress_handler(progress_callback, 1000)

    try:
        cur = conn.cursor()
        
        clean_sql = sql_str.strip().rstrip(';')
        table_name = None
        where_clause_str = None
        is_write = False
        
        try:
            tree = sqlglot.parse_one(clean_sql, read='sqlite')
            if isinstance(tree, (exp.Update, exp.Delete, exp.Insert, exp.Drop, exp.Alter)):
                is_write = True
            tbl_node = tree.find(exp.Table)
            if tbl_node:
                table_name = tbl_node.name.strip('"')
            where_node = tree.find(exp.Where)
            if where_node:
                where_clause_str = str(where_node)
        except Exception:
            upper = clean_sql.upper()
            is_write = any(w in upper for w in ('UPDATE', 'DELETE', 'INSERT', 'DROP', 'ALTER'))

        # Check pre-execution schema
        cur.execute("SELECT name, sql FROM sqlite_master WHERE type='table'")
        schema_before = dict(cur.fetchall())

        # Measure n_matched if table and WHERE exist
        if table_name and table_name in schema_before:
            if where_clause_str:
                try:
                    cnt_cur = cur.execute(f'SELECT COUNT(*) FROM "{table_name}" {where_clause_str}')
                    result['n_matched'] = cnt_cur.fetchone()[0]
                except Exception:
                    result['n_matched'] = 0
            elif not clean_sql.upper().startswith(('CREATE', 'DROP', 'ALTER')):
                try:
                    cnt_cur = cur.execute(f'SELECT COUNT(*) FROM "{table_name}"')
                    result['n_matched'] = cnt_cur.fetchone()[0]
                except Exception:
                    result['n_matched'] = 0

        # Snapshot rows targeted by WHERE (or table if small) before mutation
        rows_before = {}
        if table_name and table_name in schema_before:
            try:
                if where_clause_str:
                    cur.execute(f'SELECT rowid, * FROM "{table_name}" {where_clause_str}')
                else:
                    cur.execute(f'SELECT rowid, * FROM "{table_name}" LIMIT 5000')
                for r in cur.fetchall():
                    rows_before[r[0]] = r[1:]
            except Exception:
                pass

        cur.execute("SAVEPOINT l2_effect_check")
        try:
            cur.execute(clean_sql)
            result['executes_ok'] = True
            
            cur.execute("SELECT name, sql FROM sqlite_master WHERE type='table'")
            schema_after = dict(cur.fetchall())
            if schema_before != schema_after:
                result['schema_changed'] = True

            # Use conn.total_changes or targeted rowid snapshot
            if table_name and table_name in schema_after:
                if rows_before:
                    rids = list(rows_before.keys())
                    rid_str = ','.join(map(str, rids))
                    cur.execute(f'SELECT rowid, * FROM "{table_name}" WHERE rowid IN ({rid_str})')
                    rows_after = {r[0]: r[1:] for r in cur.fetchall()}
                    changed = 0
                    for rid, row in rows_after.items():
                        if rid not in rows_before or rows_before[rid] != row:
                            changed += 1
                    for rid in rows_before:
                        if rid not in rows_after:
                            changed += 1
                    result['n_changed'] = changed
                else:
                    result['n_changed'] = cur.rowcount if cur.rowcount > 0 else 0
            elif result['schema_changed']:
                result['n_changed'] = len(rows_before)

        except sqlite3.OperationalError as e:
            if "interrupted" in str(e).lower() or time.perf_counter() > deadline:
                result['is_timeout'] = True
                result['decision'] = "CONFIRM"
                result['reason'] = f"Layer 2 execution timed out (> {timeout_ms} ms)"
            else:
                result['error_message'] = str(e)
                if is_write:
                    result['decision'] = "CONFIRM"
                    result['reason'] = f"Layer 2 execution error on write: {e}"
        except Exception as e:
            result['error_message'] = str(e)
            if is_write:
                result['decision'] = "CONFIRM"
                result['reason'] = f"Layer 2 execution error on write: {e}"
        finally:
            try:
                cur.execute("ROLLBACK TO SAVEPOINT l2_effect_check")
                cur.execute("RELEASE SAVEPOINT l2_effect_check")
            except Exception:
                pass

    finally:
        result['elapsed_ms'] = (time.perf_counter() - start_time) * 1000.0
        conn.close()

    return result
