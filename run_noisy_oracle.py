"""
run_noisy_oracle.py
====================
Noisy-Oracle Experiment for GuardianAgent v2.2.

Renames the mechanical oracle track to "mechanical-oracle (upper bound)"
in every table, with a note that it is circular by construction.

Corrupt each field of the mechanical intent independently with rate p
in {0, 5, 10, 20, 40}% (using 5 seeds), then run the pipeline's Layer 3
comparator and report decision quality vs field-level accuracy:
  - R_block_unsafe
  - R_escape
  - R_worst
  - IR (benign CONFIRM+BLOCK / n_benign)
  - OER (benign expected-ALLOW → CONFIRM / n_expected-ALLOW)

Fields corrupted independently (each with prob p):
  - operation: replaced with a random wrong operation
  - table: replaced with a random wrong table or "wrong_table"
  - filter_columns: replaced with [] (unknown)
  - set_assignments: replaced with {} (unknown)
  - expected_cardinality: replaced with wrong value
  - where_val: replaced with "9999" (wrong value)

Output:
  results/dev_audit/noisy_oracle_results.json
  results/dev_audit/noisy_oracle_report.txt
"""
import os
import sys
import json
import random
import copy
from typing import List, Dict, Any, Tuple

from evaluate_dev import load_dev_data, resolve_db_path
from intent_spec_mechanical import derive_mechanical_intent
from intent_spec_v2 import extract_sql_components, compare_intent_and_sql, IntentSpecV2
from guardian_v2 import guardian_check_v2
from metrics import compute_all_registered_metrics

RESULTS_DIR = os.path.join("results", "dev_audit")
os.makedirs(RESULTS_DIR, exist_ok=True)

CORRUPT_RATES = [0.0, 0.05, 0.10, 0.20, 0.40]
N_SEEDS = 5
SEEDS = [42, 43, 44, 45, 46]

OPERATIONS = ["SELECT", "UPDATE", "DELETE", "INSERT", "DROP", "ALTER"]
CARDINALITIES = ["single", "multi", "unknown"]


def corrupt_field(value: Any, field: str, p: float, rng: random.Random) -> Any:
    """Corrupt a single field with probability p."""
    if rng.random() >= p:
        return value  # keep original

    if field == "operation":
        wrong_ops = [o for o in OPERATIONS if o != value]
        return rng.choice(wrong_ops) if wrong_ops else "unknown"

    elif field == "table":
        return "wrong_table_xyz"

    elif field == "filter_columns":
        return []  # unknown

    elif field == "set_assignments":
        return {}  # unknown

    elif field == "expected_cardinality":
        wrong_cards = [c for c in CARDINALITIES if c != value]
        return rng.choice(wrong_cards) if wrong_cards else "unknown"

    elif field == "where_val":
        return "9999"

    return value


def corrupt_intent(intent: IntentSpecV2, p: float, rng: random.Random) -> IntentSpecV2:
    """Return a corrupted copy of the intent with each field corrupted at rate p."""
    noisy = copy.copy(intent)

    noisy.operation = corrupt_field(intent.operation, "operation", p, rng)
    noisy.table = corrupt_field(intent.table, "table", p, rng)
    noisy.filter_columns = corrupt_field(intent.filter_columns or [], "filter_columns", p, rng)
    noisy.set_assignments = corrupt_field(intent.set_assignments or {}, "set_assignments", p, rng)
    noisy.expected_cardinality = corrupt_field(
        intent.expected_cardinality or "unknown", "expected_cardinality", p, rng
    )
    noisy.where_val = corrupt_field(intent.where_val, "where_val", p, rng)

    # Recompute unverifiable_fields
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
    """Wraps the mechanical oracle, injecting corruption at rate p."""
    def __init__(self, p: float, seed: int):
        self.p = p
        self.rng = random.Random(seed)

    def extract_intent(self, request: str, db_path: str = None, record: dict = None) -> IntentSpecV2:
        if not record:
            return IntentSpecV2(operation="unknown", unverifiable_fields=["no_record_available"])
        gold = record.get("gold_sql") or record.get("sql")
        if not gold:
            return IntentSpecV2(operation="unknown", unverifiable_fields=["no_gold_sql"])
        fam = record.get("family_id", "")
        clean_intent = derive_mechanical_intent(gold, request=request, family_id=fam)
        if self.p == 0.0:
            return clean_intent
        return corrupt_intent(clean_intent, self.p, self.rng)


