"""
generate_dev_report.py
======================
Generates the comprehensive evaluation report across dev-tune and dev-val.
Reports across 3 views:
  1. Pairs-only HEADLINE (dev_paired 448 cases)
  2. Full paired (all dev_paired + dev_extended records)
  3. Write-only scope (excluding MUT_BENIGN_READ_SELECT)
Runs cumulative ablations and all baselines.
"""
import os
import json
import numpy as np
from evaluate_dev import load_dev_data, run_evaluation, compute_metrics, resolve_db_path
from guardian_v2 import guardian_check_v2

def run_baseline_constant(dataset, constant_decision, variant="variant_a"):
    if not dataset:
        return {'accuracy': 0.0, 'balanced_accuracy': 0.0, 'macro_f1': 0.0, 'n': 0}
    y_true = [r.get(f"expected_decision_{variant}", r.get('expected_decision_variant_a')) for r in dataset]
    y_pred = [constant_decision] * len(dataset)
    return compute_metrics(y_true, y_pred)

def run_view_evaluation(dataset, view_name, layer=3, risk_mode="rules", extractor="oracle", variant="variant_a"):
    if view_name == "pairs_only_headline":
        filtered = [r for r in dataset if not r.get('is_extended')]
    elif view_name == "full_paired":
        filtered = list(dataset)
    elif view_name == "write_only":
        filtered = [r for r in dataset if r.get('family_id') != 'MUT_BENIGN_READ_SELECT']
    else:
        filtered = list(dataset)
        
    if not filtered:
        return {'accuracy': 0.0, 'balanced_accuracy': 0.0, 'macro_f1': 0.0, 'confusion_matrix': [], 'n': 0}, {}
    return run_evaluation(filtered, layer=layer, risk_mode=risk_mode, extractor=extractor, variant=variant)

def print_metrics_table(results_dict):
    print(f"{'Configuration':<35} | {'Accuracy':<10} | {'Balanced Acc':<12} | {'Macro-F1':<10} | {'N':<6}")
    print("-" * 80)
    for name, m in results_dict.items():
        print(f"{name:<35} | {m['accuracy']:<10.4f} | {m['balanced_accuracy']:<12.4f} | {m['macro_f1']:<10.4f} | {m['n']:<6}")

if __name__ == "__main__":
    tune, val = load_dev_data()
    print("================================================================================")
    print("                    GUARDIANAGENT v2 COMPREHENSIVE DEV REPORT                    ")
    print("================================================================================")
    print(f"Total dev-tune cases: {len(tune)} | Total dev-val cases: {len(val)}\n")

    views = ["pairs_only_headline", "full_paired", "write_only"]
    
    for v in views:
        print(f"\n==================== VIEW: {v.upper()} ====================")
        
        # 1. Headline Candidate Pipeline (Layer 3, Rules, Oracle, Variant A)
        m_tune_va, _ = run_view_evaluation(tune, v, layer=3, risk_mode="rules", extractor="oracle", variant="variant_a")
        m_val_va, _ = run_view_evaluation(val, v, layer=3, risk_mode="rules", extractor="oracle", variant="variant_a")
        
        # 2. Variant B
        m_tune_vb, _ = run_view_evaluation(tune, v, layer=3, risk_mode="rules", extractor="oracle", variant="variant_b")
        m_val_vb, _ = run_view_evaluation(val, v, layer=3, risk_mode="rules", extractor="oracle", variant="variant_b")
        
        # 3. Ablation: Layer 1 alone
        m_tune_l1, _ = run_view_evaluation(tune, v, layer=1, risk_mode="rules", extractor="oracle", variant="variant_a")
        m_val_l1, _ = run_view_evaluation(val, v, layer=1, risk_mode="rules", extractor="oracle", variant="variant_a")

        # 4. Ablation: Layer 1 + 2 (No Intent Spec)
        m_tune_l2, _ = run_view_evaluation(tune, v, layer=2, risk_mode="rules", extractor="oracle", variant="variant_a")
        m_val_l2, _ = run_view_evaluation(val, v, layer=2, risk_mode="rules", extractor="oracle", variant="variant_a")

        # 5. Ablation: Risk Mode = Weighted (Legacy)
        m_tune_wt, _ = run_view_evaluation(tune, v, layer=3, risk_mode="weighted", extractor="oracle", variant="variant_a")
        m_val_wt, _ = run_view_evaluation(val, v, layer=3, risk_mode="weighted", extractor="oracle", variant="variant_a")

        # 6. Intent Extractor: Deterministic Linker
        m_tune_link, _ = run_view_evaluation(tune, v, layer=3, risk_mode="rules", extractor="linker", variant="variant_a")
        m_val_link, _ = run_view_evaluation(val, v, layer=3, risk_mode="rules", extractor="linker", variant="variant_a")

        # 7. Baselines on dev-val (or dev-tune if val is empty for that view)
        target_baseline_set = val if v != "pairs_only_headline" else tune
        base_allow = run_baseline_constant(target_baseline_set, "ALLOW")
        base_confirm = run_baseline_constant(target_baseline_set, "CONFIRM")
        base_block = run_baseline_constant(target_baseline_set, "BLOCK")

        print("\n--- DEV-TUNE METRICS ---")
        print_metrics_table({
            "Pipeline v2 (Full, Rules, Var A)": m_tune_va,
            "Pipeline v2 (Variant B)": m_tune_vb,
            "Ablation: Layer 1 Alone": m_tune_l1,
            "Ablation: Layer 1 + Layer 2": m_tune_l2,
            "Ablation: Weighted Risk Mode": m_tune_wt,
            "Extractor: Deterministic Linker": m_tune_link,
        })

        if m_val_va['n'] > 0:
            print("\n--- DEV-VAL METRICS ---")
            print_metrics_table({
                "Pipeline v2 (Full, Rules, Var A)": m_val_va,
                "Pipeline v2 (Variant B)": m_val_vb,
                "Ablation: Layer 1 Alone": m_val_l1,
                "Ablation: Layer 1 + Layer 2": m_val_l2,
                "Ablation: Weighted Risk Mode": m_val_wt,
                "Extractor: Deterministic Linker": m_val_link,
                "Baseline: Always-ALLOW": base_allow,
                "Baseline: Always-CONFIRM": base_confirm,
                "Baseline: Always-BLOCK": base_block,
            })
        else:
            print("\n--- DEV-VAL METRICS ---")
            print("Note: dev_paired partition resides in dev-tune databases (448 cases). Dev-val comprises 8 independent extended DBs.")
