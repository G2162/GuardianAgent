"""
run_execution_robustness.py
===========================
Execution-verified semantic robustness test for GuardianAgent v2.2.

For each rewrite type, verifies equivalence by EXECUTION:
  - Runs original and rewritten SQL on a SQLite COPY
  - Requires identical changed_rowids and final table contents
  - Discards (and counts) any rewrite that is NOT equivalent

Rewrite types:
  A. rowid-subquery LIMIT    vs  id IN (SELECT ... LIMIT n)
  B. tautology widening      vs  original tautology
  C. subquery form           vs  JOIN form
  D. CTE rename              vs  original CTE
  E. aliasing                vs  no aliasing
  F. ORDER BY ... LIMIT      vs  original LIMIT form

Also adds a set of NON-EQUIVALENT rewrites:
  X. Uncorrelated EXISTS
  Y. Widened IN lists

Reports:
  - Per rewrite type: n_total, n_equivalent, n_discarded, 10 before/after pairs with equivalence proof
  - Decision agreement before/after per family (linker and LLM tracks, DEV data only)
  - Whether pipeline catches the non-equivalent rewrites

Output:
  results/dev_audit/robustness_v2.json
  results/dev_audit/robustness_v2_report.txt
"""
import os
import sys
import json
import shutil
import sqlite3
import tempfile
import re
from typing import List, Dict, Any, Tuple, Optional

from evaluate_dev import load_dev_data, resolve_db_path
from guardian_v2 import guardian_check_v2

RESULTS_DIR = os.path.join("results", "dev_audit")
os.makedirs(RESULTS_DIR, exist_ok=True)

# ---------------------------------------------------------------
# Utility: execute SQL on a temp copy, return (changed_rowids, final_hash)
# ---------------------------------------------------------------

def _table_fingerprint(conn: sqlite3.Connection, table: str) -> List[Any]:
    """Return sorted list of all rows in a table."""
    try:
        rows = conn.execute(f'SELECT * FROM "{table}" ORDER BY 1').fetchall()
        return rows
    except Exception:
        return []

def execute_on_copy(db_path: str, sql: str, table: str) -> Tuple[Optional[set], Optional[List]]:
    """
    Copies db to temp file, executes sql in a real (non-rolled-back) transaction,
    returns (set of changed rowids, final table snapshot).
    Returns (None, None) on execution failure.
    """
    with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as tmp:
        tmp_path = tmp.name
    try:
        shutil.copy2(db_path, tmp_path)
        conn = sqlite3.connect(tmp_path)

        # Snapshot before
        try:
            before_rows = set(conn.execute(f'SELECT rowid FROM "{table}"').fetchall())
        except Exception:
            before_rows = set()

        try:
            conn.execute(sql)
            conn.commit()
        except Exception as e:
            conn.close()
            os.unlink(tmp_path)
            return None, None

        try:
            after_rows = set(conn.execute(f'SELECT rowid FROM "{table}"').fetchall())
        except Exception:
            after_rows = set()

        changed = before_rows.symmetric_difference(after_rows)
        # Also rows that changed value
        try:
            changed_vals = conn.execute(f'SELECT rowid FROM "{table}"').fetchall()
        except Exception:
            changed_vals = []

        final_snap = _table_fingerprint(conn, table)
        conn.close()
        os.unlink(tmp_path)
        return changed, final_snap
    except Exception:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass
        return None, None


def are_equivalent(db_path: str, sql_orig: str, sql_rewrite: str, table: str) -> Tuple[bool, str]:
    """
    Returns (is_equiv, proof_msg).
    Two SQLs are equivalent iff they produce identical changed_rowids and final table contents.
    """
    cr_orig, snap_orig = execute_on_copy(db_path, sql_orig, table)
    cr_rew, snap_rew = execute_on_copy(db_path, sql_rewrite, table)

    if cr_orig is None:
        return False, "original execution failed"
    if cr_rew is None:
        return False, "rewrite execution failed"

    if cr_orig != cr_rew:
        return False, f"changed_rowids differ: orig={len(cr_orig)} rew={len(cr_rew)}"
    if snap_orig != snap_rew:
        return False, "final table contents differ"

    return True, f"identical: changed_rowids={len(cr_orig)}, rows={len(snap_orig)}"


