"""
run_baselines.py
================
Compute all baselines on PAIRS-ONLY dev-tune, Variant A.
Fast (no LLM calls).
"""
import json, os
from evaluate_dev import load_dev_data, resolve_db_path
from guardian_layer1 import check_layer1_rules
from guardian_layer2 import check_layer2_effect
from metrics import compute_all_registered_metrics

RESULTS_DIR = os.path.join("results", "dev_audit")

def main():
    tune, val = load_dev_data()
    po_tune = [r for r in tune if not r.get("is_extended", False)]
    print(f"PAIRS-ONLY dev-tune: {len(po_tune)} cases")

    baselines = {}

    # Always-X
    for dec in ["ALLOW", "CONFIRM", "BLOCK"]:
        y_true = [r.get("expected_decision_variant_a", "ALLOW") for r in po_tune]
        y_pred = [dec] * len(po_tune)
        m = compute_all_registered_metrics(y_true, y_pred)
        baselines[f"Always_{dec}"] = m
        print(f"Always-{dec}: R_block={m['r_block_unsafe']:.4f} R_escape={m['r_escape']:.4f} R_worst={m['r_worst']:.4f} FBR={m['fbr']:.4f} IR={m['ir']:.4f}")

    # STRUCTURE + CONFIRM-REST
    y_true, y_pred = [], []
    for r in po_tune:
        sql = r.get("sql", "")
        request = r.get("request", "")
        expected = r.get("expected_decision_variant_a", "ALLOW")
        is_viol, _, l1_dec, _ = check_layer1_rules(sql, request)
        decision = l1_dec if (is_viol and l1_dec == "BLOCK") else "CONFIRM"
        y_true.append(expected)
        y_pred.append(decision)
    m = compute_all_registered_metrics(y_true, y_pred)
    baselines["STRUCTURE_CONFIRM_REST"] = m
    print(f"STRUCTURE+CONFIRM-REST: R_block={m['r_block_unsafe']:.4f} R_escape={m['r_escape']:.4f} R_worst={m['r_worst']:.4f} FBR={m['fbr']:.4f} IR={m['ir']:.4f}")

    # Row-count dry-run
    y_true, y_pred = [], []
    for r in po_tune:
        sql = r.get("sql", "")
        db_path = resolve_db_path(r["database"])
        expected = r.get("expected_decision_variant_a", "ALLOW")
        n = r.get("measured_affected_rows", 0) or 0
        if db_path and os.path.exists(db_path):
            try:
                eff = check_layer2_effect(db_path, sql)
                n = eff.get("n_changed", 0)
            except Exception:
                pass
        decision = "BLOCK" if n > 1 else "ALLOW"
        y_true.append(expected)
        y_pred.append(decision)
    m = compute_all_registered_metrics(y_true, y_pred)
    baselines["Row_count_dry_run"] = m
    print(f"Row-count dry-run: R_block={m['r_block_unsafe']:.4f} R_escape={m['r_escape']:.4f} R_worst={m['r_worst']:.4f} FBR={m['fbr']:.4f} IR={m['ir']:.4f}")

    out = os.path.join(RESULTS_DIR, "baselines_v22.json")
    with open(out, "w") as f:
        json.dump(baselines, f, indent=2, default=str)
    print(f"Saved to {out}")
    return baselines

if __name__ == "__main__":
    main()
