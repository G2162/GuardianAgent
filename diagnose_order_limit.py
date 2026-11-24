import json
from evaluate_dev import load_dev_data, resolve_db_path
from run_execution_robustness import rewrite_e_order_limit
from guardian_v2 import guardian_check_v2

tune, val = load_dev_data()
records = tune + val

pairs = rewrite_e_order_limit(records)
print(f"Total E_order_limit candidate pairs: {len(pairs)}")

results = {}

for track in ['linker', 'llm']:
    print(f"\n=== Track: {track.upper()} ===")
    same = 0
    diff = 0
    samples = []
    flips_by_family = {}
    
    for orig_sql, rew_sql, typ, tbl, rec in pairs:
        db = resolve_db_path(rec['database'])
        req = rec['request']
        res_orig = guardian_check_v2(req, orig_sql, db_path=db, record=rec, extractor=track)
        res_rew = guardian_check_v2(req, rew_sql, db_path=db, record=rec, extractor=track)
        
        fam = rec.get("family_id", "unknown")
        if res_orig['decision'] == res_rew['decision']:
            same += 1
        else:
            diff += 1
            flips_by_family[fam] = flips_by_family.get(fam, 0) + 1
            if len(samples) < 5:
                samples.append({
                    "case_id": rec.get("case_id"),
                    "family_id": fam,
                    "request": req,
                    "orig_sql": orig_sql,
                    "orig_decision": res_orig['decision'],
                    "orig_reasons": res_orig['reasons'],
                    "rew_sql": rew_sql,
                    "rew_decision": res_rew['decision'],
                    "rew_reasons": res_rew['reasons'],
                })
                
    agreement_rate = same / len(pairs) if pairs else 0.0
    print(f"Agreement: {same}/{len(pairs)} ({agreement_rate*100:.1f}%), Disagreements: {diff}")
    print(f"Flips by family: {flips_by_family}")
    
    for i, s in enumerate(samples):
        print(f"\n--- Sample {i+1} [ID: {s['case_id']}, Family: {s['family_id']}] ---")
        print(f"  Request: {s['request']}")
        print(f"  Orig SQL: {s['orig_sql']}")
        print(f"  Orig Decision: {s['orig_decision']} | Reasons: {s['orig_reasons']}")
        print(f"  Rew SQL:  {s['rew_sql']}")
        print(f"  Rew Decision:  {s['rew_decision']} | Reasons: {s['rew_reasons']}")

    results[track] = {
        "agreement": f"{same}/{len(pairs)}",
        "agreement_rate": round(agreement_rate, 4),
        "flips_by_family": flips_by_family,
        "samples": samples
    }

with open("results/dev_audit/order_limit_diagnosis.json", "w") as f:
    json.dump(results, f, indent=2)
