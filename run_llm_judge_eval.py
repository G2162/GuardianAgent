"""
run_llm_judge_eval.py
=====================
Run LLM-as-judge on PAIRS-ONLY dev-tune for seeds 42, 43, 44.
Saves per-seed decisions and computes metrics + run-to-run agreement.
"""
import os, json
from evaluate_dev import load_dev_data, resolve_db_path
from llm_judge import LLMJudge
from metrics import compute_all_registered_metrics

RESULTS_DIR = os.path.join("results", "dev_audit")
os.makedirs(RESULTS_DIR, exist_ok=True)

def run_judge_seed(records, variant, seed):
    judge = LLMJudge(seed=seed)
    out_path = os.path.join(RESULTS_DIR, f"decisions_llm_judge_seed{seed}_{variant}.jsonl")
    done_ids = set()
    done_rows = []
    if os.path.exists(out_path):
        with open(out_path) as f:
            for line in f:
                if line.strip():
                    r = json.loads(line)
                    done_ids.add(r["case_id"])
                    done_rows.append(r)
    pending = [r for r in records if r.get("case_id") not in done_ids]
    if not pending:
        print(f"  seed={seed}: all {len(done_rows)} already done")
        return done_rows
    print(f"  seed={seed}: {len(done_rows)} done, {len(pending)} pending")
    new_rows = []
    with open(out_path, "a") as f:
        for i, r in enumerate(pending):
            db_path = resolve_db_path(r["database"])
            sql = r.get("sql", "")
            request = r.get("request", "")
            expected = r.get(f"expected_decision_{variant}", r.get("expected_decision_variant_a","ALLOW"))
            j = judge.judge(request, sql, db_path=db_path)
            row = {"case_id": r.get("case_id"), "family_id": r.get("family_id"),
                   "expected": expected, "decision": j["decision"], "reason": j.get("reason","")}
            f.write(json.dumps(row) + "\n")
            f.flush()
            new_rows.append(row)
            if (i+1) % 10 == 0:
                print(f"    {i+1}/{len(pending)}")
    return done_rows + new_rows

def main():
    tune, val = load_dev_data()
    po_tune = [r for r in tune if not r.get("is_extended", False)]
    print(f"LLM Judge on PAIRS-ONLY dev-tune: {len(po_tune)} cases")

    variant = "variant_a"
    all_preds = {}
    judge_metrics = {}

    for seed in [42, 43, 44]:
        rows = run_judge_seed(po_tune, variant, seed)
        y_true = [r["expected"] for r in rows]
        y_pred = [r["decision"] for r in rows]
        m = compute_all_registered_metrics(y_true, y_pred)
        judge_metrics[f"seed_{seed}"] = m
        all_preds[seed] = y_pred
        if m.get("n",0) > 0:
            print(f"  seed={seed}: R_block={m['r_block_unsafe']:.4f} R_escape={m['r_escape']:.4f} FBR={m['fbr']:.4f} IR={m['ir']:.4f}")

    # Run-to-run agreement
    s42, s43, s44 = all_preds.get(42,[]), all_preds.get(43,[]), all_preds.get(44,[])
    n = min(len(s42), len(s43), len(s44))
    agree_all = sum(1 for a,b,c in zip(s42[:n], s43[:n], s44[:n]) if a==b==c)
    judge_metrics["run_to_run_agreement"] = {
        "agree_all_3": agree_all, "total": n,
        "rate": agree_all/n if n>0 else None
    }
    print(f"\nRun-to-run agreement (all 3): {agree_all}/{n} = {agree_all/n:.4f}" if n else "No data")

    out = os.path.join(RESULTS_DIR, "llm_judge_metrics.json")
    with open(out, "w") as f:
        json.dump(judge_metrics, f, indent=2, default=str)
    print(f"Saved to {out}")

if __name__ == "__main__":
    main()
