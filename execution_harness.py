"""
execution_harness.py
====================
Execution verification harness for candidate benchmark cases.
Dialect: SQLite (strict).

For EVERY case (benign and unsafe):
- Runs candidate SQL on an isolated in-memory or rolled-back transaction copy of the DB.
- Computes:
    executes_ok: bool
    error_message: str or None
    n_matched: count of rows matching target predicate before mutation
    n_changed: row-level snapshot diff before/after execution
    schema_changed: bool
"""
import sqlite3, sqlglot, copy, re
from sqlglot import exp

DIALECT = 'sqlite'

def verify_candidate_execution(db_path, sql_str, is_stacked=False, is_ddl=False):
    """
    Executes sql_str against db_path in a safe rolled-back transaction.
    Returns:
        dict: {
            'executes_ok': bool,
            'error_message': str or None,
            'n_matched': int,
            'n_changed': int,
            'schema_changed': bool
        }
    """
    res = {
        'executes_ok': False,
        'error_message': None,
        'n_matched': 0,
        'n_changed': 0,
        'schema_changed': False
    }
    
    if not sql_str or not sql_str.strip():
        res['error_message'] = "Empty SQL statement"
        return res

    # 1. Connect to DB
    try:
        conn = sqlite3.connect(db_path)
    except Exception as e:
        res['error_message'] = f"Database connection error: {e}"
        return res

    # Special handling for DDL (CREATE, DROP, ALTER)
    # SQLite allows DDL inside transactions, but table schema diff can be verified
    try:
        cur = conn.cursor()
        
        if is_stacked:
            # Execute constituent statements sequentially in a single transaction
            stmts = [s.strip() for s in sql_str.split(';') if s.strip()]
            conn.execute("SAVEPOINT test_stacked")
            try:
                for s in stmts:
                    cur.execute(s)
                res['executes_ok'] = True
            except Exception as e:
                res['executes_ok'] = False
                res['error_message'] = str(e)
            finally:
                conn.execute("ROLLBACK TO SAVEPOINT test_stacked")
                conn.execute("RELEASE SAVEPOINT test_stacked")
                conn.close()
            return res

        # For normal DML / DDL:
        # Determine table and parse
        table_name = None
        where_clause_str = None
        try:
            tree = sqlglot.parse_one(sql_str.rstrip(';'), read='sqlite')
            tbl_node = tree.find(exp.Table)
            if tbl_node:
                table_name = tbl_node.name.strip('"')
            where_node = tree.find(exp.Where)
            if where_node:
                where_clause_str = str(where_node)
        except Exception:
            pass

        # Measure n_matched if table and WHERE exist
        if table_name and where_clause_str:
            try:
                cnt_cur = cur.execute(f'SELECT COUNT(*) FROM "{table_name}" {where_clause_str}')
                res['n_matched'] = cnt_cur.fetchone()[0]
            except Exception:
                res['n_matched'] = 0
        elif table_name and not where_clause_str and not is_ddl:
            # Whole table
            try:
                cnt_cur = cur.execute(f'SELECT COUNT(*) FROM "{table_name}"')
                res['n_matched'] = cnt_cur.fetchone()[0]
            except Exception:
                res['n_matched'] = 0

        # Snapshot table state before
        snapshot_before = None
        if table_name and not is_ddl:
            try:
                rows_cur = cur.execute(f'SELECT rowid, * FROM "{table_name}"')
                snapshot_before = rows_cur.fetchall()
            except Exception:
                pass

        # Snapshot schema before if DDL
        schema_before = None
        if is_ddl:
            try:
                schema_cur = cur.execute("SELECT type, name, sql FROM sqlite_master")
                schema_before = schema_cur.fetchall()
            except Exception:
                pass

        # Execute inside transaction
        conn.execute("SAVEPOINT test_exec")
        try:
            cur.execute(sql_str)
            res['executes_ok'] = True
            
            # Snapshot table state after
            if table_name and snapshot_before is not None:
                try:
                    rows_cur = cur.execute(f'SELECT rowid, * FROM "{table_name}"')
                    snapshot_after = rows_cur.fetchall()
                    before_dict = {r[0]: r[1:] for r in snapshot_before}
                    after_dict = {r[0]: r[1:] for r in snapshot_after}
                    
                    changed = 0
                    for rid, vals in after_dict.items():
                        if rid not in before_dict or before_dict[rid] != vals:
                            changed += 1
                    # deleted rows
                    for rid in before_dict:
                        if rid not in after_dict:
                            changed += 1
                    res['n_changed'] = changed
                except Exception:
                    res['n_changed'] = cur.rowcount if cur.rowcount >= 0 else 0
            elif is_ddl:
                try:
                    schema_cur = cur.execute("SELECT type, name, sql FROM sqlite_master")
                    schema_after = schema_cur.fetchall()
                    res['schema_changed'] = (schema_before != schema_after)
                    res['n_changed'] = 1 if res['schema_changed'] else 0
                except Exception:
                    pass
            else:
                res['n_changed'] = cur.rowcount if cur.rowcount >= 0 else 0
                
        except Exception as exec_err:
            res['executes_ok'] = False
            res['error_message'] = str(exec_err)
        finally:
            conn.execute("ROLLBACK TO SAVEPOINT test_exec")
            conn.execute("RELEASE SAVEPOINT test_exec")

    except Exception as outer_err:
        res['executes_ok'] = False
        res['error_message'] = str(outer_err)
    finally:
        try:
            conn.close()
        except:
            pass

    return res

if __name__ == '__main__':
    # Self-test
    test_db = 'data/evaluation_dbs/battle_death.sqlite'
    out = verify_candidate_execution(test_db, 'UPDATE "battle" SET "name" = \'Test Battle\' WHERE "id" = 1;')
    print("Self-test result:", out)
    assert out['executes_ok'], "Self-test failed"
    assert out['n_changed'] == 1, "Expected 1 changed row"
    print("Execution harness verified OK.")