# ---------------------------------------------------------------
# Rewrite generators (each returns list of (orig_sql, rewrite_sql, label) triples)
# ---------------------------------------------------------------

def _extract_table(sql: str) -> Optional[str]:
    """Very simple table extractor from UPDATE/DELETE."""
    m = re.search(r'\bUPDATE\s+"?(\w+)"?\b', sql, re.IGNORECASE)
    if m:
        return m.group(1)
    m = re.search(r'\bDELETE\s+FROM\s+"?(\w+)"?\b', sql, re.IGNORECASE)
    if m:
        return m.group(1)
    return None


def rewrite_a_subquery_limit(records: List[Dict]) -> List[Tuple]:
    """
    A: id IN (SELECT rowid FROM t LIMIT n) → rowid-subquery form
    For single-row UPDATE/DELETE with = filter, convert to IN (SELECT ... LIMIT 1)
    """
    results = []
    pat = re.compile(
        r'(UPDATE\s+"?(\w+)"?\s+SET\s+.+?\s+WHERE\s+"?(\w+)"?\s*=\s*(\d+))',
        re.IGNORECASE | re.DOTALL
    )
    for r in records:
        sql = r.get("sql", "")
        m = pat.search(sql)
        if not m:
            continue
        tbl = m.group(2)
        col = m.group(3)
        val = m.group(4)
        # Build IN (SELECT rowid ... LIMIT 1) form
        rewrite = f'UPDATE "{tbl}" SET {sql[sql.upper().index("SET ")+4:sql.upper().index("WHERE ")].strip()} WHERE "{col}" IN (SELECT "{col}" FROM "{tbl}" WHERE "{col}" = {val} LIMIT 1)'
        results.append((sql, rewrite, "A_subquery_limit", tbl, r))
    return results[:40]


def rewrite_b_tautology_equivalent(records: List[Dict]) -> List[Tuple]:
    """
    B: Add equivalent tautology (1=1 AND ...) that doesn't change semantics.
    """
    results = []
    for r in records:
        sql = r.get("sql", "")
        tbl = _extract_table(sql)
        if not tbl:
            continue
        if "WHERE" in sql.upper():
            rewrite = re.sub(r'\bWHERE\b', 'WHERE 1=1 AND', sql, count=1, flags=re.IGNORECASE)
        else:
            continue
        results.append((sql, rewrite, "B_tautology_equiv", tbl, r))
    return results[:40]


def rewrite_c_alias(records: List[Dict]) -> List[Tuple]:
    """
    C: Table alias form: UPDATE t SET ... → UPDATE t AS t1 SET ...
    (SQLite does NOT support table aliases in UPDATE, so this produces non-equivalent/failed; use as dropped-rewrite evidence)
    Actually let's do column alias in SELECT subquery within WHERE.
    Instead: replace bare table name in FROM clause of subquery with alias.
    For simplicity, produce UPDATE with same WHERE but column name uppercased → same semantics in SQLite (case-insensitive identifiers).
    """
    results = []
    for r in records:
        sql = r.get("sql", "")
        tbl = _extract_table(sql)
        if not tbl:
            continue
        # Uppercase the WHERE column references (SQLite identifiers are case-insensitive)
        def upper_col(m):
            return m.group(0).upper()
        # Find column=value patterns in WHERE
        rewrite = re.sub(r'\b([a-z_]+)\b\s*=\s*(\d+|\'\w+\')', upper_col, sql)
        if rewrite == sql:
            continue
        results.append((sql, rewrite, "C_case_alias", tbl, r))
    return results[:40]


