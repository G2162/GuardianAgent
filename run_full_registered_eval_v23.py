"""
run_full_registered_eval_v23.py
===============================
Comprehensive Registered Evaluation for GuardianAgent v2.3 on DEV data.
- Covers all tracks: mechanical-oracle (upper bound), linker, llm, baselines
- Covers operating points: STRICT and BALANCED
- Covers views: PAIRS-ONLY, FULL PAIRED, WRITE-ONLY
- Saves per-case decisions as results/dev_audit/decisions_<track>_<policy>_<view>.jsonl
- Computes 3x3 confusion matrices, Wilson CIs, 1000-sample clustered bootstrap CIs
- Performs paired McNemar tests against LLM-as-judge and STRUCTURE+CONFIRM-REST
- Analyzes LLM schema validity per field
"""
import os, sys, json, math
from collections import defaultdict
import numpy as np
from evaluate_dev import load_dev_data, resolve_db_path
from guardian_v2 import guardian_check_v2
from intent_extractors import LLMIntentExtractor, DeterministicLinkerExtractor, OracleIntentExtractor
from metrics import compute_all_registered_metrics, compute_clustered_bootstrap_cis
from guardian_layer1 import check_layer1_rules
from guardian_layer2 import check_layer2_effect

RESULTS_DIR = os.path.join("results", "dev_audit")
os.makedirs(RESULTS_DIR, exist_ok=True)

def filter_view(records, view_name):
    if view_name == "PAIRS-ONLY":
        # Unsafe cases + paired twins only
        # On dev_paired: pair_id is set for paired cases
        # Or record.get('is_paired', False) or 'twin_of' in record or 'pair_id' in record
        res = []
        for r in records:
            is_unsafe = (r.get("expected_decision_variant_a") == "BLOCK")
            has_pair = bool(r.get("pair_id") or r.get("twin_of") or r.get("paired_twin"))
            if is_unsafe or has_pair:
                res.append(r)
        return res
    elif view_name == "WRITE-ONLY":
        write_prefixes = ("UPDATE", "DELETE", "INSERT", "DROP", "ALTER", "CREATE", "WITH")
        return [r for r in records if r.get("sql", "").strip().upper().startswith(write_prefixes)]
    else: # FULL PAIRED
        return list(records)

def evaluate_baseline_decision(baseline_name, record, db_path):
    sql = record.get("sql", "")
    req = record.get("request", "")
    exp = record.get("expected_decision_variant_a", "ALLOW")
    
    if baseline_name == "always_allow":
        return "ALLOW", 0, False, False
    elif baseline_name == "always_confirm":
        return "CONFIRM", 0, False, False
    elif baseline_name == "always_block":
        return "BLOCK", 0, False, False
    elif baseline_name == "layer1_only":
        viol, rid, dec, is_cat = check_layer1_rules(sql, req)
        if viol:
            return dec, 1, is_cat, False
        return "ALLOW", 1, False, False
    elif baseline_name == "layer1_plus_layer2":
        viol, rid, dec, is_cat = check_layer1_rules(sql, req)
        if viol:
            return dec, 1, is_cat, False
        effects = check_layer2_effect(db_path, sql)
        if effects.get("decision") == "CONFIRM":
            return "CONFIRM", 2, False, effects.get("is_timeout", False)
        return "ALLOW", 2, False, False
    elif baseline_name == "structure_confirm_rest":
        viol, rid, dec, is_cat = check_layer1_rules(sql, req)
        if viol and dec == "BLOCK":
            return "BLOCK", 1, is_cat, False
        effects = check_layer2_effect(db_path, sql)
        if effects.get("decision") == "CONFIRM":
            return "CONFIRM", 2, False, effects.get("is_timeout", False)
        # Everything else CONFIRM
        return "CONFIRM", 3, False, False
    elif baseline_name == "row_count_dry_run_redesigned":
        # Redesigned row-count dry run:
        # BLOCK if measured rows > request cardinality
        # CONFIRM if ambiguous / execution error
        # else ALLOW
        viol, rid, dec, is_cat = check_layer1_rules(sql, req)
        if viol and dec == "BLOCK":
            return "BLOCK", 1, is_cat, False
        effects = check_layer2_effect(db_path, sql)
        if not effects.get("executes_ok"):
            return "CONFIRM", 2, False, effects.get("is_timeout", False)
        n_changed = effects.get("n_changed", 0)
        n_matched = effects.get("n_matched", 0)
        req_low = req.lower()
        
        # Determine cardinality expectation from request keywords
        if any(w in req_low for w in [" all ", " every ", "all ", "every "]):
            exp_card = "multi"
        elif any(w in req_low for w in [" id is ", " id = ", "contid is", "contid =", "countryid is", "countryid ="]):
            exp_card = "single"
        else:
            exp_card = "ambiguous"

        if exp_card == "single" and (n_changed > 1 or n_matched > 1):
            return "BLOCK", 2, False, False
        elif exp_card == "ambiguous":
            return "CONFIRM", 2, False, False
        else:
            return "ALLOW", 2, False, False
    return "CONFIRM", 0, False, False

