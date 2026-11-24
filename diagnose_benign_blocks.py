"""
diagnose_benign_blocks.py
=========================
Diagnoses every benign write statement decided BLOCK under:
  1. The LLM track
  2. The Linker track
on dev-tune.

For each benign BLOCK:
  - which comparator rule fired
  - extracted field vs mechanical field
  - classification:
      (a) extractor error
      (b) comparator too strict (type/case/quoting/alias/normalization, e.g. '1' vs 1, column case, quoted identifiers, table aliases)
      (c) other
"""
import os, json
from collections import defaultdict
from evaluate_dev import load_dev_data, resolve_db_path
from guardian_v2 import guardian_check_v2
from intent_spec_mechanical import derive_mechanical_intent
from intent_extractors import LLMIntentExtractor, DeterministicLinkerExtractor
from intent_spec_v2 import extract_sql_components, compare_intent_and_sql

RESULTS_DIR = os.path.join("results", "dev_audit")

def diagnose():
    tune, val = load_dev_data()
    write_cases = [
        r for r in tune
        if r.get("expected_decision_variant_a") != "BLOCK"
        and r.get("sql", "").strip().upper().startswith(("UPDATE", "DELETE", "INSERT", "WITH"))
    ]
    print(f"Total benign write cases on dev-tune: {len(write_cases)}")

    extractors = {
        "linker": DeterministicLinkerExtractor(),
        "llm": LLMIntentExtractor()
    }

    diagnosis_report = {"linker": [], "llm": []}

    for ext_name, ext in extractors.items():
        print(f"\nAnalyzing {ext_name}...")
        for r in write_cases:
            db_path = resolve_db_path(r["database"])
            sql = r.get("sql", "")
            req = r.get("request", "")
            gold_sql = r.get("gold_sql") or sql

            mech_intent = derive_mechanical_intent(gold_sql, request=req, family_id=r.get("family_id", ""))
            pred_intent = ext.extract_intent(req, db_path=db_path, record=r)

            # Check decision
            res = guardian_check_v2(req, sql, db_path=db_path, record=r, extractor=ext_name, variant="variant_a")
            if res["decision"] == "BLOCK":
                # Find which rule fired
                reasons = res.get("reasons", [])
                
                # Classify
                # Compare extracted vs mechanical
                field_diffs = []
                classification = "other"
                
                # Check table mismatch
                if mech_intent.table != pred_intent.table:
                    field_diffs.append(f"table: mech={mech_intent.table} vs pred={pred_intent.table}")
                    # Is it case or quoting?
                    if str(mech_intent.table).strip('"\'').lower() == str(pred_intent.table).strip('"\'').lower():
                        classification = "comparator_too_strict"
                    else:
                        classification = "extractor_error"

                # Check operation mismatch
                if mech_intent.operation != pred_intent.operation:
                    field_diffs.append(f"op: mech={mech_intent.operation} vs pred={pred_intent.operation}")
                    classification = "extractor_error"

                # Check filter columns mismatch
                m_cols = set(c.lower().strip('"\'') for c in (mech_intent.filter_columns or []))
                p_cols = set(c.lower().strip('"\'') for c in (pred_intent.filter_columns or []))
                if m_cols != p_cols:
                    field_diffs.append(f"filters: mech={m_cols} vs pred={p_cols}")
                    # If column names differ only by case/quote/type
                    raw_m = set(mech_intent.filter_columns or [])
                    raw_p = set(pred_intent.filter_columns or [])
                    if raw_m != raw_p and m_cols == p_cols:
                        classification = "comparator_too_strict"
                    elif not classification or classification == "other":
                        classification = "extractor_error"

                # Check where_val mismatch
                m_val = str(mech_intent.where_val).strip('"\'').lower() if mech_intent.where_val is not None else None
                p_val = str(pred_intent.where_val).strip('"\'').lower() if pred_intent.where_val is not None else None
                if m_val != p_val:
                    field_diffs.append(f"where_val: mech={mech_intent.where_val} vs pred={pred_intent.where_val}")
                    # Check '1' vs 1 or quotes
                    if mech_intent.where_val is not None and pred_intent.where_val is not None:
                        if str(mech_intent.where_val).strip('"\'') == str(pred_intent.where_val).strip('"\'') or \
                           str(mech_intent.where_val).replace(".0","") == str(pred_intent.where_val).replace(".0",""):
                            classification = "comparator_too_strict"
                        elif classification == "other":
                            classification = "extractor_error"

                # Check set_assignments
                m_set = mech_intent.set_assignments or {}
                p_set = pred_intent.set_assignments or {}
                if m_set != p_set:
                    field_diffs.append(f"set: mech={m_set} vs pred={p_set}")
                    # check normalized
                    m_norm = {k.lower().strip('"\'') : str(v).lower().strip('"\'') for k, v in m_set.items()}
                    p_norm = {k.lower().strip('"\'') : str(v).lower().strip('"\'') for k, v in p_set.items()}
                    if m_norm == p_norm and m_set != p_set:
                        classification = "comparator_too_strict"
                    elif classification == "other":
                        classification = "extractor_error"

                diag_entry = {
                    "case_id": r.get("case_id"),
                    "family_id": r.get("family_id"),
                    "request": req,
                    "sql": sql,
                    "reasons": reasons,
                    "field_diffs": field_diffs,
                    "classification": classification
                }
                diagnosis_report[ext_name].append(diag_entry)

        print(f"Total benign BLOCKs for {ext_name}: {len(diagnosis_report[ext_name])}")
        class_counts = defaultdict(int)
        for d in diagnosis_report[ext_name]:
            class_counts[d["classification"]] += 1
        print("  Breakdown:", dict(class_counts))

    out_p = os.path.join(RESULTS_DIR, "benign_blocks_diagnosis.json")
    with open(out_p, "w", encoding="utf-8") as f:
        json.dump(diagnosis_report, f, indent=2)
    print(f"\nSaved diagnosis to {out_p}")

if __name__ == "__main__":
    diagnose()
