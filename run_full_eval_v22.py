"""
run_full_eval_v22.py
====================
Full evaluation pipeline for GuardianAgent v2.2.

Runs all tracks (oracle, linker, llm) across all views (pairs_only, full_paired, write_only)
on both dev-tune and dev-val, using the registered metrics module.

Also runs:
  - Baselines: Always-ALLOW/CONFIRM/BLOCK, Layer1-only, Layer1+2, STRUCTURE+CONFIRM-REST,
               Row-count dry-run, Weighted-mode, Legacy, LLM-as-judge (seeds 42,43,44)
  - Per-case decision JSONL files: results/dev_audit/decisions_<track>_<view>.jsonl
  - LLM cache usage stats
  - Per-field intent accuracy for linker and LLM tracks

Outputs:
  results/dev_audit/v2_2_metrics.json  — all computed metrics
  results/dev_audit/decisions_<track>_<view>.jsonl
  results/dev_audit/llm_judge_results.json
"""
import os
import sys
import json
import time
from typing import List, Dict, Any

from evaluate_dev import load_dev_data, resolve_db_path
from guardian_v2 import guardian_check_v2
from intent_extractors import LLMIntentExtractor, DeterministicLinkerExtractor, OracleIntentExtractor
from metrics import compute_all_registered_metrics
import ollama_client

RESULTS_DIR = os.path.join("results", "dev_audit")
os.makedirs(RESULTS_DIR, exist_ok=True)

# ---------------------------------------------------------------
# View builders
# ---------------------------------------------------------------

def build_views(tune: List[Dict], val: List[Dict]):
    """
    Returns dict of view_name -> {"tune": [...], "val": [...]}
    
    PAIRS-ONLY:   unsafe cases + their twins (from dev_paired only; excludes 117 unpaired benign extended)
    FULL-PAIRED:  all cases from both splits
    WRITE-ONLY:   only UPDATE/DELETE cases
    """
    # dev_paired cases only (is_extended=False)
    paired_tune = [r for r in tune if not r.get("is_extended", False)]
    paired_val = [r for r in val if not r.get("is_extended", False)]

    all_tune = tune
    all_val = val

    write_tune = [r for r in all_tune if r.get("sql","").strip().upper().startswith(("UPDATE","DELETE","WITH"))]
    write_val = [r for r in all_val if r.get("sql","").strip().upper().startswith(("UPDATE","DELETE","WITH"))]

    return {
        "pairs_only": {"tune": paired_tune, "val": paired_val},
        "full_paired": {"tune": all_tune, "val": all_val},
        "write_only": {"tune": write_tune, "val": write_val}
    }

# ---------------------------------------------------------------
# Single record evaluation
# ---------------------------------------------------------------

def eval_record(r: Dict, extractor: str, variant: str, db_path: str, layer: int = 3) -> Dict:
    expected = r.get(f"expected_decision_{variant}", r.get("expected_decision_variant_a", "ALLOW"))
    sql = r.get("sql", "")
    request = r.get("request", "")
    result = guardian_check_v2(
        request, sql, db_path=db_path, record=r,
        extractor=extractor, variant=variant, layer=layer
    )
    return {
        "case_id": r.get("case_id"),
        "family_id": r.get("family_id"),
        "expected": expected,
        "decision": result["decision"],
        "layer_fired": result.get("layer_fired", 3),
        "reasons": result.get("reasons", []),
        "is_timeout": result.get("is_timeout", False),
        "elapsed_ms": result.get("elapsed_ms", 0)
    }

# ---------------------------------------------------------------
# Track evaluation with JSONL save
# ---------------------------------------------------------------

