import os, sys, json, sqlite3, time, math
from collections import Counter

# Set environment before any imports
os.environ['GUARDIAN_DISABLE_LLM'] = '1'

import eval_guard
import guardian

# 1. Call eval_guard first
eval_guard.verify_and_log_eval("dev", config_desc="GUARDIAN_DISABLE_LLM=1", intent_track="Track A/B", pipeline_version="v1.1")

# 2. Load DEV cases
dev_cases = json.load(open('data/evaluation_splits/dev_dataset.json'))
db_inventory = json.load(open('data/evaluation_dbs/db_inventory.json'))
policy = json.load(open('labeling_policy.json'))
catastrophic_ids = {p['id'] for p in policy if p['catastrophic']}

print(f"Loaded {len(dev_cases)} DEV cases across {len(set(c['database'] for c in dev_cases))} databases.")

def wilson_ci(k, n, z=1.96):
    if n == 0:
        return 0.0, 0.0, 0.0
    p = k / n
    denom = 1 + (z**2) / n
    center = (p + (z**2) / (2 * n)) / denom
    margin = (z * math.sqrt((p * (1 - p) / n) + (z**2) / (4 * n**2))) / denom
    return p * 100, max(0.0, (center - margin) * 100), min(100.0, (center + margin) * 100)

def run_evaluation(track_name, use_oracle_intent=False):
    print(f"\n=======================================================")
    print(f"RUNNING BASELINE EVALUATION: {track_name} (GUARDIAN_DISABLE_LLM=1)")
    print(f"=======================================================")
    
    results = []
    field_matches = {'operation': 0, 'table': 0, 'field': 0, 'value': 0, 'scope': 0}
    total_eval = len(dev_cases)
    timeouts = 0
    
    t0_all = time.time()
    
    for idx, case in enumerate(dev_cases):
        db_name = case['database']
        db_path = db_inventory[db_name]['path']
        sql = case['sql']
        user_req = case['request']
        gold_intent = case['ground_truth_intent']
        
        conn = sqlite3.connect(db_path)
        
        t0 = time.time()
        try:
            if use_oracle_intent:
                # Track A: Oracle Intent
                res = guardian.guardian_check(user_req, sql, known_intent=gold_intent, connection=conn)
            else:
                # Track B: Extracted Intent
                res = guardian.guardian_check(user_req, sql, known_intent=None, connection=conn)
            elapsed_ms = (time.time() - t0) * 1000.0
            
            # Check intent extraction accuracy for Track B
            ext_intent = res.get('intent', {})
            if ext_intent:
                for k in field_matches.keys():
                    if str(ext_intent.get(k, '')).lower() == str(gold_intent.get(k, '')).lower():
                        field_matches[k] += 1
                        
            decision = res.get('risk', {}).get('decision', 'CONFIRM')
        except Exception as e:
            decision = 'CONFIRM'
            elapsed_ms = (time.time() - t0) * 1000.0
            if "timeout" in str(e).lower():
                timeouts += 1
        finally:
            conn.close()
            
        results.append({
            'case_id': case['case_id'],
            'family_id': case['family_id'],
            'database': case['database'],
            'expected_a': case['expected_decision_variant_a'],
            'expected_b': case['expected_decision_variant_b'],
            'predicted': decision,
            'catastrophic': case.get('catastrophic', False),
            'elapsed_ms': elapsed_ms
        })
        
        if (idx + 1) % 100 == 0 or (idx + 1) == total_eval:
            print(f"  Processed {idx + 1}/{total_eval} queries ({time.time() - t0_all:.1f}s)...")
            
    # Metrics computation
    total_time = time.time() - t0_all
    print(f"\nCompleted {track_name} in {total_time:.2f}s ({total_time*1000/total_eval:.2f} ms/query)")
    
    # Analyze metrics under Variant A and Variant B
    def compute_metrics_for_variant(variant_name, exp_key):
        # 3x3 confusion matrix
        matrix = {
            'ALLOW': {'ALLOW': 0, 'CONFIRM': 0, 'BLOCK': 0},
            'CONFIRM': {'ALLOW': 0, 'CONFIRM': 0, 'BLOCK': 0},
            'BLOCK': {'ALLOW': 0, 'CONFIRM': 0, 'BLOCK': 0}
        }
        for r in results:
            exp = r[exp_key]
            pred = r['predicted']
            matrix[exp][pred] += 1
            
        unsafe_cases = [r for r in results if r[exp_key] == 'BLOCK']
        benign_cases = [r for r in results if r[exp_key] in ('ALLOW', 'CONFIRM')]
        allow_cases = [r for r in results if r[exp_key] == 'ALLOW']
        cat_cases = [r for r in results if r['catastrophic']]
        
        n_unsafe = len(unsafe_cases)
        n_benign = len(benign_cases)
        n_allow = len(allow_cases)
        n_cat = len(cat_cases)
        
        # Unsafe metrics
        block_unsafe = sum(1 for r in unsafe_cases if r['predicted'] == 'BLOCK')
        confirm_unsafe = sum(1 for r in unsafe_cases if r['predicted'] == 'CONFIRM')
        intercept_unsafe = block_unsafe + confirm_unsafe
        worst_escape = sum(1 for r in unsafe_cases if r['predicted'] in ('ALLOW', 'CONFIRM'))
        cat_escape = sum(1 for r in cat_cases if r['predicted'] == 'ALLOW')
        
        # Benign metrics
        fbr_count = sum(1 for r in benign_cases if r['predicted'] == 'BLOCK')
        ir_count = sum(1 for r in benign_cases if r['predicted'] == 'CONFIRM')
        oer_count = sum(1 for r in allow_cases if r['predicted'] == 'CONFIRM')
        
        # Wilson CIs
        r_block, ci_block_l, ci_block_h = wilson_ci(block_unsafe, n_unsafe)
        r_int, ci_int_l, ci_int_h = wilson_ci(intercept_unsafe, n_unsafe)
        r_conf_u, _, _ = wilson_ci(confirm_unsafe, n_unsafe)
        r_worst, ci_worst_l, ci_worst_h = wilson_ci(worst_escape, n_unsafe)
        fbr, ci_fbr_l, ci_fbr_h = wilson_ci(fbr_count, n_benign)
        ir, ci_ir_l, ci_ir_h = wilson_ci(ir_count, n_benign)
        oer, ci_oer_l, ci_oer_h = wilson_ci(oer_count, n_allow)
        r_tout, _, _ = wilson_ci(timeouts, total_eval)
        
        return {
            'matrix': matrix,
            'n_unsafe': n_unsafe,
            'n_benign': n_benign,
            'n_allow': n_allow,
            'n_catastrophic': n_cat,
            'R_block_unsafe': r_block,
            'ci_block': (ci_block_l, ci_block_h),
            'R_intercept': r_int,
            'R_confirm_unsafe': r_conf_u,
            'ci_intercept': (ci_int_l, ci_int_h),
            'R_worst_escape': r_worst,
            'ci_worst_escape': (ci_worst_l, ci_worst_h),
            'catastrophic_escapes': cat_escape,
            'FBR': fbr,
            'ci_fbr': (ci_fbr_l, ci_fbr_h),
            'IR': ir,
            'ci_ir': (ci_ir_l, ci_ir_h),
            'OER': oer,
            'ci_oer': (ci_oer_l, ci_oer_h),
            'R_timeout': r_tout
        }
        
    m_var_a = compute_metrics_for_variant("Variant A", 'expected_a')
    m_var_b = compute_metrics_for_variant("Variant B", 'expected_b')
    
    # Per family breakdown
    fam_breakdown = {}
    for r in results:
        f = r['family_id']
        fam_breakdown.setdefault(f, {'total': 0, 'ALLOW': 0, 'CONFIRM': 0, 'BLOCK': 0, 'cat_escapes': 0})
        fam_breakdown[f]['total'] += 1
        fam_breakdown[f][r['predicted']] += 1
        if r['catastrophic'] and r['predicted'] == 'ALLOW':
            fam_breakdown[f]['cat_escapes'] += 1
            
    intent_acc = {k: v / total_eval * 100 for k, v in field_matches.items()}
    
    return {
        'track': track_name,
        'variant_a': m_var_a,
        'variant_b': m_var_b,
        'per_family': fam_breakdown,
        'intent_accuracy': intent_acc,
        'latencies': [r['elapsed_ms'] for r in results]
    }

if __name__ == '__main__':
    track_a = run_evaluation("Track A (Oracle Intent)", use_oracle_intent=True)
    track_b = run_evaluation("Track B (Extracted Intent)", use_oracle_intent=False)
    
    output = {
        'created_at': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'split': 'dev',
        'pipeline_config': 'GUARDIAN_DISABLE_LLM=1',
        'track_a_oracle': track_a,
        'track_b_extracted': track_b
    }
    
    os.makedirs('results/baseline_dev', exist_ok=True)
    with open('results/baseline_dev/dev_baseline_report.json', 'w') as f:
        json.dump(output, f, indent=2)
        
    print("\nSuccessfully executed and saved baseline results to results/baseline_dev/dev_baseline_report.json")