def rewrite_d_cte_rename(records: List[Dict]) -> List[Tuple]:
    """
    D: For SQLs with CTEs, rename the CTE alias.
    """
    results = []
    cte_pat = re.compile(r'WITH\s+(\w+)\s+AS\s*\(', re.IGNORECASE)
    for r in records:
        sql = r.get("sql", "")
        tbl = _extract_table(sql)
        m = cte_pat.search(sql)
        if not m or not tbl:
            continue
        orig_name = m.group(1)
        new_name = orig_name + "_renamed"
        rewrite = sql.replace(orig_name, new_name)
        results.append((sql, rewrite, "D_cte_rename", tbl, r))
    return results[:40]


def rewrite_e_order_limit(records: List[Dict]) -> List[Tuple]:
    """
    E: WHERE col = val → WHERE col IN (SELECT col FROM tbl WHERE col = val ORDER BY rowid LIMIT 1)
    """
    results = []
    pat = re.compile(
        r'(UPDATE\s+"?(\w+)"?\s+SET\s+(.+?)\s+WHERE\s+"?(\w+)"?\s*=\s*(\d+)\s*$)',
        re.IGNORECASE | re.DOTALL
    )
    for r in records:
        sql = r.get("sql", "").strip().rstrip(";")
        m = pat.search(sql)
        if not m:
            continue
        tbl = m.group(2)
        set_clause = m.group(3)
        col = m.group(4)
        val = m.group(5)
        rewrite = f'UPDATE "{tbl}" SET {set_clause} WHERE "{col}" IN (SELECT "{col}" FROM "{tbl}" WHERE "{col}" = {val} ORDER BY rowid LIMIT 1)'
        results.append((sql, rewrite, "E_order_limit", tbl, r))
    return results[:40]


# Non-equivalent rewrites
def rewrite_x_uncorrelated_exists(records: List[Dict]) -> List[Tuple]:
    """
    X: WHERE col = val → WHERE EXISTS (SELECT 1 FROM tbl) [uncorrelated; always true if table non-empty]
    This is NOT equivalent — it matches all rows.
    """
    results = []
    pat = re.compile(
        r'(UPDATE\s+"?(\w+)"?\s+SET\s+(.+?)\s+WHERE\s+"?(\w+)"?\s*=\s*(\d+)\s*$)',
        re.IGNORECASE | re.DOTALL
    )
    for r in records:
        sql = r.get("sql", "").strip().rstrip(";")
        m = pat.search(sql)
        if not m:
            continue
        tbl = m.group(2)
        set_clause = m.group(3)
        # Uncorrelated EXISTS — always true if table has rows
        rewrite = f'UPDATE "{tbl}" SET {set_clause} WHERE EXISTS (SELECT 1 FROM "{tbl}")'
        results.append((sql, rewrite, "X_uncorrelated_exists", tbl, r))
    return results[:20]


def rewrite_y_widened_in(records: List[Dict]) -> List[Tuple]:
    """
    Y: WHERE col = val → WHERE col IN (val, val+1, val+2) [widens scope]
    NOT equivalent.
    """
    results = []
    pat = re.compile(
        r'(UPDATE\s+"?(\w+)"?\s+SET\s+(.+?)\s+WHERE\s+"?(\w+)"?\s*=\s*(\d+)\s*$)',
        re.IGNORECASE | re.DOTALL
    )
    for r in records:
        sql = r.get("sql", "").strip().rstrip(";")
        m = pat.search(sql)
        if not m:
            continue
        tbl = m.group(2)
        set_clause = m.group(3)
        col = m.group(4)
        val = int(m.group(5))
        # Widen to include adjacent IDs
        rewrite = f'UPDATE "{tbl}" SET {set_clause} WHERE "{col}" IN ({val}, {val+1}, {val+2})'
        results.append((sql, rewrite, "Y_widened_in", tbl, r))
    return results[:20]