def run_noisy_oracle_on_records(records: List[Dict], p: float, seed: int) -> Dict[str, Any]:
    """
    Run the pipeline with the noisy oracle at corruption rate p and given seed.
    Returns aggregated metrics.
    """
    extractor = NoisyOracleExtractor(p=p, seed=seed)
    y_true = []
    y_pred = []
    family_ids = []

    for r in records:
        db_path = resolve_db_path(r["database"])
        sql = r.get("sql", "")
        request = r.get("request", "")
        expected_va = r.get("expected_decision_variant_a", "ALLOW")

        # Inject noisy oracle via inline function
        from intent_spec_v2 import extract_sql_components, compare_intent_and_sql
        from guardian_layer1 import check_layer1_rules
        from guardian_layer2 import check_layer2_effect

        # Layer 1
        is_viol, rule_id, l1_dec, is_cat = check_layer1_rules(sql, request)
        if is_viol:
            decision = l1_dec
        else:
            # Layer 2
            effects = {"executes_ok": True, "n_matched": 0, "n_changed": 0,
                       "schema_changed": False, "is_timeout": False, "decision": None}
            if db_path and os.path.exists(db_path):
                effects = check_layer2_effect(db_path, sql)
                if effects.get("decision") == "CONFIRM":
                    decision = "CONFIRM"
                    y_true.append(expected_va)
                    y_pred.append(decision)
                    family_ids.append(r.get("family_id", "unknown"))
                    continue
            # Layer 3 with noisy intent
            noisy_intent = extractor.extract_intent(request, db_path=db_path, record=r)
            sql_comp = extract_sql_components(sql)
            comp_res = compare_intent_and_sql(
                intent=noisy_intent,
                sql_comp=sql_comp,
                measured_effects=effects,
                risk_mode="rules",
                variant="variant_a"
            )
            decision = comp_res["decision"]

        y_true.append(expected_va)
        y_pred.append(decision)
        family_ids.append(r.get("family_id", "unknown"))

    return compute_all_registered_metrics(y_true, y_pred, family_ids=family_ids)


def run_noisy_oracle():
    tune, val = load_dev_data()
    # Use dev-tune PAIRS-ONLY view: paired dataset cases
    pairs_only = [r for r in tune if not r.get("is_extended", False)]
    print(f"Noisy oracle experiment on PAIRS-ONLY dev-tune: {len(pairs_only)} cases")

    results = {}
    report_lines = [
        "=" * 70,
        "NOISY-ORACLE EXPERIMENT (mechanical-oracle upper bound)",
        "NOTE: Oracle is circular by construction (uses gold SQL). Results",
        "      show how field-level accuracy maps to pipeline safety metrics.",
        "=" * 70,
        ""
    ]

    header = f"{'p':>6}  {'seed':>4}  {'R_block':>8}  {'R_escape':>9}  {'R_worst':>8}  {'IR':>8}  {'OER':>8}"
    report_lines.append(header)
    report_lines.append("-" * len(header))

    for p in CORRUPT_RATES:
        p_key = str(int(p * 100))
        results[p_key] = []
        for seed in SEEDS:
            m = run_noisy_oracle_on_records(pairs_only, p=p, seed=seed)
            row = {
                "p": p,
                "seed": seed,
                "r_block_unsafe": m["r_block_unsafe"],
                "r_escape": m["r_escape"],
                "r_worst": m["r_worst"],
                "ir": m["ir"],
                "oer": m["oer"],
                "n": m["n"]
            }
            results[p_key].append(row)
            report_lines.append(
                f"{p*100:5.0f}%  {seed:4d}  "
                f"{m['r_block_unsafe']:8.4f}  {m['r_escape']:9.4f}  "
                f"{m['r_worst']:8.4f}  {m['ir']:8.4f}  {m['oer']:8.4f}"
            )
            print(
                f"p={p*100:.0f}% seed={seed}: R_block={m['r_block_unsafe']:.4f} "
                f"R_escape={m['r_escape']:.4f} R_worst={m['r_worst']:.4f} "
                f"IR={m['ir']:.4f} OER={m['oer']:.4f}"
            )

    report_lines.append("")
    report_lines.append("Mean across seeds:")
    mean_header = f"{'p':>6}  {'R_block':>8}  {'R_escape':>9}  {'R_worst':>8}  {'IR':>8}  {'OER':>8}"
    report_lines.append(mean_header)
    report_lines.append("-" * len(mean_header))

    for p in CORRUPT_RATES:
        p_key = str(int(p * 100))
        rows = results[p_key]
        def mean(key): return sum(r[key] for r in rows) / len(rows)
        report_lines.append(
            f"{p*100:5.0f}%  "
            f"{mean('r_block_unsafe'):8.4f}  {mean('r_escape'):9.4f}  "
            f"{mean('r_worst'):8.4f}  {mean('ir'):8.4f}  {mean('oer'):8.4f}"
        )

    # Save
    with open(os.path.join(RESULTS_DIR, "noisy_oracle_results.json"), "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    with open(os.path.join(RESULTS_DIR, "noisy_oracle_report.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(report_lines))

    print("\n" + "\n".join(report_lines[-15:]))
    print(f"\nSaved to results/dev_audit/noisy_oracle_results.json and noisy_oracle_report.txt")


if __name__ == "__main__":
    run_noisy_oracle()
