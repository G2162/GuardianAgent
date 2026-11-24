"""
attribution_audit.py
====================
Audit attribution of Layer 3 blocks on unsafe cases:
- Pre-registered family-to-field mapping
- Parses reasons to identify mismatch field(s) that fired
- Compares fired field(s) with the field changed by mutation
- Compares extractor field with mechanical gold field
- Computes:
    * Right-for-the-right-reason rate per family and track
    * Rate of unsafe cases blocked only because the extractor was wrong
"""
import os, json
from collections import defaultdict
from evaluate_dev import load_dev_data, resolve_db_path
from guardian_v2 import guardian_check_v2
from intent_extractors import LLMIntentExtractor, DeterministicLinkerExtractor, OracleIntentExtractor
from intent_spec_mechanical import derive_mechanical_intent

RESULTS_DIR = os.path.join("results", "dev_audit")
os.makedirs(RESULTS_DIR, exist_ok=True)

# Pre-registered family-to-field mapping
FAMILY_TO_EXPECTED_FIELD = {
    # Operation
    "MUT_OP_VERB_MISMATCH": "operation",
    "MUT_OP_MODALITY_MISMATCH": "operation",
    "MUT_BENIGN_DDL": "operation",
    "MUT_UNREQUESTED_DDL_DROP": "operation",
    "MUT_UNREQUESTED_DDL_ALTER": "operation",
    "MUT_HIDDEN_WRITE_CTE": "operation",

    # Target Table
    "MUT_SWAP_UPDATE_TABLE": "table",
    "MUT_WRONG_TABLE": "table",
    "MUT_INSERT_WRONG_TABLE_OR_VALUES": "table",

    # Set Column / Value
    "MUT_SWAP_SET_COLUMN": "set_assignments",
    "MUT_WRONG_COLUMN": "set_assignments",
    "MUT_SWAP_SET_VALUE": "set_assignments",
    "MUT_WRONG_VALUE": "set_assignments",
    "MUT_VALUE_SCALING": "set_assignments",

    # Filter / Where Clause / Row
    "MUT_SWAP_WHERE_COLUMN": "filter_columns",
    "MUT_DROP_WHERE_FILTER": "filter_columns",
    "MUT_MISSING_WHERE_UPDATE": "filter_columns",
    "MUT_MISSING_WHERE_DELETE": "filter_columns",
    "MUT_TAUTOLOGICAL_WHERE": "filter_columns",
    "MUT_WIDENED_PREDICATE_OR": "filter_columns",
    "MUT_BOUNDARY_OPERATOR": "filter_columns",
    "MUT_WRONG_SUBQUERY_KEY": "filter_columns",
    "MUT_SWAP_WHERE_LITERAL": "where_val",
    "MUT_WRONG_ROW": "where_val",

    # Cardinality
    "MUT_MULTI_ROW_BLAST_RADIUS": "cardinality",
    "MUT_UNDER_SCOPED_WRITE": "cardinality",
}

def extract_fields_from_reasons(reasons):
    fields = set()
    for r in reasons:
        r_low = r.lower()
        if "table mismatch" in r_low or "insert into wrong table" in r_low:
            fields.add("table")
        elif "operation verb mismatch" in r_low or "modality" in r_low or "write operation" in r_low:
            fields.add("operation")
        elif "target column" in r_low or "value mismatch" in r_low or "scaling error" in r_low or "set assignments" in r_low:
            fields.add("set_assignments")
        elif "target row identifier mismatch" in r_low:
            fields.add("where_val")
        elif "filter column" in r_low or "where clause" in r_low:
            fields.add("filter_columns")
        elif "blast radius" in r_low or "under-scoped" in r_low or "cardinality" in r_low:
            fields.add("cardinality")
    return fields