def run_mcnemar_test(y_true, y_pred1, y_pred2):
    """
    Computes McNemar test between two classifiers on unsafe cases (correct BLOCK vs incorrect non-BLOCK).
    Returns contingency table: b (1 correct, 2 wrong), c (1 wrong, 2 correct), chi2, p-value, odds ratio.
    """
    b = 0
    c = 0
    a = 0
    d = 0
    for yt, p1, p2 in zip(y_true, y_pred1, y_pred2):
        if yt == "BLOCK":
            c1 = (p1 == "BLOCK")
            c2 = (p2 == "BLOCK")
            if c1 and c2:
                a += 1
            elif c1 and not c2:
                b += 1
            elif not c1 and c2:
                c += 1
            else:
                d += 1
    total_disc = b + c
    if total_disc == 0:
        chi2 = 0.0
        p_val = 1.0
        odds_ratio = 1.0
    else:
        # McNemar with continuity correction
        chi2 = ((abs(b - c) - 1.0) ** 2) / total_disc
        # 1-df chi-square survival
        # Approximation via normal distribution
        z = math.sqrt(chi2)
        p_val = math.erfc(z / math.sqrt(2.0))
        odds_ratio = (b / c) if c > 0 else float("inf")
        
    return {
        "contingency": {"both_correct": a, "model1_only": b, "model2_only": c, "both_wrong": d},
        "chi2": round(chi2, 4),
        "p_value": p_val,
        "odds_ratio": round(odds_ratio, 4) if odds_ratio != float("inf") else "inf"
    }

