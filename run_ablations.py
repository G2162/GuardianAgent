"""
run_ablations.py
================
Runs cumulative layer ablations on PAIRS-ONLY dev-tune (Variant A) for:
  1. Layer 1 alone
  2. Layer 1 + 2
  3. Full (Layer 1 + 2 + 3)
Computes metrics with metrics.py and saves results.
"""
import os
import json
from evaluate_dev import load_dev_data, resolve_db_path
from guardian_v2 import guardian_check_v2
from metrics import compute_all_registered_metrics

RESULTS_DIR = os.path.join("results", "dev_audit")
os.makedirs(RESULTS_DIR, exist_ok=True)

def main():
    tune, val = load_dev_data()
    po_tune = [r for r in tune if not r.get("is_extended", False)]
    print(f"Loaded {len(po_tune)} PAIRS-ONLY dev-tune records.")

    ablations = {}

    for extractor in ["linker", "oracle"]:
        print(f"\n--- Extractor: {extractor} ---")
        ablations[extractor] = {}
        for layer in [1, 2, 3]:
            y_true, y_pred, family_ids, layer_fired = [], [], [], []
            for r in po_tune:
                db_path = resolve_db_path(r["database"])
                expected = r.get("expected_decision_variant_a", "ALLOW")
                res = guardian_check_v2(
                    r["request"],
                    r.get("sql", ""),
                    db_path=db_path,
                    record=r,
                    extractor=extractor,
                    variant="variant_a",
                    layer=layer
                )
                y_true.append(expected)
                y_pred.append(res["decision"])
                family_ids.append(r.get("family_id", "unknown"))
                layer_fired.append(res.get("layer_fired", layer))

            m = compute_all_registered_metrics(
                y_true, y_pred, family_ids=family_ids, layer_fired_list=layer_fired
            )
            key = f"layer{layer}" if layer < 3 else "full"
            ablations[extractor][key] = m
            print(f"  Layer {layer} ({key}): R_block={m['r_block_unsafe']:.4f}, R_escape={m['r_escape']:.4f}, R_worst={m['r_worst']:.4f}, FBR={m['fbr']:.4f}, IR={m['ir']:.4f}")

    out_file = os.path.join(RESULTS_DIR, "ablations_v22.json")
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(ablations, f, indent=2)
    print(f"\nSaved ablations to {out_file}")

if __name__ == "__main__":
    main()