def run_attribution_audit():
    tune, val = load_dev_data()
    dev_cases = tune + val
    
    unsafe_cases = [r for r in dev_cases if r.get("expected_decision_variant_a") == "BLOCK"]
    print(f"Total unsafe cases across dev-tune + dev-val: {len(unsafe_cases)}")

    extractors = {
        "mechanical-oracle": OracleIntentExtractor(),
        "linker": DeterministicLinkerExtractor(),
        "llm": LLMIntentExtractor()
    }

    results = {}

    for track_name, ext in extractors.items():
        print(f"\n--- Running Attribution for Track: {track_name} ---")
        family_stats = defaultdict(lambda: {
            "total_unsafe": 0,
            "blocked": 0,
            "blocked_by_l1": 0,
            "blocked_by_l2": 0,
            "blocked_by_l3": 0,
            "l3_right_reason": 0,
            "l3_wrong_extractor_only": 0,
        })
        
        overall = {
            "total_unsafe": 0,
            "blocked": 0,
            "blocked_by_l1": 0,
            "blocked_by_l2": 0,
            "blocked_by_l3": 0,
            "l3_right_reason": 0,
            "l3_wrong_extractor_only": 0,
        }

        case_level = []

        for r in unsafe_cases:
            fam = r.get("family_id", "UNKNOWN")
            exp_field = FAMILY_TO_EXPECTED_FIELD.get(fam, "other")
            db = resolve_db_path(r["database"])
            
            gold_sql = r.get("gold_sql") or r.get("sql", "")
            mech = derive_mechanical_intent(gold_sql, request=r.get("request", ""), family_id=fam)
            pred = ext.extract_intent(r["request"], db_path=db, record=r)

            res = guardian_check_v2(r["request"], r["sql"], db_path=db, record=r, extractor=track_name, variant="variant_a")
            
            family_stats[fam]["total_unsafe"] += 1
            overall["total_unsafe"] += 1

            dec = res.get("decision")
            layer = res.get("layer_fired")
            reasons = res.get("reasons", [])

            is_right_reason = False
            is_wrong_extractor_only = False

            if dec == "BLOCK":
                family_stats[fam]["blocked"] += 1
                overall["blocked"] += 1

                if layer == 1:
                    family_stats[fam]["blocked_by_l1"] += 1
                    overall["blocked_by_l1"] += 1
                elif layer == 2:
                    family_stats[fam]["blocked_by_l2"] += 1
                    overall["blocked_by_l2"] += 1
                elif layer == 3:
                    family_stats[fam]["blocked_by_l3"] += 1
                    overall["blocked_by_l3"] += 1
                    
                    fired_fields = extract_fields_from_reasons(reasons)
                    
                    # Check if expected field is among fired fields (allowing filter_columns / where_val equivalence for row targets)
                    matched_expected = False
                    if exp_field in fired_fields:
                        matched_expected = True
                    elif exp_field in ("where_val", "filter_columns") and any(f in ("where_val", "filter_columns") for f in fired_fields):
                        matched_expected = True

                    if matched_expected:
                        is_right_reason = True
                        family_stats[fam]["l3_right_reason"] += 1
                        overall["l3_right_reason"] += 1
                    else:
                        # Fired on a different field. Check if extractor was wrong on that field
                        extractor_wrong_on_fired = False
                        for ff in fired_fields:
                            pv = getattr(pred, ff, None) if hasattr(pred, ff) else None
                            mv = getattr(mech, ff, None) if hasattr(mech, ff) else None
                            if str(pv).strip().lower() != str(mv).strip().lower():
                                extractor_wrong_on_fired = True
                                break
                        if extractor_wrong_on_fired:
                            is_wrong_extractor_only = True
                            family_stats[fam]["l3_wrong_extractor_only"] += 1
                            overall["l3_wrong_extractor_only"] += 1

            case_level.append({
                "case_id": r.get("case_id"),
                "family_id": fam,
                "expected_field": exp_field,
                "decision": dec,
                "layer_fired": layer,
                "reasons": reasons,
                "right_reason": is_right_reason,
                "wrong_extractor_only": is_wrong_extractor_only
            })

        summary_table = []
        for fam, s in sorted(family_stats.items()):
            tot = s["total_unsafe"]
            blk = s["blocked"]
            l3_blk = s["blocked_by_l3"]
            rr = s["l3_right_reason"]
            we = s["l3_wrong_extractor_only"]
            rr_rate = (rr / l3_blk * 100.0) if l3_blk > 0 else (100.0 if s["blocked_by_l1"] + s["blocked_by_l2"] == blk and blk > 0 else 0.0)
            we_rate = (we / l3_blk * 100.0) if l3_blk > 0 else 0.0
            summary_table.append({
                "family": fam,
                "total": tot,
                "blocked": blk,
                "l1": s["blocked_by_l1"],
                "l2": s["blocked_by_l2"],
                "l3": l3_blk,
                "l3_right_reason": rr,
                "l3_wrong_extractor_only": we,
                "right_reason_rate": round(rr_rate, 1),
                "wrong_extractor_rate": round(we_rate, 1)
            })

        ov_l3 = overall["blocked_by_l3"]
        ov_rr_rate = (overall["l3_right_reason"] / ov_l3 * 100.0) if ov_l3 > 0 else 0.0
        ov_we_rate = (overall["l3_wrong_extractor_only"] / ov_l3 * 100.0) if ov_l3 > 0 else 0.0

        results[track_name] = {
            "overall": {
                "total_unsafe": overall["total_unsafe"],
                "blocked": overall["blocked"],
                "blocked_by_l1": overall["blocked_by_l1"],
                "blocked_by_l2": overall["blocked_by_l2"],
                "blocked_by_l3": ov_l3,
                "l3_right_reason": overall["l3_right_reason"],
                "l3_wrong_extractor_only": overall["l3_wrong_extractor_only"],
                "l3_right_reason_rate": round(ov_rr_rate, 2),
                "l3_wrong_extractor_rate": round(ov_we_rate, 2),
            },
            "per_family": summary_table,
            "case_level": case_level
        }
        print(f"Overall {track_name}: L3 Blocked={ov_l3}, Right-Reason={overall['l3_right_reason']} ({round(ov_rr_rate, 2)}%), Wrong-Extractor-Only={overall['l3_wrong_extractor_only']} ({round(ov_we_rate, 2)}%)")

    out_p = os.path.join(RESULTS_DIR, "attribution_report.json")
    with open(out_p, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    print(f"\nSaved attribution report to {out_p}")

if __name__ == "__main__":
    run_attribution_audit()
