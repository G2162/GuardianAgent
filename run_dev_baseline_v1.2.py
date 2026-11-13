"""
run_dev_baseline_v1.2.py
========================
Runs the legacy unadapted pipeline baseline on DEV split v1.2.
No pipeline modifications. GUARDIAN_DISABLE_LLM=1.
Saves to results/baseline_dev/dev_baseline_v1.2_report.json.
"""
import os, sys, json, sqlite3, time, math
from collections import Counter

os.environ['GUARDIAN_DISABLE_LLM'] = '1'

import eval_guard
import guardian

# 1. Guard
eval_guard.verify_and_log_eval(
    "dev",
    config_desc="GUARDIAN_DISABLE_LLM=1",
    intent_track="Track A/B",
    pipeline_version="v1.2",
    dataset_version="v1.2"
)

# 2. Load v1.2 DEV cases
dev_cases = json.load(open('data/evaluation_splits/dev_dataset_v1.2.json'))
db_inventory = json.load(open('data/evaluation_dbs/db_inventory.json'))
policy = json.load(open('labeling_policy.json'))
catastrophic_ids = {p['id'] for p in policy if p['catastrophic']}

print(f"Loaded {len(dev_cases)} DEV v1.2 cases across {len(set(c['database'] for c in dev_cases))} databases.")

def wilson_ci(k, n, z=1.96):
    if n == 0:
        return 0.0, 0.0, 0.0
    p = k / n
    denom = 1 + (z**2) / n
    center = (p + (z**2) / (2*n)) / denom
    margin = (z * math.sqrt((p*(1-p)/n) + (z**2)/(4*n**2))) / denom
    return p*100, max(0.0,(center-margin)*100), min(100.0,(center+margin)*100)

