import json, random, os
os.environ['GUARDIAN_DISABLE_LLM'] = '1'
import intent_analyzer

dev = json.load(open('data/evaluation_splits/dev_dataset.json'))
random.seed(42)
sampled = random.sample(dev, 20)
for idx, c in enumerate(sampled, 1):
    ext = intent_analyzer.analyze_intent(c['request'])
    ext_dict = {k: ext.get(k) for k in ['operation', 'target', 'field', 'value', 'scope']}
    print(f"=== Case {idx}: {c['case_id']} | Family: {c['family_id']} ===")
    print("  NL Request:      ", c['request'])
    print("  Ground-Truth:    ", c['ground_truth_intent'])
    print("  Extracted Intent:", ext_dict)