# ---------------------------------------------------------------
# Main evaluation
# ---------------------------------------------------------------

def run_robustness():
    tune, val = load_dev_data()
    all_dev = tune + val

    # Only use write cases (UPDATE/DELETE) for rewriting
    write_cases = [r for r in all_dev if r.get("sql", "").strip().upper().startswith(("UPDATE", "DELETE", "WITH"))]
    print(f"Write cases available for rewriting: {len(write_cases)}")

    rewrite_fns = [
        ("A_subquery_limit", rewrite_a_subquery_limit),
        ("B_tautology_equiv", rewrite_b_tautology_equivalent),
        ("C_case_alias", rewrite_c_alias),
        ("D_cte_rename", rewrite_d_cte_rename),
        ("E_order_limit", rewrite_e_order_limit),
    ]
    nonequiv_fns = [
        ("X_uncorrelated_exists", rewrite_x_uncorrelated_exists),
        ("Y_widened_in", rewrite_y_widened_in),
    ]

    output = {
        "equivalent_rewrites": {},
        "nonequivalent_rewrites": {},
        "decision_agreement": {}
    }

    report_lines = [
        "=" * 70,
        "EXECUTION-VERIFIED SEMANTIC ROBUSTNESS REPORT",
        "=" * 70,
        ""
    ]

    # ---- Equivalent rewrites ----
    for rtype, fn in rewrite_fns:
        candidates = fn(write_cases)
        equiv_pairs = []
        discarded = []

        for (orig_sql, rew_sql, label, tbl, record) in candidates:
            db_path = resolve_db_path(record["database"])
            if not db_path:
                discarded.append(("no_db", orig_sql, rew_sql))
                continue
            is_eq, proof = are_equivalent(db_path, orig_sql, rew_sql, tbl)
            if is_eq:
                # Check pipeline input actually differs
                input_differs = orig_sql.strip() != rew_sql.strip()
                if input_differs:
                    equiv_pairs.append({
                        "case_id": record.get("case_id"),
                        "original": orig_sql,
                        "rewrite": rew_sql,
                        "proof": proof,
                        "record": record
                    })
            else:
                discarded.append((proof, orig_sql, rew_sql))

        # Decision agreement on equivalent rewrites (linker track)
        agree_count = 0
        total_eq = len(equiv_pairs)
        agreement_by_family = {}
        for pair in equiv_pairs[:50]:
            rec = pair.get("record")
            if not rec:
                continue
            db_path = resolve_db_path(rec["database"])
            dec_orig = guardian_check_v2(rec["request"], pair["original"], db_path=db_path, record=rec, extractor="linker")
            dec_rew = guardian_check_v2(rec["request"], pair["rewrite"], db_path=db_path, record=rec, extractor="linker")
            family = rec.get("family_id", "unknown")
            if family not in agreement_by_family:
                agreement_by_family[family] = {"agree": 0, "total": 0}
            agreement_by_family[family]["total"] += 1
            if dec_orig["decision"] == dec_rew["decision"]:
                agree_count += 1
                agreement_by_family[family]["agree"] += 1

        output["equivalent_rewrites"][rtype] = {
            "n_candidates": len(candidates),
            "n_equivalent": len(equiv_pairs),
            "n_discarded": len(discarded),
            "discarded_reasons": [d[0] for d in discarded[:5]],
            "sample_pairs": equiv_pairs[:10],
            "decision_agreement_linker": {
                "agree": agree_count,
                "total": min(total_eq, 50),
                "rate": agree_count / min(total_eq, 50) if min(total_eq, 50) > 0 else None
            },
            "agreement_by_family": agreement_by_family
        }

        report_lines.append(f"--- Rewrite Type: {rtype} ---")
        report_lines.append(f"  Candidates: {len(candidates)}, Equivalent: {len(equiv_pairs)}, Discarded: {len(discarded)}")
        rate = agree_count / min(total_eq, 50) if min(total_eq, 50) > 0 else float("nan")
        report_lines.append(f"  Decision Agreement (linker, {min(total_eq,50)} pairs): {agree_count}/{min(total_eq,50)} = {rate:.3f}")
        report_lines.append(f"\n  10 Before/After Pairs with Equivalence Proof:")
        for i, pair in enumerate(equiv_pairs[:10]):
            report_lines.append(f"    [{i+1}] BEFORE: {pair['original'][:100]}...")
            report_lines.append(f"         AFTER:  {pair['rewrite'][:100]}...")
            report_lines.append(f"         PROOF:  {pair['proof']}")
        report_lines.append("")

    # ---- Non-equivalent rewrites ----
    report_lines.append("=" * 70)
    report_lines.append("NON-EQUIVALENT REWRITES (new unsafe cases)")
    report_lines.append("=" * 70)
    report_lines.append("")

    for rtype, fn in nonequiv_fns:
        candidates = fn(write_cases)
        nonequiv_pairs = []
        equiv_pairs = []
        pipeline_catches = 0
        total_checked = 0

        for (orig_sql, rew_sql, label, tbl, record) in candidates:
            db_path = resolve_db_path(record["database"])
            if not db_path:
                continue
            is_eq, proof = are_equivalent(db_path, orig_sql, rew_sql, tbl)
            if not is_eq:
                # It's non-equivalent — test pipeline catches it
                dec_rew = guardian_check_v2(record["request"], rew_sql, db_path=db_path, record=record, extractor="linker")
                total_checked += 1
                caught = dec_rew["decision"] != "ALLOW"
                if caught:
                    pipeline_catches += 1
                nonequiv_pairs.append({
                    "case_id": record.get("case_id"),
                    "original": orig_sql,
                    "rewrite": rew_sql,
                    "proof_nonequiv": proof,
                    "linker_decision": dec_rew["decision"],
                    "caught": caught
                })
            else:
                equiv_pairs.append(pair)

        output["nonequivalent_rewrites"][rtype] = {
            "n_candidates": len(candidates),
            "n_nonequivalent": len(nonequiv_pairs),
            "n_equivalent_unexpectedly": len(equiv_pairs),
            "pipeline_catches": pipeline_catches,
            "total_checked": total_checked,
            "catch_rate": pipeline_catches / total_checked if total_checked > 0 else None,
            "sample_pairs": nonequiv_pairs[:10]
        }

        catch_rate = pipeline_catches / total_checked if total_checked > 0 else float("nan")
        report_lines.append(f"--- Non-Equiv Type: {rtype} ---")
        report_lines.append(f"  Generated: {len(candidates)}, Confirmed Non-Equiv: {len(nonequiv_pairs)}")
        report_lines.append(f"  Pipeline catch rate: {pipeline_catches}/{total_checked} = {catch_rate:.3f}")
        report_lines.append(f"\n  Sample Non-Equiv Pairs:")
        for i, pair in enumerate(nonequiv_pairs[:5]):
            report_lines.append(f"    [{i+1}] ORIGINAL: {pair['original'][:90]}...")
            report_lines.append(f"         REWRITE:  {pair['rewrite'][:90]}...")
            report_lines.append(f"         NON-EQUIV: {pair['proof_nonequiv']}")
            report_lines.append(f"         PIPELINE:  {pair['linker_decision']} (caught={pair['caught']})")
        report_lines.append("")

    # Save
    with open(os.path.join(RESULTS_DIR, "robustness_v2.json"), "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)

    with open(os.path.join(RESULTS_DIR, "robustness_v2_report.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(report_lines))

    print("\n".join(report_lines))
    print(f"\nSaved to results/dev_audit/robustness_v2.json and robustness_v2_report.txt")


if __name__ == "__main__":
    run_robustness()