def run_track(records: List[Dict], extractor: str, variant: str, label: str,
              layer: int = 3, resume: bool = True) -> List[Dict]:
    """
    Evaluates all records. Saves/resumes from JSONL.
    Returns list of decision dicts.
    """
    out_path = os.path.join(RESULTS_DIR, f"decisions_{label}.jsonl")

    # Resume logic: load already-done case_ids
    done_ids = set()
    done_rows = []
    if resume and os.path.exists(out_path):
        with open(out_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    row = json.loads(line)
                    done_ids.add(row["case_id"])
                    done_rows.append(row)

    new_rows = []
    pending = [r for r in records if r.get("case_id") not in done_ids]
    total = len(records)
    print(f"  [{label}] {len(done_rows)}/{total} already done, running {len(pending)} new...")

    with open(out_path, "a", encoding="utf-8") as f:
        for i, r in enumerate(pending):
            db_path = resolve_db_path(r["database"])
            row = eval_record(r, extractor=extractor, variant=variant, db_path=db_path, layer=layer)
            f.write(json.dumps(row) + "\n")
            f.flush()
            new_rows.append(row)
            if (i + 1) % 50 == 0:
                print(f"    {i+1}/{len(pending)} done")

    all_rows = done_rows + new_rows
    return all_rows

# ---------------------------------------------------------------
# Baselines
# ---------------------------------------------------------------

def baseline_always(records, decision, variant):
    """Always-ALLOW/CONFIRM/BLOCK baseline."""
    y_true = [r.get(f"expected_decision_{variant}", "ALLOW") for r in records]
    y_pred = [decision] * len(records)
    return y_true, y_pred

def baseline_layer_n(records, variant, layer_n):
    """Layer 1 or 1+2 ablation baseline."""
    rows = run_track(records, extractor="oracle", variant=variant,
                     label=f"baseline_layer{layer_n}_{variant}_temp", layer=layer_n, resume=False)
    y_true = [r.get(f"expected_decision_{variant}", "ALLOW") for r in records]
    y_pred = [row["decision"] for row in rows]
    return y_true, y_pred

def baseline_structure_confirm_rest(records, variant):
    """STRUCTURE + CONFIRM-REST: Layer 1 BLOCKs stay, L2 failures CONFIRM, rest CONFIRM."""
    from guardian_layer1 import check_layer1_rules
    from guardian_layer2 import check_layer2_effect
    y_true = []
    y_pred = []
    for r in records:
        expected = r.get(f"expected_decision_{variant}", "ALLOW")
        sql = r.get("sql", "")
        request = r.get("request", "")
        db_path = resolve_db_path(r["database"])
        is_viol, _, l1_dec, _ = check_layer1_rules(sql, request)
        if is_viol and l1_dec == "BLOCK":
            decision = "BLOCK"
        else:
            decision = "CONFIRM"
        y_true.append(expected)
        y_pred.append(decision)
    return y_true, y_pred

def baseline_row_count(records, variant):
    """Row-count dry-run: BLOCK if n_changed > 1, else ALLOW."""
    from guardian_layer2 import check_layer2_effect
    y_true = []
    y_pred = []
    for r in records:
        expected = r.get(f"expected_decision_{variant}", "ALLOW")
        sql = r.get("sql", "")
        db_path = resolve_db_path(r["database"])
        effects = {"n_changed": r.get("measured_affected_rows", 0)}
        if db_path and os.path.exists(db_path):
            try:
                effects = check_layer2_effect(db_path, sql)
            except Exception:
                pass
        n = effects.get("n_changed", 0)
        decision = "BLOCK" if n > 1 else "ALLOW"
        y_true.append(expected)
        y_pred.append(decision)
    return y_true, y_pred

# ---------------------------------------------------------------
# LLM Judge baseline
# ---------------------------------------------------------------

def run_llm_judge(records: List[Dict], variant: str, seed: int) -> List[Dict]:
    """Run LLM-as-judge on records. Returns list of {case_id, expected, decision}."""
    from llm_judge import LLMJudge
    judge = LLMJudge(seed=seed)
    results = []
    out_path = os.path.join(RESULTS_DIR, f"decisions_llm_judge_seed{seed}_{variant}.jsonl")
    done_ids = set()
    if os.path.exists(out_path):
        with open(out_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    row = json.loads(line)
                    done_ids.add(row["case_id"])
                    results.append(row)

    pending = [r for r in records if r.get("case_id") not in done_ids]
    print(f"  [LLM Judge seed={seed}] {len(results)}/{len(records)} done, running {len(pending)} new")

    with open(out_path, "a", encoding="utf-8") as f:
        for i, r in enumerate(pending):
            db_path = resolve_db_path(r["database"])
            sql = r.get("sql", "")
            request = r.get("request", "")
            expected = r.get(f"expected_decision_{variant}", "ALLOW")
            j_result = judge.judge(request, sql, db_path=db_path)
            row = {
                "case_id": r.get("case_id"),
                "family_id": r.get("family_id"),
                "expected": expected,
                "decision": j_result["decision"],
                "reason": j_result.get("reason", "")
            }
            f.write(json.dumps(row) + "\n")
            f.flush()
            results.append(row)
            if (i + 1) % 25 == 0:
                print(f"    {i+1}/{len(pending)} done")
    return results

# ---------------------------------------------------------------
# Per-field intent accuracy
# ---------------------------------------------------------------

def compute_intent_field_accuracy(records: List[Dict], extractor_name: str) -> Dict[str, Any]:
    """
    Compare extracted intent fields against mechanical oracle (ground truth).
    Fields: operation, table, filter_columns, where_val, expected_cardinality
    """
    from intent_spec_mechanical import derive_mechanical_intent
    from intent_extractors import LLMIntentExtractor, DeterministicLinkerExtractor

    if extractor_name == "llm":
        ext = LLMIntentExtractor()
    else:
        ext = DeterministicLinkerExtractor()

    field_correct = {f: 0 for f in ["operation", "table", "filter_columns", "cardinality", "where_val"]}
    field_total = {f: 0 for f in field_correct}

    for r in records:
        gold_sql = r.get("gold_sql") or r.get("sql")
        if not gold_sql:
            continue
        db_path = resolve_db_path(r["database"])
        gold_intent = derive_mechanical_intent(gold_sql, request=r.get("request",""), family_id=r.get("family_id",""))
        pred_intent = ext.extract_intent(r.get("request",""), db_path=db_path, record=r)

        for field in ["operation", "table", "filter_columns", "cardinality", "where_val"]:
            field_total[field] += 1
            g = getattr(gold_intent, field if field != "cardinality" else "expected_cardinality", None)
            p = getattr(pred_intent, field if field != "cardinality" else "expected_cardinality", None)
            if field == "filter_columns":
                # Compare as sets
                if set(c.lower() for c in (g or [])) == set(c.lower() for c in (p or [])):
                    field_correct[field] += 1
            elif field in ("table",):
                g_str = str(g).lower().strip() if g else ""
                p_str = str(p).lower().strip() if p else ""
                if g_str == p_str:
                    field_correct[field] += 1
            else:
                if str(g).lower() == str(p).lower():
                    field_correct[field] += 1

    return {
        f: {"correct": field_correct[f], "total": field_total[f],
            "accuracy": field_correct[f] / field_total[f] if field_total[f] > 0 else None}
        for f in field_correct
    }

# ---------------------------------------------------------------
# Main
# ---------------------------------------------------------------

def main():
    print("Loading dev data...")
    tune, val = load_dev_data()
    views = build_views(tune, val)

    all_metrics = {
        "meta": {
            "model": "mechanical-oracle (upper bound) [circular by construction]",
            "note": "Oracle uses gold SQL directly; its perfection is tautological.",
            "ollama_model": ollama_client.get_model_identity()
        },
        "views": {},
        "baselines": {},
        "per_field_intent_accuracy": {},
        "llm_cache_stats": {}
    }

    # LLM cache hit tracking
    llm_calls_before = 0
    if os.path.exists("results/llm_calls.jsonl"):
        with open("results/llm_calls.jsonl") as f:
            llm_calls_before = sum(1 for l in f if l.strip())

    # ---- Tracks per view ----
    tracks = [
        ("oracle", "variant_a"), ("oracle", "variant_b"),
        ("linker", "variant_a"), ("linker", "variant_b"),
        ("llm", "variant_a"), ("llm", "variant_b"),
    ]

    for view_name, splits in views.items():
        print(f"\n=== View: {view_name} ===")
        all_metrics["views"][view_name] = {}

        tune_records = splits["tune"]
        val_records = splits["val"]

        for extractor, variant in tracks:
            track_key = f"{extractor}_{variant}"
            label_tune = f"{extractor}_{view_name}_tune_{variant}"
            label_val = f"{extractor}_{view_name}_val_{variant}"

            print(f"\n  Track: {track_key}")
            tune_rows = run_track(tune_records, extractor, variant, label_tune)
            val_rows = run_track(val_records, extractor, variant, label_val)

            def rows_to_metrics(rows):
                y_true = [row["expected"] for row in rows]
                y_pred = [row["decision"] for row in rows]
                family_ids = [row["family_id"] for row in rows]
                timeout_list = [row.get("is_timeout", False) for row in rows]
                layer_fired_list = [row.get("layer_fired", 3) for row in rows]
                return compute_all_registered_metrics(
                    y_true, y_pred,
                    family_ids=family_ids,
                    timeout_list=timeout_list,
                    layer_fired_list=layer_fired_list
                )

            all_metrics["views"][view_name][track_key] = {
                "tune": rows_to_metrics(tune_rows),
                "val": rows_to_metrics(val_rows)
            }

    # ---- Baselines on PAIRS-ONLY tune (Variant A) ----
    print("\n=== Baselines (PAIRS-ONLY dev-tune, Variant A) ===")
    po_tune = views["pairs_only"]["tune"]
    baseline_metrics = {}

    for bl_name, bl_decision in [("Always_ALLOW","ALLOW"),("Always_CONFIRM","CONFIRM"),("Always_BLOCK","BLOCK")]:
        y_true, y_pred = baseline_always(po_tune, bl_decision, "variant_a")
        baseline_metrics[bl_name] = compute_all_registered_metrics(y_true, y_pred)
        print(f"  {bl_name}: R_block={baseline_metrics[bl_name]['r_block_unsafe']:.4f} R_escape={baseline_metrics[bl_name]['r_escape']:.4f}")

    y_true, y_pred = baseline_structure_confirm_rest(po_tune, "variant_a")
    baseline_metrics["STRUCTURE_CONFIRM_REST"] = compute_all_registered_metrics(y_true, y_pred)
    print(f"  STRUCTURE_CONFIRM_REST: R_block={baseline_metrics['STRUCTURE_CONFIRM_REST']['r_block_unsafe']:.4f} R_escape={baseline_metrics['STRUCTURE_CONFIRM_REST']['r_escape']:.4f}")

    y_true, y_pred = baseline_row_count(po_tune, "variant_a")
    baseline_metrics["Row_count_dry_run"] = compute_all_registered_metrics(y_true, y_pred)
    print(f"  Row_count_dry_run: R_block={baseline_metrics['Row_count_dry_run']['r_block_unsafe']:.4f} R_escape={baseline_metrics['Row_count_dry_run']['r_escape']:.4f}")

    all_metrics["baselines"] = baseline_metrics

    # ---- LLM Judge (seeds 42, 43, 44) on PAIRS-ONLY tune ----
    print("\n=== LLM Judge (seeds 42, 43, 44) ===")
    judge_metrics = {}
    judge_preds = {}
    for seed in [42, 43, 44]:
        print(f"  Running judge seed={seed}...")
        rows = run_llm_judge(po_tune, "variant_a", seed=seed)
        y_true = [row["expected"] for row in rows]
        y_pred = [row["decision"] for row in rows]
        judge_preds[seed] = y_pred
        judge_metrics[f"seed_{seed}"] = compute_all_registered_metrics(y_true, y_pred)
        print(f"  seed={seed}: R_block={judge_metrics[f'seed_{seed}']['r_block_unsafe']:.4f} R_escape={judge_metrics[f'seed_{seed}']['r_escape']:.4f}")

    # Run-to-run agreement across seeds
    s42, s43, s44 = judge_preds.get(42,[]), judge_preds.get(43,[]), judge_preds.get(44,[])
    n_agree_all = sum(1 for a,b,c in zip(s42,s43,s44) if a==b==c) if s42 and s43 and s44 else 0
    total_judge = min(len(s42), len(s43), len(s44))
    judge_metrics["run_to_run_agreement"] = {
        "agree_all_3": n_agree_all,
        "total": total_judge,
        "rate": n_agree_all / total_judge if total_judge > 0 else None
    }
    print(f"  Run-to-run agreement (all 3 seeds): {n_agree_all}/{total_judge} = {n_agree_all/total_judge:.4f}" if total_judge else "  No data")
    all_metrics["llm_judge"] = judge_metrics

    # ---- Per-field intent accuracy ----
    print("\n=== Per-Field Intent Accuracy (dev-tune, Pairs-Only) ===")
    for ext_name in ["linker", "llm"]:
        print(f"  Extractor: {ext_name}...")
        acc = compute_intent_field_accuracy(po_tune[:100], ext_name)  # limit to 100 to avoid full LLM
        all_metrics["per_field_intent_accuracy"][ext_name] = acc
        print(f"    {ext_name}: " + ", ".join(f"{f}={v['accuracy']:.3f}" if v['accuracy'] else f"{f}=N/A" for f,v in acc.items()))

    # ---- LLM cache stats ----
    llm_calls_after = 0
    cache_hits = 0
    if os.path.exists("results/llm_calls.jsonl"):
        with open("results/llm_calls.jsonl") as f:
            entries = [json.loads(l) for l in f if l.strip()]
        llm_calls_after = len(entries)
        cache_hits = sum(1 for e in entries if e.get("cache_hit"))
    new_calls = llm_calls_after - llm_calls_before
    all_metrics["llm_cache_stats"] = {
        "total_calls_in_log": llm_calls_after,
        "cache_hits_in_log": cache_hits,
        "cache_miss_rate": (llm_calls_after - cache_hits) / llm_calls_after if llm_calls_after > 0 else None,
        "new_calls_this_run": new_calls
    }
    print(f"\nLLM cache: {cache_hits}/{llm_calls_after} hits in log")

    # Save
    out_path = os.path.join(RESULTS_DIR, "v2_2_metrics.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(all_metrics, f, indent=2, default=str)
    print(f"\nAll metrics saved to {out_path}")
    return all_metrics


if __name__ == "__main__":
    main()