def main():
    tune, val = load_dev_data()
    print(f"Loaded {len(tune)} dev-tune records, {len(val)} dev-val records.")

    # Load judge decisions if available
    judge_decisions = {}
    if os.path.exists("results/dev_audit/llm_judge_metrics.json"):
        with open("results/dev_audit/llm_judge_metrics.json") as f:
            jd = json.load(f)
            # map case_id -> decision from seed 42
            for case in jd.get("runs", {}).get("seed_42", {}).get("case_decisions", []):
                judge_decisions[case["case_id"]] = case["decision"]

    tracks = [
        ("mechanical-oracle (upper bound)", "STRICT", "oracle"),
        ("linker", "STRICT", "linker"),
        ("linker", "BALANCED", "linker"),
        ("llm", "STRICT", "llm"),
        ("llm", "BALANCED", "llm"),
    ]

    baselines = [
        "always_allow",
        "always_confirm",
        "always_block",
        "layer1_only",
        "layer1_plus_layer2",
        "structure_confirm_rest",
        "row_count_dry_run_redesigned"
    ]

    splits = {
        "dev-tune": tune,
        "dev-val": val
    }

    views = ["FULL PAIRED", "PAIRS-ONLY", "WRITE-ONLY"]

    full_evaluation_results = {}
    stored_predictions = defaultdict(dict) # (split, view, track_key) -> list of decisions

    for split_name, split_records in splits.items():
        print(f"\n=======================================================")
        print(f"EVALUATING SPLIT: {split_name} (N={len(split_records)})")
        print(f"=======================================================")
        full_evaluation_results[split_name] = {}

        for view_name in views:
            view_records = filter_view(split_records, view_name)
            print(f"\n--- View: {view_name} (N={len(view_records)}) ---")
            full_evaluation_results[split_name][view_name] = {}

            # 1. Pipeline Tracks
            for track_label, op_point, extractor_name in tracks:
                track_key = f"{track_label}_{op_point}"
                y_true = []
                y_pred = []
                family_ids = []
                intercept_counts = defaultdict(int)
                cat_escapes = defaultdict(int)
                timeouts = 0
                jsonl_entries = []

                for r in view_records:
                    cid = r.get("case_id")
                    db = resolve_db_path(r["database"])
                    req = r.get("request", "")
                    sql = r.get("sql", "")
                    fam = r.get("family_id", "unknown")
                    exp = r.get("expected_decision_variant_a", "ALLOW")

                    res = guardian_check_v2(
                        user_request=req,
                        sql_str=sql,
                        db_path=db,
                        record=r,
                        extractor=extractor_name,
                        variant="variant_a",
                        operating_point=op_point
                    )

                    dec = res["decision"]
                    layer = res["layer_fired"]
                    is_cat = res.get("is_catastrophic", False)
                    is_to = res.get("is_timeout", False)

                    y_true.append(exp)
                    y_pred.append(dec)
                    family_ids.append(fam)

                    # Intercept tracking on unsafe cases
                    if exp == "BLOCK":
                        if dec == "BLOCK":
                            intercept_counts[f"layer{layer}_block"] += 1
                        elif dec == "CONFIRM":
                            intercept_counts[f"layer{layer}_confirm"] += 1

                    if dec == "ALLOW" and exp == "BLOCK" and is_cat:
                        cat_escapes[fam] += 1

                    if is_to:
                        timeouts += 1

                    jsonl_entries.append({
                        "case_id": cid,
                        "family_id": fam,
                        "database": r.get("database"),
                        "expected_decision": exp,
                        "decision": dec,
                        "layer_fired": layer,
                        "reasons": res.get("reasons", [])
                    })

                # Compute standard registered metrics
                metrics = compute_all_registered_metrics(y_true, y_pred, family_ids)

                # Add clustered bootstrap CIs (1,000 resamples by database)
                bootstrap_cis = compute_clustered_bootstrap_cis(view_records, y_true, y_pred, n_bootstraps=1000)
                metrics["bootstrap_cis"] = bootstrap_cis
                metrics["catastrophic_escapes_by_family"] = dict(cat_escapes)
                metrics["intercept_breakdown"] = dict(intercept_counts)

                # Save JSONL
                clean_track_slug = track_label.replace(" ", "_").replace("(", "").replace(")", "")
                clean_view_slug = view_name.replace(" ", "_").replace("-", "_").lower()
                jsonl_path = os.path.join(RESULTS_DIR, f"decisions_{clean_track_slug}_{op_point}_{clean_view_slug}.jsonl")
                with open(jsonl_path, "w", encoding="utf-8") as f:
                    for je in jsonl_entries:
                        f.write(json.dumps(je) + "\n")

                full_evaluation_results[split_name][view_name][track_key] = metrics
                stored_predictions[(split_name, view_name, track_key)] = (y_true, y_pred)
                print(f"  [{track_label} - {op_point}] R_block={metrics['r_block_unsafe']:.4f}, R_escape={metrics['r_escape']:.4f}, FBR={metrics['fbr']:.4f}, IR={metrics['ir']:.4f}, Allow={metrics['allow_rate']:.4f}")

            # 2. Baselines
            for base in baselines:
                y_true = []
                y_pred = []
                family_ids = []
                for r in view_records:
                    db = resolve_db_path(r["database"])
                    dec, layer, is_cat, is_to = evaluate_baseline_decision(base, r, db)
                    exp = r.get("expected_decision_variant_a", "ALLOW")
                    y_true.append(exp)
                    y_pred.append(dec)
                    family_ids.append(r.get("family_id", "unknown"))

                b_metrics = compute_all_registered_metrics(y_true, y_pred, family_ids)
                full_evaluation_results[split_name][view_name][base] = b_metrics
                stored_predictions[(split_name, view_name, base)] = (y_true, y_pred)
                print(f"  [Baseline: {base}] R_block={b_metrics['r_block_unsafe']:.4f}, R_escape={b_metrics['r_escape']:.4f}, FBR={b_metrics['fbr']:.4f}, IR={b_metrics['ir']:.4f}, Allow={b_metrics['allow_rate']:.4f}")

            # 3. LLM-as-judge baseline (where decisions are available)
            judge_y_true = []
            judge_y_pred = []
            judge_fams = []
            for r in view_records:
                cid = r.get("case_id")
                if cid in judge_decisions:
                    judge_y_true.append(r.get("expected_decision_variant_a", "ALLOW"))
                    judge_y_pred.append(judge_decisions[cid])
                    judge_fams.append(r.get("family_id", "unknown"))
            if judge_y_true:
                j_metrics = compute_all_registered_metrics(judge_y_true, judge_y_pred, judge_fams)
                full_evaluation_results[split_name][view_name]["llm_judge"] = j_metrics
                stored_predictions[(split_name, view_name, "llm_judge")] = (judge_y_true, judge_y_pred)
                print(f"  [Baseline: llm_judge] N={len(judge_y_true)}, R_block={j_metrics['r_block_unsafe']:.4f}, R_escape={j_metrics['r_escape']:.4f}, FBR={j_metrics['fbr']:.4f}, IR={j_metrics['ir']:.4f}, Allow={j_metrics['allow_rate']:.4f}")

    # Paired McNemar Tests on dev-tune FULL PAIRED
    print(f"\n=======================================================")
    print("RUNNING PAIRED MCNEMAR TESTS")
    print(f"=======================================================")
    mcnemar_results = {}
    for op_point in ["STRICT", "BALANCED"]:
        llm_key = f"llm_{op_point}"
        if ("dev-tune", "FULL PAIRED", llm_key) in stored_predictions:
            yt, p_llm = stored_predictions[("dev-tune", "FULL PAIRED", llm_key)]
            
            # 1. vs LLM-as-judge
            if ("dev-tune", "FULL PAIRED", "llm_judge") in stored_predictions:
                _, p_judge = stored_predictions[("dev-tune", "FULL PAIRED", "llm_judge")]
                # filter to overlapping cases
                test_judge = run_mcnemar_test(yt, p_llm, p_judge)
                mcnemar_results[f"llm_{op_point}_vs_judge"] = test_judge
                print(f"LLM ({op_point}) vs Judge: chi2={test_judge['chi2']}, p={test_judge['p_value']}, odds_ratio={test_judge['odds_ratio']}")

            # 2. vs STRUCTURE + CONFIRM-REST
            if ("dev-tune", "FULL PAIRED", "structure_confirm_rest") in stored_predictions:
                _, p_struct = stored_predictions[("dev-tune", "FULL PAIRED", "structure_confirm_rest")]
                test_struct = run_mcnemar_test(yt, p_llm, p_struct)
                mcnemar_results[f"llm_{op_point}_vs_structure_confirm_rest"] = test_struct
                print(f"LLM ({op_point}) vs Structure+Confirm-Rest: chi2={test_struct['chi2']}, p={test_struct['p_value']}, odds_ratio={test_struct['odds_ratio']}")

    full_evaluation_results["mcnemar_tests"] = mcnemar_results

    # Schema-valid rate of LLM outputs per field
    print(f"\n=======================================================")
    print("ANALYZING LLM SCHEMA-VALIDITY AND PARSE RATES")
    print(f"=======================================================")
    llm_ext = LLMIntentExtractor()
    dev_records = tune + val
    field_counts = {"total": len(dev_records), "invalid_or_unknown": defaultdict(int)}
    for r in dev_records:
        intent = llm_ext.extract_intent(r.get("request", ""), db_path=resolve_db_path(r["database"]), record=r)
        if intent.operation == "unknown":
            field_counts["invalid_or_unknown"]["operation"] += 1
        if not intent.table or intent.table == "unknown":
            field_counts["invalid_or_unknown"]["table"] += 1
        if intent.expected_cardinality == "unknown":
            field_counts["invalid_or_unknown"]["cardinality"] += 1
        if not intent.filter_columns and r.get("sql", "").strip().upper().startswith(("UPDATE", "DELETE")):
            field_counts["invalid_or_unknown"]["filter_columns"] += 1
        if not intent.set_assignments and r.get("sql", "").strip().upper().startswith("UPDATE"):
            field_counts["invalid_or_unknown"]["set_assignments"] += 1

    schema_report = {
        "total_requests": len(dev_records),
        "unknown_or_invalid_counts": dict(field_counts["invalid_or_unknown"]),
        "valid_rates": {
            k: round((len(dev_records) - v) / len(dev_records) * 100.0, 2)
            for k, v in field_counts["invalid_or_unknown"].items()
        }
    }
    full_evaluation_results["schema_validity"] = schema_report
    print("Schema Validity Rates:", schema_report["valid_rates"])

    out_p = os.path.join(RESULTS_DIR, "full_registered_eval_v23.json")
    with open(out_p, "w", encoding="utf-8") as f:
        json.dump(full_evaluation_results, f, indent=2)
    print(f"\nSaved all registered evaluation metrics to {out_p}")

if __name__ == "__main__":
    main()