def run_evaluation(track_name, use_oracle_intent=False):
    print(f"\n{'='*55}")
    print(f"RUNNING: {track_name} (GUARDIAN_DISABLE_LLM=1, dataset=v1.2)")
    print(f"{'='*55}")

    results = []
    field_matches = {'operation': 0, 'table': 0, 'field': 0, 'value': 0, 'scope': 0}
    total_eval = len(dev_cases)
    timeouts = 0

    t0_all = time.time()

    for i, case in enumerate(dev_cases):
        db_name = case['database']
        db_path = f"data/evaluation_dbs/{db_name}.sqlite"

        is_benign = 'gold_sql' not in case
        sql = case.get('sql', '')
        request = case.get('request', '')
        gti = case.get('ground_truth_intent', {})
        expected_va = case.get('expected_decision_variant_a', 'UNKNOWN')
        expected_vb = case.get('expected_decision_variant_b', 'UNKNOWN')
        fid = case['family_id']

        if use_oracle_intent:
            # Pass ground_truth_intent directly (Track A)
            # Adapt keys: pipeline expects 'target' not 'table'
            intent_arg = {
                'operation': gti.get('operation'),
                'target': gti.get('target', gti.get('table')),   # pipeline reads 'target'
                'table': gti.get('table'),
                'field': gti.get('field'),
                'value': str(gti.get('value', '')),
                'scope': gti.get('scope'),
            }
        else:
            intent_arg = None

        t0 = time.time()
        try:
            conn = sqlite3.connect(db_path)
            res = guardian.guardian_check(
                user_request=request,
                sql=sql,
                known_intent=intent_arg,
                connection=conn,
            )
            decision = res.get('risk', {}).get('decision', 'CONFIRM') if isinstance(res, dict) else str(res)
            conn.close()
        except Exception as e:
            decision = 'CONFIRM'
        latency_ms = (time.time() - t0) * 1000

        if use_oracle_intent and gti:
            # Track intent field match accuracy
            extracted = {}  # Oracle: we don't re-extract
            for field in field_matches:
                pass  # Oracle intent is ground truth, no extraction

        results.append({
            'case_id': case['case_id'],
            'family_id': fid,
            'is_benign': is_benign,
            'decision': decision,
            'expected_va': expected_va,
            'expected_vb': expected_vb,
            'catastrophic': fid in catastrophic_ids,
            'latency_ms': latency_ms,
        })

        if (i+1) % 50 == 0:
            print(f"  Progress: {i+1}/{total_eval}")

    total_ms = (time.time() - t0_all) * 1000

    # --- Compute metrics ---
    benign = [r for r in results if r['is_benign']]
    unsafe = [r for r in results if not r['is_benign']]
    crit   = [r for r in unsafe if r['catastrophic']]

    # Variant A metrics
    def metrics(subset, variant='va'):
        exp_key = f'expected_{variant}'
        n_allow_expected = sum(1 for r in subset if r[exp_key] == 'ALLOW')
        n_block_expected = sum(1 for r in subset if r[exp_key] == 'BLOCK')
        n_confirm_expected = sum(1 for r in subset if r[exp_key] == 'CONFIRM')

        correct = sum(1 for r in subset if r['decision'] == r[exp_key])
        blocked = sum(1 for r in subset if r['decision'] == 'BLOCK')
        allowed = sum(1 for r in subset if r['decision'] == 'ALLOW')
        confirmed = sum(1 for r in subset if r['decision'] == 'CONFIRM')

        return {
            'n': len(subset),
            'correct': correct,
            'blocked': blocked,
            'allowed': allowed,
            'confirmed': confirmed,
            'accuracy': 100*correct/len(subset) if subset else 0,
        }

    # Unsafe metrics (Variant A)
    n_unsafe = len(unsafe)
    blocked_unsafe_va = sum(1 for r in unsafe if r['decision'] == 'BLOCK' and r['expected_va'] == 'BLOCK')
    total_expected_block_va = sum(1 for r in unsafe if r['expected_va'] == 'BLOCK')
    r_block_unsafe_va = 100 * sum(1 for r in unsafe if r['decision'] == 'BLOCK') / n_unsafe if n_unsafe else 0

    # Benign metrics
    n_benign = len(benign)
    # FBR: false block rate on benign expected-ALLOW cases
    benign_allow_va = [r for r in benign if r['expected_va'] == 'ALLOW']
    fbr_va = 100 * sum(1 for r in benign_allow_va if r['decision'] == 'BLOCK') / len(benign_allow_va) if benign_allow_va else 0

    # Catastrophic escapes
    cat_escapes_va = [r for r in crit if r['decision'] == 'ALLOW']
    r_block_unsafe_num_va = sum(1 for r in unsafe if r['decision'] == 'BLOCK') / n_unsafe if n_unsafe else 0
    fbr_num_va = fbr_va / 100.0
    youden_va = r_block_unsafe_num_va - fbr_num_va

    # Variant B
    r_block_unsafe_vb = 100 * sum(1 for r in unsafe if r['decision'] == 'BLOCK') / n_unsafe if n_unsafe else 0
    benign_allow_vb = [r for r in benign if r['expected_vb'] == 'ALLOW']
    fbr_vb = 100 * sum(1 for r in benign_allow_vb if r['decision'] == 'BLOCK') / len(benign_allow_vb) if benign_allow_vb else 0

    # Confusion matrix (3x3): expected x actual
    decisions = ['ALLOW', 'CONFIRM', 'BLOCK']
    conf_va = Counter((r['expected_va'], r['decision']) for r in results)

    report = {
        'track': track_name,
        'dataset_version': 'v1.2',
        'n_total': len(results),
        'n_benign': n_benign,
        'n_unsafe': n_unsafe,
        'n_catastrophic': len(crit),
        'variant_a': {
            'r_block_unsafe_pct': round(r_block_unsafe_va, 2),
            'fbr_pct': round(fbr_va, 2),
            'youden_j': round(youden_va, 4),
            'catastrophic_escapes': len(cat_escapes_va),
            'wilson_r_block': wilson_ci(sum(1 for r in unsafe if r['decision']=='BLOCK'), n_unsafe),
            'wilson_fbr': wilson_ci(sum(1 for r in benign_allow_va if r['decision']=='BLOCK'), len(benign_allow_va)),
        },
        'variant_b': {
            'r_block_unsafe_pct': round(r_block_unsafe_vb, 2),
            'fbr_pct': round(fbr_vb, 2),
            'catastrophic_escapes': len([r for r in crit if r['decision']=='ALLOW']),
        },
        'confusion_matrix_va': {
            f'exp_{e}_act_{a}': conf_va.get((e,a),0)
            for e in decisions for a in decisions
        },
        'by_family': {
            fam: {
                'n': sum(1 for r in results if r['family_id']==fam),
                'BLOCK': sum(1 for r in results if r['family_id']==fam and r['decision']=='BLOCK'),
                'CONFIRM': sum(1 for r in results if r['family_id']==fam and r['decision']=='CONFIRM'),
                'ALLOW': sum(1 for r in results if r['family_id']==fam and r['decision']=='ALLOW'),
                'expected_va': policy_lookup.get(fam, {}).get('expected_decision_variant_a', '?'),
                'expected_vb': policy_lookup.get(fam, {}).get('expected_decision_variant_b', '?'),
            }
            for fam in set(r['family_id'] for r in results)
        },
        'mean_latency_ms': round(total_ms / len(results), 2) if results else 0,
        'total_time_s': round(total_ms/1000, 1),
    }

    # Print summary
    print(f"\n--- {track_name} Variant A ---")
    print(f"  R_block_unsafe:    {report['variant_a']['r_block_unsafe_pct']:.2f}%")
    print(f"  FBR:               {report['variant_a']['fbr_pct']:.2f}%")
    print(f"  Youden's J:        {report['variant_a']['youden_j']:.4f}")
    print(f"  Catastrophic ALLOW:{report['variant_a']['catastrophic_escapes']}")
    print(f"\nPer-family (Variant A):")
    for fam, m in sorted(report['by_family'].items()):
        print(f"  {fam:40s} n={m['n']:3d} BLOCK={m['BLOCK']:3d} CONFIRM={m['CONFIRM']:3d} ALLOW={m['ALLOW']:3d} expected={m['expected_va']}")

    return report

policy_lookup = {p['id']: p for p in policy}

# Run both tracks
track_a = run_evaluation("Track A (Oracle Intent)", use_oracle_intent=True)
track_b = run_evaluation("Track B (Extracted Intent)", use_oracle_intent=False)

# Save report
report = {
    'dataset_version': 'v1.2',
    'pipeline_config': 'GUARDIAN_DISABLE_LLM=1',
    'track_a_oracle': track_a,
    'track_b_extracted': track_b,
}

os.makedirs('results/baseline_dev', exist_ok=True)
out_path = 'results/baseline_dev/dev_baseline_v1.2_report.json'
with open(out_path, 'w') as f:
    json.dump(report, f, indent=2)
print(f"\nSaved: {out_path}")
print("DEV baseline v1.2 complete.")

