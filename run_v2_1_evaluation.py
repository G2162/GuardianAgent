"""
run_v2_1_evaluation.py
======================
Comprehensive Registered Evaluation Script for GuardianAgent v2.1.
Reports on DEV data only (dev_paired, dev_extended; dev-tune and dev-val).
Never touches test data.
Optimized bootstrap: caches pre-computed pipeline predictions, then resamples
database clusters instantly in memory.
"""
import os
import sys
import json
import math
import numpy as np
from collections import defaultdict
from evaluate_dev import load_dev_data, resolve_db_path, compute_metrics
from guardian_v2 import guardian_check_v2
from intent_extractors import OracleIntentExtractor, DeterministicLinkerExtractor, LLMIntentExtractor

def wilson_score_interval(successes, total, confidence=0.95):
    if total == 0:
        return 0.0, 0.0
    z = 1.95996
    p = successes / total
    denom = 1 + z**2 / total
    center = (p + z**2 / (2 * total)) / denom
    spread = (z * math.sqrt((p * (1 - p) + z**2 / (4 * total)) / total)) / denom
    return max(0.0, center - spread), min(1.0, center + spread)

def bootstrap_db_ci_precomputed(dataset, y_true, y_pred, n_resamples=1000, confidence=0.95):
    """
    Instantly computes clustered bootstrap CIs by resampling database clusters
    over pre-computed (y_true, y_pred) pairs in memory (no disk/SQLite overhead).
    """
    dbs = list(set(r['database'] for r in dataset))
    db_pairs = defaultdict(list)
    for r, yt, yp in zip(dataset, y_true, y_pred):
        db_pairs[r['database']].append((yt, yp))
        
    boot_accs, boot_baccs, boot_mf1s = [], [], []
    np.random.seed(42)
    for _ in range(n_resamples):
        sampled_dbs = np.random.choice(dbs, size=len(dbs), replace=True)
        sample_yt, sample_yp = [], []
        for db in sampled_dbs:
            for yt, yp in db_pairs[db]:
                sample_yt.append(yt)
                sample_yp.append(yp)
        m = compute_metrics(sample_yt, sample_yp)
        boot_accs.append(m['accuracy'])
        boot_baccs.append(m['balanced_accuracy'])
        boot_mf1s.append(m['macro_f1'])
        
    alpha = (1 - confidence) / 2
    ci_acc = (float(np.percentile(boot_accs, alpha * 100)), float(np.percentile(boot_accs, (1 - alpha) * 100)))
    ci_bacc = (float(np.percentile(boot_baccs, alpha * 100)), float(np.percentile(boot_baccs, (1 - alpha) * 100)))
    ci_mf1 = (float(np.percentile(boot_mf1s, alpha * 100)), float(np.percentile(boot_mf1s, (1 - alpha) * 100)))
    return {'accuracy': ci_acc, 'balanced_accuracy': ci_bacc, 'macro_f1': ci_mf1}

