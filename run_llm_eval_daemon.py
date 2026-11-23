"""
run_llm_eval_daemon.py
======================
Long-running resumable LLM eval daemon for all views.
Supports cache (skips already-computed cases). Run as background.
"""
import os, json
from evaluate_dev import load_dev_data, resolve_db_path
from guardian_v2 import guardian_check_v2
from metrics import compute_all_registered_metrics

RESULTS_DIR = os.path.join("results", "dev_audit")
os.makedirs(RESULTS_DIR, exist_ok=True)

def build_views(tune, val):
    paired_tune = [r for r in tune if not r.get("is_extended", False)]
    paired_val  = [r for r in val  if not r.get("is_extended", False)]
    write_tune  = [r for r in tune if r.get("sql","").strip().upper().startswith(("UPDATE","DELETE","WITH"))]
    write_val   = [r for r in val  if r.get("sql","").strip().upper().startswith(("UPDATE","DELETE","WITH"))]
    return {
        "pairs_only": {"tune": paired_tune, "val": paired_val},
        "full_paired": {"tune": tune, "val": val},
        "write_only":  {"tune": write_tune,  "val": write_val},
    }

def run_track_llm(records, variant, label):
    out_path = os.path.join(RESULTS_DIR, f"decisions_{label}.jsonl")
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
        print(f"  {label}: all {len(done_rows)} already done")
        return done_rows
    print(f"  {label}: {len(done_rows)} done, {len(pending)} pending")
    new_rows = []
    with open(out_path, "a") as f:
        for i, r in enumerate(pending):
            db_path = resolve_db_path(r["database"])
            expected = r.get(f"expected_decision_{variant}",
                             r.get("expected_decision_variant_a","ALLOW"))
            res = guardian_check_v2(r["request"], r.get("sql",""), db_path=db_path,
                                    record=r, extractor="llm", variant=variant)
            row = {"case_id": r.get("case_id"), "family_id": r.get("family_id"),
                   "expected": expected, "decision": res["decision"],
                   "layer_fired": res.get("layer_fired",3),
                   "reasons": res.get("reasons",[]),
                   "is_timeout": res.get("is_timeout",False)}
            f.write(json.dumps(row) + "\n")
            f.flush()
            new_rows.append(row)
            if (i+1) % 20 == 0:
                print(f"    {i+1}/{len(pending)} ({label})")
    return done_rows + new_rows

def main():
    tune, val = load_dev_data()
    views = build_views(tune, val)
    result = {"views": {}}

    # Priority order: pairs_only first (most important), then full_paired, write_only
    view_order = ["pairs_only", "full_paired", "write_only"]
    for view_name in view_order:
        splits = views[view_name]
        result["views"][view_name] = {}
        for variant in ("variant_a", "variant_b"):
            tk = f"llm_{variant}"
            result["views"][view_name][tk] = {}
            for split_name, records in [("tune", splits["tune"]), ("val", splits["val"])]:
                if not records:
                    result["views"][view_name][tk][split_name] = {"n": 0}
                    continue
                label = f"llm_{view_name}_{split_name}_{variant}"
                rows = run_track_llm(records, variant, label)
                y_true = [r["expected"] for r in rows]
                y_pred = [r["decision"] for r in rows]
                fids   = [r["family_id"] for r in rows]
                lf     = [r.get("layer_fired",3) for r in rows]
                tl     = [r.get("is_timeout",False) for r in rows]
                m = compute_all_registered_metrics(y_true, y_pred, family_ids=fids,
                                                   layer_fired_list=lf, timeout_list=tl)
                result["views"][view_name][tk][split_name] = m
                if m.get("n",0) > 0:
                    print(f"  DONE {label}: R_block={m['r_block_unsafe']:.4f} R_escape={m['r_escape']:.4f} FBR={m['fbr']:.4f}")

    out = os.path.join(RESULTS_DIR, "v2_2_metrics_llm.json")
    with open(out, "w") as f:
        json.dump(result, f, indent=2, default=str)
    print(f"\nAll LLM metrics saved to {out}")

if __name__ == "__main__":
    main()
