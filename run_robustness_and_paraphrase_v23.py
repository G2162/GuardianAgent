"""
run_robustness_and_paraphrase_v23.py
====================================
Complete evaluation of:
1. Semantic Robustness Rewrites (A-E equivalent, X-Y non-equivalent) on both Linker and LLM tracks.
2. Paraphrase Evaluation on dev-tune and dev-val for both extractors.
   - Per-family decision agreement before/after.
   - Lists every family whose decision changes.
   - Reports per-field intent accuracy before/after paraphrasing.
"""
import os, sys, json
from collections import defaultdict
from evaluate_dev import load_dev_data, resolve_db_path
from guardian_v2 import guardian_check_v2
from intent_extractors import LLMIntentExtractor, DeterministicLinkerExtractor
from intent_spec_mechanical import derive_mechanical_intent
from run_execution_robustness import (
    rewrite_a_subquery_limit,
    rewrite_b_tautology_equivalent,
    rewrite_c_alias,
    rewrite_d_cte_rename,
    rewrite_e_order_limit,
    rewrite_x_uncorrelated_exists,
    rewrite_y_widened_in,
    execute_on_copy
)

RESULTS_DIR = os.path.join("results", "dev_audit")
os.makedirs(RESULTS_DIR, exist_ok=True)

def evaluate_rewrites(tune_records, val_records):
    records = tune_records + val_records
    print(f"\n=======================================================")
    print(f"1. RUNNING SEMANTIC REWRITE SUITE (N_dev={len(records)})")
    print(f"=======================================================")

    rewrite_generators = [
        ("A_subquery_limit", rewrite_a_subquery_limit, True),
        ("B_tautology_equiv", rewrite_b_tautology_equivalent, True),
        ("C_case_alias", rewrite_c_alias, True),
        ("D_cte_rename", rewrite_d_cte_rename, True),
        ("E_order_limit", rewrite_e_order_limit, True),
        ("X_uncorrelated_exists", rewrite_x_uncorrelated_exists, False),
        ("Y_widened_in", rewrite_y_widened_in, False),
    ]

    extractors = {
        "linker": DeterministicLinkerExtractor(),
        "llm": LLMIntentExtractor()
    }

    results = {
        "equivalent": {},
        "nonequivalent": {}
    }

    for rw_name, gen_fn, is_equiv in rewrite_generators:
        print(f"\nEvaluating Rewrite: {rw_name} (Equivalent={is_equiv})")
        pairs = gen_fn(records)
        print(f"  Generated {len(pairs)} candidate pairs.")

        # Verify equivalence by execution
        verified_pairs = []
        discarded_count = 0
        for orig_sql, rew_sql, typ, tbl, rec in pairs:
            db_p = resolve_db_path(rec["database"])
            ch_orig, snap_orig = execute_on_copy(db_p, orig_sql, tbl)
            ch_rew, snap_rew = execute_on_copy(db_p, rew_sql, tbl)

            if is_equiv:
                if ch_orig is not None and ch_orig == ch_rew and snap_orig == snap_rew:
                    verified_pairs.append((orig_sql, rew_sql, typ, tbl, rec))
                else:
                    discarded_count += 1
            else:
                # Non-equivalent: must NOT be identical in both effects and snapshot
                if ch_orig is not None and (ch_orig != ch_rew or snap_orig != snap_rew):
                    verified_pairs.append((orig_sql, rew_sql, typ, tbl, rec))
                else:
                    discarded_count += 1

        print(f"  Verified: {len(verified_pairs)} | Discarded: {discarded_count}")

        rw_res = {
            "n_total": len(pairs),
            "n_verified": len(verified_pairs),
            "n_discarded": discarded_count,
            "tracks": {}
        }

        for track_name, ext in extractors.items():
            same_dec = 0
            diff_dec = 0
            flips_by_family = defaultdict(int)
            sample_diffs = []
            intercept_counts = defaultdict(int)

            for orig_sql, rew_sql, typ, tbl, rec in verified_pairs:
                db_p = resolve_db_path(rec["database"])
                req = rec["request"]
                fam = rec.get("family_id", "unknown")

                res_orig = guardian_check_v2(req, orig_sql, db_path=db_p, record=rec, extractor=track_name)
                res_rew = guardian_check_v2(req, rew_sql, db_path=db_p, record=rec, extractor=track_name)

                dec_orig = res_orig["decision"]
                dec_rew = res_rew["decision"]

                if dec_orig == dec_rew:
                    same_dec += 1
                else:
                    diff_dec += 1
                    flips_by_family[fam] += 1
                    if len(sample_diffs) < 5:
                        sample_diffs.append({
                            "case_id": rec.get("case_id"),
                            "family_id": fam,
                            "orig_dec": dec_orig,
                            "rew_dec": dec_rew,
                            "orig_reasons": res_orig.get("reasons", []),
                            "rew_reasons": res_rew.get("reasons", []),
                        })

                if not is_equiv:
                    # Catch rate for unsafe/non-equivalent mutations:
                    # pipeline catches it if it blocks or confirms
                    intercept_counts[dec_rew] += 1

            agr_rate = (same_dec / len(verified_pairs) * 100.0) if verified_pairs else 100.0
            print(f"    [{track_name.upper()}] Agreement: {same_dec}/{len(verified_pairs)} ({agr_rate:.1f}%), Flips: {dict(flips_by_family)}")
            if not is_equiv:
                print(f"    [{track_name.upper()}] Non-equiv outcomes on rewrite: {dict(intercept_counts)}")

            rw_res["tracks"][track_name] = {
                "agreement_count": same_dec,
                "disagreement_count": diff_dec,
                "agreement_rate": round(agr_rate, 2),
                "flips_by_family": dict(flips_by_family),
                "sample_diffs": sample_diffs,
                "outcomes": dict(intercept_counts) if not is_equiv else None
            }

        sec = "equivalent" if is_equiv else "nonequivalent"
        results[sec][rw_name] = rw_res

    out_p = os.path.join(RESULTS_DIR, "robustness_v23_results.json")
    with open(out_p, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    print(f"\nSaved semantic rewrite results to {out_p}")


def evaluate_paraphrases(tune_records, val_records):
    print(f"\n=======================================================")
    print(f"2. RUNNING PARAPHRASE EVALUATION (dev-tune + dev-val)")
    print(f"=======================================================")

    with open("data/dev_paraphrases.json", "r", encoding="utf-8") as f:
        para_map = json.load(f)

    splits = {
        "dev-tune": tune_records,
        "dev-val": val_records
    }

    extractors = {
        "linker": DeterministicLinkerExtractor(),
        "llm": LLMIntentExtractor()
    }

    para_results = {}

    for split_name, records in splits.items():
        print(f"\n--- Split: {split_name} (N={len(records)}) ---")
        para_results[split_name] = {}

        for track_name, ext in extractors.items():
            print(f"  Evaluating Extractor: {track_name}")
            total = 0
            same = 0
            diff = 0
            flips_by_family = defaultdict(int)
            sample_flips = []

            # Per-field accuracy before and after paraphrase
            field_stats = {
                "orig": {"op": 0, "table": 0, "filters": 0, "where_val": 0, "set": 0, "card": 0, "total": 0},
                "para": {"op": 0, "table": 0, "filters": 0, "where_val": 0, "set": 0, "card": 0, "total": 0}
            }

            for r in records:
                cid = r.get("case_id")
                orig_req = r.get("request", "")
                para_req = para_map.get(cid)
                if not para_req:
                    continue

                total += 1
                db_p = resolve_db_path(r["database"])
                sql = r.get("sql", "")
                gold_sql = r.get("gold_sql") or sql
                fam = r.get("family_id", "unknown")

                # Ground truth mechanical intent
                mech = derive_mechanical_intent(gold_sql, request=orig_req, family_id=fam)

                # Original evaluation
                res_orig = guardian_check_v2(orig_req, sql, db_path=db_p, record=r, extractor=track_name)
                intent_orig = ext.extract_intent(orig_req, db_path=db_p, record=r)

                # Paraphrase evaluation (create copy of record with paraphrase request)
                r_para = dict(r)
                r_para["request"] = para_req
                res_para = guardian_check_v2(para_req, sql, db_path=db_p, record=r_para, extractor=track_name)
                intent_para = ext.extract_intent(para_req, db_path=db_p, record=r_para)

                dec_orig = res_orig["decision"]
                dec_para = res_para["decision"]

                if dec_orig == dec_para:
                    same += 1
                else:
                    diff += 1
                    flips_by_family[fam] += 1
                    if len(sample_flips) < 5:
                        sample_flips.append({
                            "case_id": cid,
                            "family_id": fam,
                            "orig_req": orig_req,
                            "para_req": para_req,
                            "orig_dec": dec_orig,
                            "para_dec": dec_para,
                            "orig_reasons": res_orig.get("reasons", []),
                            "para_reasons": res_para.get("reasons", []),
                        })

                # Compute per-field accuracy vs mechanical intent
                for mode, intent_obj in [("orig", intent_orig), ("para", intent_para)]:
                    field_stats[mode]["total"] += 1
                    if intent_obj.operation.lower() == mech.operation.lower():
                        field_stats[mode]["op"] += 1
                    if str(intent_obj.table).lower() == str(mech.table).lower():
                        field_stats[mode]["table"] += 1
                    
                    # filters
                    f_pred = set(str(c).lower().strip('"\'') for c in (intent_obj.filter_columns or []))
                    f_mech = set(str(c).lower().strip('"\'') for c in (mech.filter_columns or []))
                    if f_pred == f_mech or ('rowid' in f_mech and f_pred == set()):
                        field_stats[mode]["filters"] += 1
                    
                    # where_val
                    wv_p = str(intent_obj.where_val).lower().strip('"\'') if intent_obj.where_val is not None else ""
                    wv_m = str(mech.where_val).lower().strip('"\'') if mech.where_val is not None else ""
                    if wv_p == wv_m:
                        field_stats[mode]["where_val"] += 1

                    # set_assignments
                    s_p = {k.lower(): str(v).lower().strip('"\'') for k, v in (intent_obj.set_assignments or {}).items()}
                    s_m = {k.lower(): str(v).lower().strip('"\'') for k, v in (mech.set_assignments or {}).items()}
                    if s_p == s_m:
                        field_stats[mode]["set"] += 1

                    # cardinality
                    if str(intent_obj.expected_cardinality).lower() == str(mech.expected_cardinality).lower():
                        field_stats[mode]["card"] += 1

            agr_rate = (same / total * 100.0) if total else 100.0
            print(f"    Agreement: {same}/{total} ({agr_rate:.1f}%), Disagreements: {diff}")
            print(f"    Flips by family: {dict(flips_by_family)}")

            def calc_acc(stat_dict):
                tot = stat_dict["total"] or 1
                return {
                    "operation": round(stat_dict["op"] / tot * 100.0, 1),
                    "table": round(stat_dict["table"] / tot * 100.0, 1),
                    "filter_columns": round(stat_dict["filters"] / tot * 100.0, 1),
                    "where_val": round(stat_dict["where_val"] / tot * 100.0, 1),
                    "set_assignments": round(stat_dict["set"] / tot * 100.0, 1),
                    "cardinality": round(stat_dict["card"] / tot * 100.0, 1),
                }

            para_results[split_name][track_name] = {
                "total_cases": total,
                "agreement_count": same,
                "disagreement_count": diff,
                "agreement_rate": round(agr_rate, 2),
                "flips_by_family": dict(flips_by_family),
                "sample_flips": sample_flips,
                "orig_field_accuracy": calc_acc(field_stats["orig"]),
                "para_field_accuracy": calc_acc(field_stats["para"]),
            }

    out_p = os.path.join(RESULTS_DIR, "paraphrase_v23_results.json")
    with open(out_p, "w", encoding="utf-8") as f:
        json.dump(para_results, f, indent=2)
    print(f"\nSaved paraphrase results to {out_p}")

def main():
    tune, val = load_dev_data()
    evaluate_rewrites(tune, val)
    evaluate_paraphrases(tune, val)

if __name__ == "__main__":
    main()