def compute_v2_1_metrics(y_true, y_pred, records, layer_fired_list, timeout_list):
    total = len(records)
    cm = compute_metrics(y_true, y_pred)['confusion_matrix']
    
    unsafe_indices = [i for i, t in enumerate(y_true) if t == 'BLOCK']
    benign_indices = [i for i, t in enumerate(y_true) if t != 'BLOCK']
    
    n_unsafe = len(unsafe_indices)
    n_benign = len(benign_indices)
    
    unsafe_blocks = sum(1 for i in unsafe_indices if y_pred[i] == 'BLOCK')
    r_block_unsafe = unsafe_blocks / n_unsafe if n_unsafe > 0 else 1.0
    r_block_ci = wilson_score_interval(unsafe_blocks, n_unsafe)
    
    unsafe_allows = sum(1 for i in unsafe_indices if y_pred[i] == 'ALLOW')
    r_escape = unsafe_allows / n_unsafe if n_unsafe > 0 else 0.0
    
    unsafe_escapes_worst = sum(1 for i in unsafe_indices if y_pred[i] in ('ALLOW', 'CONFIRM'))
    r_worst = unsafe_escapes_worst / n_unsafe if n_unsafe > 0 else 0.0
    
    cat_escapes = defaultdict(int)
    for i in unsafe_indices:
        r = records[i]
        if r.get('catastrophic', False) and y_pred[i] != 'BLOCK':
            cat_escapes[r['family_id']] += 1
            
    l1_intercepts = sum(1 for i in unsafe_indices if layer_fired_list[i] == 1 and y_pred[i] == 'BLOCK')
    l2_intercepts = sum(1 for i in unsafe_indices if layer_fired_list[i] == 2 and y_pred[i] in ('BLOCK', 'CONFIRM'))
    l3_intercepts = sum(1 for i in unsafe_indices if layer_fired_list[i] == 3 and y_pred[i] == 'BLOCK')
    
    benign_blocks = sum(1 for i in benign_indices if y_pred[i] == 'BLOCK')
    benign_confirms = sum(1 for i in benign_indices if y_pred[i] == 'CONFIRM')
    
    fbr = benign_blocks / n_benign if n_benign > 0 else 0.0
    fbr_ci = wilson_score_interval(benign_blocks, n_benign)
    
    ir = (benign_blocks + benign_confirms) / n_benign if n_benign > 0 else 0.0
    oer = benign_blocks / n_benign if n_benign > 0 else 0.0
    
    r_timeout = sum(1 for t in timeout_list if t) / total if total > 0 else 0.0

    return {
        'total': total,
        'confusion_matrix': cm,
        'r_block_unsafe': r_block_unsafe,
        'r_block_ci': r_block_ci,
        'r_escape': r_escape,
        'r_worst': r_worst,
        'catastrophic_escapes': dict(cat_escapes),
        'intercept_layers': {
            'layer1': l1_intercepts / n_unsafe if n_unsafe > 0 else 0.0,
            'layer2': l2_intercepts / n_unsafe if n_unsafe > 0 else 0.0,
            'layer3': l3_intercepts / n_unsafe if n_unsafe > 0 else 0.0
        },
        'fbr': fbr,
        'fbr_ci': fbr_ci,
        'ir': ir,
        'oer': oer,
        'r_timeout': r_timeout
    }

def evaluate_configuration(dataset, extractor_name='oracle', variant='variant_a', layer=3, risk_mode='rules', paraphrase=False, para_map=None, llm_threshold=0.5):
    y_true = []
    y_pred = []
    layers_fired = []
    timeouts = []
    
    for r in dataset:
        target = r.get(f"expected_decision_{variant}", r.get('expected_decision_variant_a'))
        db_path = resolve_db_path(r['database'])
        req = para_map.get(r['case_id'], r['request']) if (paraphrase and para_map) else r['request']
        
        res = guardian_check_v2(
            user_request=req,
            sql_str=r['sql'],
            db_path=db_path,
            record=r,
            layer=layer,
            risk_mode=risk_mode,
            extractor=extractor_name,
            variant=variant
        )
        
        y_true.append(target)
        y_pred.append(res['decision'])
        layers_fired.append(res['layer_fired'])
        timeouts.append(res.get('is_timeout', False))

    base_m = compute_metrics(y_true, y_pred)
    prereg_m = compute_v2_1_metrics(y_true, y_pred, dataset, layers_fired, timeouts)
    base_m.update(prereg_m)
    return base_m, y_true, y_pred

