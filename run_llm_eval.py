"""
run_llm_eval.py
================
Resumable evaluation script for LLM extractor and LLM-as-judge on dev data.
Arguments:
  --split dev-tune|dev-val (default: dev-tune)
  --view pairs|full|write (default: full)
  --extractor llm|judge (default: llm)
  --smoke-test <n> (optional: run only first n cases)
  --seed <int> (optional: for judge seed)
  --bypass-cache (optional: bypass on-disk Ollama cache)
"""
import os
import sys
import json
import argparse
import time
from typing import List, Dict, Any

from evaluate_dev import load_dev_data, resolve_db_path, compute_metrics
from guardian_v2 import guardian_check_v2
from intent_extractors import LLMIntentExtractor
from llm_judge import LLMJudge
import ollama_client

def parse_args():
    parser = argparse.ArgumentParser(description="Run LLM evaluation on DEV data")
    parser.add_argument("--split", choices=["dev-tune", "dev-val", "both"], default="dev-tune")
    parser.add_argument("--view", choices=["pairs", "full", "write"], default="full")
    parser.add_argument("--extractor", choices=["llm", "judge"], default="llm")
    parser.add_argument("--smoke-test", type=int, default=0, help="Run only first N cases")
    parser.add_argument("--seed", type=int, default=42, help="Seed for LLM judge")
    parser.add_argument("--bypass-cache", action="store_true", help="Bypass on-disk Ollama cache")
    return parser.parse_args()

def filter_view(dataset: List[Dict[str, Any]], view: str) -> List[Dict[str, Any]]:
    if view == "pairs":
        # Unsafe cases + paired twins
        paired_json = json.load(open("data/evaluation_splits/dev_paired_dataset_v1.4.json"))
        unsafe_ids = set(r["case_id"] for r in paired_json if r.get("expected_decision_variant_a") == "BLOCK")
        twin_ids = set(r.get("twin_of") for r in paired_json if r.get("twin_of"))
        pairs_ids = unsafe_ids.union(twin_ids)
        return [r for r in dataset if r["case_id"] in pairs_ids]
    elif view == "write":
        return [r for r in dataset if r.get("family_id") != "MUT_BENIGN_READ_SELECT"]
    return list(dataset)

def main():
    args = parse_args()
    ident = ollama_client.get_model_identity()
    print(f"Ollama Model Identity: {ident['model_tag']} ({ident['parameter_size']}, {ident['quantization']}, digest={ident['digest'][:12]}...)")

    tune, val = load_dev_data()
    if args.split == "dev-tune":
        dataset = tune
    elif args.split == "dev-val":
        dataset = val
    else:
        dataset = tune + val

    dataset = filter_view(dataset, args.view)

    if args.smoke_test > 0:
        dataset = dataset[:args.smoke_test]

    total = len(dataset)
    print(f"Running evaluation: split={args.split}, view={args.view}, extractor={args.extractor}, cases={total}")

    # Results output file
    out_dir = os.path.join("results", "dev_audit")
    os.makedirs(out_dir, exist_ok=True)
    out_file = os.path.join(out_dir, f"decisions_{args.extractor}_{args.split}_{args.view}.jsonl")

    # Load existing progress if resuming
    existing_decisions = {}
    if os.path.exists(out_file) and not args.bypass_cache and args.smoke_test == 0:
        with open(out_file, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    item = json.loads(line)
                    existing_decisions[item["case_id"]] = item

        print(f"Resuming: found {len(existing_decisions)} existing evaluated cases.")

    extractor = LLMIntentExtractor(bypass_cache=args.bypass_cache) if args.extractor == "llm" else None
    judge = LLMJudge(seed=args.seed, bypass_cache=args.bypass_cache) if args.extractor == "judge" else None

    y_true = []
    y_pred = []
    t_start = time.perf_counter()

    for idx, r in enumerate(dataset, 1):
        cid = r["case_id"]
        target = r.get("expected_decision_variant_a", "BLOCK")
        db_path = resolve_db_path(r["database"])

        if cid in existing_decisions:
            saved = existing_decisions[cid]
            pred = saved["decision"]
            y_true.append(target)
            y_pred.append(pred)
            continue

        if args.extractor == "llm":
            # Run through guardian_v2 with extractor='llm'
            res = guardian_check_v2(
                user_request=r["request"],
                sql_str=r["sql"],
                db_path=db_path,
                record=r,
                layer=3,
                risk_mode="rules",
                extractor="llm",
                variant="variant_a"
            )
            pred = res["decision"]
            record_res = {
                "case_id": cid,
                "family_id": r.get("family_id"),
                "expected": target,
                "decision": pred,
                "layer_fired": res.get("layer_fired"),
                "reasons": res.get("reasons")
            }
        else:
            # LLM Judge baseline
            j_res = judge.judge(r["request"], r["sql"], db_path)
            pred = j_res["decision"]
            record_res = {
                "case_id": cid,
                "family_id": r.get("family_id"),
                "expected": target,
                "decision": pred,
                "reason": j_res.get("reason"),
                "raw_response": j_res.get("raw_response")
            }

        y_true.append(target)
        y_pred.append(pred)

        # Append to jsonl
        with open(out_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(record_res) + "\n")

        if idx % 5 == 0 or idx == total:
            elapsed = time.perf_counter() - t_start
            rate = idx / elapsed if elapsed > 0 else 0
            print(f"[{idx}/{total}] Evaluated. Elapsed: {elapsed:.1f}s ({rate:.2f} cases/s)")

    m = compute_metrics(y_true, y_pred)
    print("\n--- Evaluation Summary ---")
    print(f"Total Cases: {total}")
    print(f"Accuracy: {m['accuracy']:.4f}")
    print(f"Balanced Accuracy: {m['balanced_accuracy']:.4f}")
    print(f"Macro-F1: {m['macro_f1']:.4f}")
    print(f"Confusion Matrix [ALLOW, CONFIRM, BLOCK]:\n{m['confusion_matrix']}")
    if extractor:
        print(f"Extractor Truncations: {extractor.truncation_count}/{extractor.call_count}")
        print(f"Extractor Parse Failures: {extractor.parse_fail_count}/{extractor.call_count}")
    if judge:
        print(f"Judge Parse Failures: {judge.parse_fail_count}/{judge.call_count}")

if __name__ == "__main__":
    main()
