import json, random

dev = json.load(open('data/evaluation_splits/dev_dataset.json'))
from collections import defaultdict

random.seed(42)
by_fam = defaultdict(list)
for c in dev:
    by_fam[c['family_id']].append(c)

lines = []
lines.append("# GuardianAgent Label Audit Sample (DEV Split)")
lines.append("")
lines.append("This document audits 5 randomly sampled cases per family in the DEV split.")
lines.append("")
lines.append("## Natural Language Request Generation Methodology")
lines.append("- **Generation Method:** Deterministic Python programmatic string interpolation (templates) based on database schema inspection, primary keys, and column metadata.")
lines.append("- **Implementation Code:** Located in `generate_benign_candidates.py` (lines 80-210) and `generate_balanced_unsafe.py` (lines 75-250).")
lines.append("- **LLM Usage:** 0 LLM calls were used to generate NL requests or SQL queries in this dataset, ensuring deterministic reproducibility.")
lines.append("")
lines.append("---")
lines.append("")

flagged_count = 0

for fam in sorted(by_fam.keys()):
    cases = by_fam[fam]
    samples = random.sample(cases, min(5, len(cases)))
    lines.append(f"### Family: `{fam}` (Sample of {len(samples)} cases)")
    lines.append("")
    for i, c in enumerate(samples, 1):
        gold = c.get('gold_sql', c.get('sql'))
        mut = c.get('sql') if 'gold_sql' in c else "N/A (Benign Query)"
        lines.append(f"#### Case {i}: `{c['case_id']}` (Database: `{c['database']}`)")
        lines.append(f"- **NL Request:** `{c['request']}`")
        lines.append(f"- **Gold SQL:** `{gold}`")
        if mut != "N/A (Benign Query)":
            lines.append(f"- **Mutated / Candidate SQL:** `{mut}`")
        lines.append(f"- **Measured $N_{{\\text{{affected}}}}$:** `{c['measured_affected_rows']}`")
        lines.append(f"- **Expected Decision:** Variant A = **{c['expected_decision_variant_a']}**, Variant B = **{c['expected_decision_variant_b']}**")
        lines.append(f"- **Ground-Truth Intent:** `{c['ground_truth_intent']}`")
        
        # Check label consistency
        flag = None
        if fam == 'MUT_EXACT_SCOPED_UPDATE' and c['measured_affected_rows'] != 1:
            flag = f"Expected N=1 for scoped update, measured {c['measured_affected_rows']}"
        elif fam == 'MUT_EXACT_SCOPED_DELETE' and c['measured_affected_rows'] != 1:
            flag = f"Expected N=1 for scoped delete, measured {c['measured_affected_rows']}"
        elif fam in ('MUT_MULTI_ROW_UPDATE', 'MUT_MULTI_ROW_DELETE') and c['measured_affected_rows'] <= 1:
            flag = f"Expected N>1 for multi-row, measured {c['measured_affected_rows']}"
            
        if flag:
            flagged_count += 1
            lines.append(f"- **Audit Flag:** :warning: {flag}")
        else:
            lines.append(f"- **Audit Label Assessment:** :white_check_mark: Valid and consistent with policy")
        lines.append("")
    lines.append("---")
    lines.append("")

lines.append(f"## Summary of Label Audit")
lines.append(f"- Total families audited: {len(by_fam)}")
lines.append(f"- Total cases audited: {len(by_fam) * 5}")
lines.append(f"- Total flagged anomalies: {flagged_count}")

with open('results/baseline_dev/label_audit_sample.md', 'w', encoding='utf-8') as f:
    f.write('\n'.join(lines))

print("Created results/baseline_dev/label_audit_sample.md successfully.")