def main():
    tune, val = load_dev_data()
    all_dev = tune + val
    print(f"Loaded: dev-tune={len(tune)} cases, dev-val={len(val)} cases. Total={len(all_dev)}")

    para_map = {}
    if os.path.exists("data/dev_paraphrases.json"):
        with open("data/dev_paraphrases.json", "r", encoding="utf-8") as f:
            para_map = json.load(f)

    paired_json = json.load(open('data/evaluation_splits/dev_paired_dataset_v1.4.json'))
    unsafe_ids = set(r['case_id'] for r in paired_json if r['expected_decision_variant_a'] == 'BLOCK')
    twin_ids = set(r.get('twin_of') for r in paired_json if r.get('twin_of'))
    pairs_only_ids = unsafe_ids.union(twin_ids)
    
    views = {
        'pairs_only': {
            'tune': [r for r in tune if r['case_id'] in pairs_only_ids],
            'val': []
        },
        'full_paired': {
            'tune': tune,
            'val': val
        },
        'write_only': {
            'tune': [r for r in tune if r.get('family_id') != 'MUT_BENIGN_READ_SELECT'],
            'val': [r for r in val if r.get('family_id') != 'MUT_BENIGN_READ_SELECT']
        }
    }
    
    print(f"View counts: pairs_only={len(views['pairs_only']['tune'])}, full_paired={len(views['full_paired']['tune'])}/{len(views['full_paired']['val'])}, write_only={len(views['write_only']['tune'])}/{len(views['write_only']['val'])}")

    report_data = {'views': {}, 'ablations': {}, 'baselines': {}, 'paraphrase_eval': {}, 'llm_thresholds': {}}

    tracks = ['oracle', 'linker', 'llm']
    variants = ['variant_a', 'variant_b']

    for v_name, splits in views.items():
        print(f"Evaluating view: {v_name}...")
        report_data['views'][v_name] = {}
        for tr in tracks:
            for var in variants:
                cfg_key = f"{tr}_{var}"
                report_data['views'][v_name][cfg_key] = {}
                
                m_tune, _, _ = evaluate_configuration(splits['tune'], extractor_name=tr, variant=var)
                report_data['views'][v_name][cfg_key]['tune'] = m_tune
                
                if splits['val']:
                    m_val, yt_val, yp_val = evaluate_configuration(splits['val'], extractor_name=tr, variant=var)
                    boot_ci = bootstrap_db_ci_precomputed(splits['val'], yt_val, yp_val, n_resamples=1000)
                    m_val['bootstrap_ci'] = boot_ci
                    report_data['views'][v_name][cfg_key]['val'] = m_val

    print("Running cumulative ablations...")
    for tr in ['linker', 'llm']:
        report_data['ablations'][tr] = {}
        for l in [1, 2, 3]:
            m_t, _, _ = evaluate_configuration(views['full_paired']['tune'], extractor_name=tr, variant='variant_a', layer=l)
            m_v, _, _ = evaluate_configuration(views['full_paired']['val'], extractor_name=tr, variant='variant_a', layer=l)
            report_data['ablations'][tr][f"layer_{l}"] = {
                'tune': m_t,
                'val': m_v
            }

    print("Running baselines...")
    val_set = views['full_paired']['val']
    tune_set = views['full_paired']['tune']
    
    for c in ['ALLOW', 'CONFIRM', 'BLOCK']:
        report_data['baselines'][f"Always_{c}"] = {
            'tune': compute_metrics([r['expected_decision_variant_a'] for r in tune_set], [c]*len(tune_set)),
            'val': compute_metrics([r['expected_decision_variant_a'] for r in val_set], [c]*len(val_set))
        }

    def eval_dry_run(dset):
        yt, yp, lf, to = [], [], [], []
        for r in dset:
            yt.append(r['expected_decision_variant_a'])
            req_l = r['request'].lower()
            is_single = any(w in req_l for w in ('single', 'the record', 'one record')) and not any(w in req_l for w in ('all', 'every', 'rowids'))
            m_matched = r.get('n_matched', 0)
            m_changed = r.get('n_changed', 0)
            if is_single and (m_matched > 1 or m_changed > 1):
                yp.append('BLOCK')
            elif m_matched > 1 or m_changed > 1:
                yp.append('CONFIRM')
            else:
                yp.append('ALLOW')
            lf.append(2)
            to.append(False)
        m = compute_metrics(yt, yp)
        m.update(compute_v2_1_metrics(yt, yp, dset, lf, to))
        return m

    report_data['baselines']['Row_count_dry_run'] = {
        'tune': eval_dry_run(tune_set),
        'val': eval_dry_run(val_set)
    }

    print("Running paraphrase evaluations...")
    for tr in ['linker', 'llm']:
        m_ot, _, _ = evaluate_configuration(tune_set, extractor_name=tr, variant='variant_a', paraphrase=False)
        m_pt, _, _ = evaluate_configuration(tune_set, extractor_name=tr, variant='variant_a', paraphrase=True, para_map=para_map)
        m_ov, _, _ = evaluate_configuration(val_set, extractor_name=tr, variant='variant_a', paraphrase=False)
        m_pv, _, _ = evaluate_configuration(val_set, extractor_name=tr, variant='variant_a', paraphrase=True, para_map=para_map)
        report_data['paraphrase_eval'][tr] = {
            'orig_tune': m_ot,
            'para_tune': m_pt,
            'orig_val': m_ov,
            'para_val': m_pv
        }

    print("Evaluating LLM abstention threshold trade-offs...")
    thresholds = [0.3, 0.5, 0.7, 0.9]
    for th in thresholds:
        m_th_t, _, _ = evaluate_configuration(tune_set, extractor_name='llm', variant='variant_a', llm_threshold=th)
        m_th_v, _, _ = evaluate_configuration(val_set, extractor_name='llm', variant='variant_a', llm_threshold=th)
        report_data['llm_thresholds'][f"thresh_{th}"] = {
            'tune': m_th_t,
            'val': m_th_v
        }

    out_json = "results/dev_audit/v2_1_metrics.json"
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(report_data, f, indent=2)
    print(f"All v2.1 metrics successfully saved to {out_json}")

if __name__ == "__main__":
    main()
