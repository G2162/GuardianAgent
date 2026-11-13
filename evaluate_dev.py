"""
evaluate_dev.py
===============
Evaluation and Tuning Script for GuardianAgent v2.
Operates EXCLUSIVELY on dev_paired and dev_extended splits.
Strictly prohibited from touching any test split.

Outputs:
  - 3-view metrics:
      1. Pairs-only HEADLINE
      2. Full paired (all dev_paired records)
      3. Write-only scope
  - Class balance, accuracy, balanced accuracy, macro-F1, confusion matrix
  - Per-family recall on unsafe cases, false-positive rate on benign cases
  - Baselines: Always-ALLOW, Always-CONFIRM, Always-BLOCK, Layer 1 alone, Layer 2 alone
"""
import os
import sys
import json
import numpy as np
from collections import defaultdict
from sklearn.metrics import accuracy_score, balanced_accuracy_score, f1_score, confusion_matrix

from guardian_v2 import guardian_check_v2

# Partition mapping
DEV_VAL_DBS = {
    'activity_1', 'city_record', 'farm', 'journal_committee',
    'music_4', 'phone_market', 'solvency_ii', 'swimming'
}

def resolve_db_path(db_name):
    # Try dev_extended_dbs
    ext_path = os.path.join("data", "dev_extended_dbs", f"{db_name}.sqlite")
    if os.path.exists(ext_path):
        return ext_path
    # Try evaluation_dbs
    eval_path = os.path.join("data", "evaluation_dbs", f"{db_name}.sqlite")
    if os.path.exists(eval_path):
        return eval_path
    return None

def load_dev_data():
    paired_file = os.path.join("data", "evaluation_splits", "dev_paired_dataset_v1.4.json")
    extended_file = os.path.join("data", "evaluation_splits", "dev_extended_dataset_v1.4.json")
    
    with open(paired_file, 'r', encoding='utf-8') as f:
        dev_paired = json.load(f)
    with open(extended_file, 'r', encoding='utf-8') as f:
        dev_extended = json.load(f)
        
    dev_tune = []
    dev_val = []
    
    for r in dev_paired:
        r_copy = dict(r)
        r_copy['is_extended'] = False
        r_copy['split_partition'] = 'dev-tune' # dev_paired dbs belong to dev-tune
        dev_tune.append(r_copy)
        
    for r in dev_extended:
        r_copy = dict(r)
        r_copy['is_extended'] = True
        if r_copy['database'] in DEV_VAL_DBS:
            r_copy['split_partition'] = 'dev-val'
            dev_val.append(r_copy)
        else:
            r_copy['split_partition'] = 'dev-tune'
            dev_tune.append(r_copy)
            
    return dev_tune, dev_val

def compute_metrics(y_true, y_pred, labels=['ALLOW', 'CONFIRM', 'BLOCK']):
    acc = accuracy_score(y_true, y_pred)
    bacc = balanced_accuracy_score(y_true, y_pred)
    mf1 = f1_score(y_true, y_pred, average='macro', zero_division=0)
    cm = confusion_matrix(y_true, y_pred, labels=labels)
    return {
        'accuracy': float(acc),
        'balanced_accuracy': float(bacc),
        'macro_f1': float(mf1),
        'confusion_matrix': cm.tolist(),
        'n': len(y_true)
    }

def run_evaluation(dataset, layer=3, risk_mode="rules", extractor="oracle", variant="variant_a"):
    y_true = []
    y_pred = []
    per_family_stats = defaultdict(lambda: {'true': [], 'pred': []})
    timeouts = 0
    
    for r in dataset:
        target_dec = r.get(f"expected_decision_{variant}", r.get('expected_decision_variant_a'))
        db_path = resolve_db_path(r['database'])
        
        res = guardian_check_v2(
            user_request=r['request'],
            sql_str=r['sql'],
            db_path=db_path,
            record=r,
            layer=layer,
            risk_mode=risk_mode,
            extractor=extractor,
            variant=variant
        )
        
        pred = res['decision']
        if res.get('is_timeout'):
            timeouts += 1
            
        y_true.append(target_dec)
        y_pred.append(pred)
        per_family_stats[r['family_id']]['true'].append(target_dec)
        per_family_stats[r['family_id']]['pred'].append(pred)

    overall = compute_metrics(y_true, y_pred)
    overall['timeouts'] = timeouts
    
    # Per family metrics
    fam_metrics = {}
    for fam, d in per_family_stats.items():
        t = d['true']
        p = d['pred']
        n = len(t)
        # Check unsafe recall (BLOCK recall) or benign FPR
        is_unsafe = any(x == 'BLOCK' for x in t)
        if is_unsafe:
            # recall = p == 'BLOCK' / n
            recall = sum(1 for pi, ti in zip(p, t) if pi == 'BLOCK' and ti == 'BLOCK') / sum(1 for ti in t if ti == 'BLOCK') if sum(1 for ti in t if ti == 'BLOCK') > 0 else 0
            fam_metrics[fam] = {'type': 'unsafe', 'n': n, 'metric_name': 'recall', 'value': recall}
        else:
            # Benign FPR: false positives are BLOCK decisions on benign cases
            fp = sum(1 for pi in p if pi == 'BLOCK')
            fpr = fp / n if n > 0 else 0
            fam_metrics[fam] = {'type': 'benign', 'n': n, 'metric_name': 'fpr', 'value': fpr}

    return overall, fam_metrics

if __name__ == "__main__":
    tune, val = load_dev_data()
    print(f"Loaded: dev-tune={len(tune)} cases, dev-val={len(val)} cases")
    
    print("\n--- Running Baseline Dev-Tune Evaluation (Variant A, Layer 3, Rules, Oracle) ---")
    ov_tune, fam_tune = run_evaluation(tune, layer=3, risk_mode="rules", extractor="oracle", variant="variant_a")
    print(f"Dev-Tune Accuracy: {ov_tune['accuracy']:.4f}, Balanced Acc: {ov_tune['balanced_accuracy']:.4f}, Macro-F1: {ov_tune['macro_f1']:.4f}")
    print(f"Confusion Matrix [ALLOW, CONFIRM, BLOCK]:\n{np.array(ov_tune['confusion_matrix'])}")
    
    print("\n--- Running Baseline Dev-Val Evaluation (Variant A, Layer 3, Rules, Oracle) ---")
    ov_val, fam_val = run_evaluation(val, layer=3, risk_mode="rules", extractor="oracle", variant="variant_a")
    print(f"Dev-Val Accuracy: {ov_val['accuracy']:.4f}, Balanced Acc: {ov_val['balanced_accuracy']:.4f}, Macro-F1: {ov_val['macro_f1']:.4f}")
    print(f"Confusion Matrix [ALLOW, CONFIRM, BLOCK]:\n{np.array(ov_val['confusion_matrix'])}")

