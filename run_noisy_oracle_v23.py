"""
run_noisy_oracle_v23.py
=======================
Repairs the noisy-oracle experiment for GuardianAgent v2.3:
1. Aligns p=0 to use the exact guardian_check_v2 code path as mechanical-oracle.
2. Evaluates corruption rates p in {0, 5, 10, 20, 40}% across 5 seeds.
3. Evaluates two corruption modes:
   - "wrong_value": corrupted fields become random wrong values (forces Layer 3 mismatch -> BLOCK)
   - "corrupt_to_unknown": corrupted fields become unknown / empty (exercises fail-closed -> CONFIRM)
4. Computes all registered metrics: R_block, R_escape, R_worst, FBR, IR (CONFIRM only), allow_rate.
5. Saves results to results/dev_audit/noisy_oracle_v23_results.json.
"""
import os, sys, json, random, copy
from typing import List, Dict, Any
from evaluate_dev import load_dev_data, resolve_db_path
from intent_spec_mechanical import derive_mechanical_intent
from intent_spec_v2 import IntentSpecV2
from guardian_v2 import guardian_check_v2
from metrics import compute_all_registered_metrics

RESULTS_DIR = os.path.join("results", "dev_audit")
os.makedirs(RESULTS_DIR, exist_ok=True)

CORRUPT_RATES = [0.0, 0.05, 0.10, 0.20, 0.40]
SEEDS = [42, 43, 44, 45, 46]
OPERATIONS = ["SELECT", "UPDATE", "DELETE", "INSERT", "DROP", "ALTER"]
CARDINALITIES = ["single", "multi", "unknown"]

def corrupt_field_wrong(value: Any, field: str, p: float, rng: random.Random) -> Any:
    if rng.random() >= p:
        return value
    if field == "operation":
        wrong = [o for o in OPERATIONS if o != value]
        return rng.choice(wrong) if wrong else "unknown"
    elif field == "table":
        return "wrong_table_corrupted"
    elif field == "filter_columns":
        return ["wrong_col_xyz"]
    elif field == "set_assignments":
        return {"wrong_col": "corrupted_val"}
    elif field == "expected_cardinality":
        wrong = [c for c in CARDINALITIES if c != value]
        return rng.choice(wrong) if wrong else "unknown"
    elif field == "where_val":
        return "999999"
    return value

def corrupt_field_unknown(value: Any, field: str, p: float, rng: random.Random) -> Any:
    if rng.random() >= p:
        return value
    if field == "operation":
        return "unknown"
    elif field == "table":
        return ""
    elif field == "filter_columns":
        return []
    elif field == "set_assignments":
        return {}
    elif field == "expected_cardinality":
        return "unknown"
    elif field == "where_val":
        return None
    return value

def build_corrupted_intent(intent: IntentSpecV2, p: float, rng: random.Random, mode: str) -> IntentSpecV2:
    if p == 0.0:
        return copy.copy(intent)
    noisy = copy.copy(intent)
    fn = corrupt_field_unknown if mode == "corrupt_to_unknown" else corrupt_field_wrong
    
    noisy.operation = fn(intent.operation, "operation", p, rng)
    noisy.table = fn(intent.table, "table", p, rng)
    noisy.filter_columns = fn(intent.filter_columns or [], "filter_columns", p, rng)
    noisy.set_assignments = fn(intent.set_assignments or {}, "set_assignments", p, rng)
    noisy.expected_cardinality = fn(intent.expected_cardinality or "unknown", "expected_cardinality", p, rng)
    noisy.where_val = fn(intent.where_val, "where_val", p, rng)

    unverifiable = []
    if noisy.operation == "unknown":
        unverifiable.append("operation")
    if not noisy.table:
        unverifiable.append("target_table")
    if not noisy.filter_columns and noisy.operation in ("UPDATE", "DELETE"):
        unverifiable.append("filter_columns")
    if noisy.expected_cardinality == "unknown":
        unverifiable.append("cardinality")
    noisy.unverifiable_fields = unverifiable
    return noisy

class NoisyOracleExtractor:
    def __init__(self, p: float, seed: int, mode: str = "wrong_value"):
        self.p = p
        self.rng = random.Random(seed)
        self.mode = mode
        self.name = f"noisy_oracle_{mode}_p{int(p*100)}"

    def extract_intent(self, request: str, db_path: str = None, record: dict = None) -> IntentSpecV2:
        if not record:
            return IntentSpecV2(operation="unknown", unverifiable_fields=["no_record"])
        gold = record.get("gold_sql") or record.get("sql")
        fam = record.get("family_id", "")
        clean = derive_mechanical_intent(gold, request=request, family_id=fam)
        return build_corrupted_intent(clean, self.p, self.rng, self.mode)

def run_evaluation():
    tune, val = load_dev_data()
    dev_records = tune + val
    print(f"Loaded {len(dev_records)} dev records (tune={len(tune)}, val={len(val)})")

    all_results = {}

    for mode in ["wrong_value", "corrupt_to_unknown"]:
        print(f"\n=======================================================")
        print(f"Running Noisy-Oracle Mode: {mode}")
        print(f"=======================================================")
        mode_results = []
        
        for p in CORRUPT_RATES:
            p_metrics = []
            for seed in SEEDS:
                ext = NoisyOracleExtractor(p=p, seed=seed, mode=mode)
                y_true = []
                y_pred = []
                family_ids = []

                for r in dev_records:
                    db = resolve_db_path(r["database"])
                    res = guardian_check_v2(
                        user_request=r.get("request", ""),
                        sql_str=r.get("sql", ""),
                        db_path=db,
                        record=r,
                        extractor=ext,
                        variant="variant_a"
                    )
                    y_true.append(r.get("expected_decision_variant_a", "ALLOW"))
                    y_pred.append(res["decision"])
                    family_ids.append(r.get("family_id", "unknown"))

                m = compute_all_registered_metrics(y_true, y_pred, family_ids)
                p_metrics.append(m)

            # Average over seeds
            avg_m = {
                "p": p,
                "n_seeds": len(SEEDS),
                "r_block_unsafe": round(sum(x["r_block_unsafe"] for x in p_metrics) / len(p_metrics), 4),
                "r_escape": round(sum(x["r_escape"] for x in p_metrics) / len(p_metrics), 4),
                "r_worst": round(sum(x["r_worst"] for x in p_metrics) / len(p_metrics), 4),
                "fbr": round(sum(x["fbr"] for x in p_metrics) / len(p_metrics), 4),
                "ir": round(sum(x["ir"] for x in p_metrics) / len(p_metrics), 4),
                "allow_rate": round(sum(x["allow_rate"] for x in p_metrics) / len(p_metrics), 4),
                "oer": round(sum(x["oer"] for x in p_metrics) / len(p_metrics), 4),
            }
            mode_results.append(avg_m)
            print(f"p={p:.2f} | R_block={avg_m['r_block_unsafe']:.4f} | R_escape={avg_m['r_escape']:.4f} | FBR={avg_m['fbr']:.4f} | IR={avg_m['ir']:.4f} | allow_rate={avg_m['allow_rate']:.4f}")

        all_results[mode] = mode_results

    out_p = os.path.join(RESULTS_DIR, "noisy_oracle_v23_results.json")
    with open(out_p, "w", encoding="utf-8") as f:
        json.dump(all_results, f, indent=2)
    print(f"\nSaved noisy-oracle results to {out_p}")

if __name__ == "__main__":
    run_evaluation()
