"""
run_oracle_linker_eval.py
=========================
Fast eval of oracle and linker tracks across all views and splits.
No LLM calls. Writes per-case JSONL and computes all metrics.
Outputs: results/dev_audit/v2_2_metrics_oracle_linker.json
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

def run_track(records, extractor, variant, label):
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
    new_rows = []
    with open(out_path, "a") as f:
        for r in pending:
            db_path = resolve_db_path(r["database"])
            expected = r.get(f"expected_decision_{variant}", r.get("expected_decision_variant_a","ALLOW"))
            res = guardian_check_v2(r["request"], r.get("sql",""), db_path=db_path,
                                    record=r, extractor=extractor, variant=variant)
            row = {"case_id": r.get("case_id"), "family_id": r.get("family_id"),
                   "expected": expected, "decision": res["decision"],
                   "layer_fired": res.get("layer_fired",3),
                   "reasons": res.get("reasons",[]),
                   "is_timeout": res.get("is_timeout",False)}
            f.write(json.dumps(row) + "\n")
            new_rows.append(row)
    return done_rows + new_rows

def rows_to_metrics(rows):
    y_true = [r["expected"] for r in rows]
    y_pred = [r["decision"] for r in rows]
    fids   = [r["family_id"] for r in rows]
    lf     = [r.get("layer_fired",3) for r in rows]
    tl     = [r.get("is_timeout",False) for r in rows]
    return compute_all_registered_metrics(y_true, y_pred, family_ids=fids,
                                          layer_fired_list=lf, timeout_list=tl)

def main():
    tune, val = load_dev_data()
    views = build_views(tune, val)
    result = {"views": {}}

    for view_name, splits in views.items():
        print(f"\n=== {view_name} ===")
        result["views"][view_name] = {}
        for extractor in ("oracle", "linker"):
            for variant in ("variant_a", "variant_b"):
                tk = f"{extractor}_{variant}"
                for split_name, records in [("tune", splits["tune"]), ("val", splits["val"])]:
                    label = f"{extractor}_{view_name}_{split_name}_{variant}"
                    print(f"  {label} ({len(records)} records)...", end=" ", flush=True)
                    rows = run_track(records, extractor, variant, label)
                    m = rows_to_metrics(rows)
                    if tk not in result["views"][view_name]:
                        result["views"][view_name][tk] = {}
                    result["views"][view_name][tk][split_name] = m
                    if m.get("n", 0) == 0:
                        print("(empty split, skipped)")
                    else:
                        print(f"R_block={m['r_block_unsafe']:.4f} R_escape={m['r_escape']:.4f} FBR={m['fbr']:.4f} IR={m['ir']:.4f}")

    out = os.path.join(RESULTS_DIR, "v2_2_metrics_oracle_linker.json")
    with open(out, "w") as f:
        json.dump(result, f, indent=2, default=str)
    print(f"\nSaved to {out}")
    return result

if __name__ == "__main__":
    main()
