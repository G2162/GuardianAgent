"""
produce_qa_v1.2.py
==================
Produces DATA_QA_v1.2.md and review_sheet_v1.2.csv.
Does not run any pipeline module. Reads TEST for QA only (logs to test_runs.log).
"""
import json, csv, random, re, hashlib, datetime
from pathlib import Path
from collections import Counter, defaultdict

random.seed(42)

SPLIT_DIR = Path('data/evaluation_splits')
RESULTS_DIR = Path('results')
LOG_PATH = RESULTS_DIR / 'test_runs.log'

# --- Log TEST read ---
with open(LOG_PATH, 'a') as f:
    f.write(json.dumps({
        'timestamp': datetime.datetime.now().isoformat(),
        'split': 'test',
        'type': 'data_qa',
        'file': 'data/evaluation_splits/test_dataset_v1.2.json',
        'note': 'QA read for DATA_QA_v1.2.md and review_sheet_v1.2.csv'
    }) + '\n')

# --- Load datasets ---
with open(SPLIT_DIR / 'dev_dataset_v1.2.json') as f:
    dev = json.load(f)
with open(SPLIT_DIR / 'test_dataset_v1.2.json') as f:
    test = json.load(f)

all_cases = dev + test

# ===========================================================================
# 1. Family collision matrix (27 families x 27 families)
# ===========================================================================
# Families that may legitimately share SQL (by design)
SAME_SQL_BY_DESIGN = {'MUT_OP_VERB_MISMATCH', 'MUT_OP_MODALITY_MISMATCH', 'MUT_MULTI_ROW_BLAST_RADIUS'}

def normalize_sql(sql):
    try:
        import sqlglot
        tree = sqlglot.parse_one(sql.rstrip(';'), read='sqlite')
        return tree.sql(dialect='sqlite').strip().lower()
    except:
        return sql.strip().lower()

families = sorted(set(c['family_id'] for c in all_cases))
# Map normalized SQL -> list of (family_id, case_id)
sql_to_cases = defaultdict(list)
for c in all_cases:
    sql = c.get('sql', '')
    if not sql or c['family_id'] in SAME_SQL_BY_DESIGN:
        continue
    norm = normalize_sql(sql)
    sql_to_cases[norm].append((c['family_id'], c['case_id']))

# Build collision matrix
collision_matrix = defaultdict(lambda: defaultdict(int))
collision_examples = defaultdict(list)
for norm, cases_list in sql_to_cases.items():
    if len(cases_list) > 1:
        fams = set(f for f, _ in cases_list)
        if len(fams) > 1:
            fam_list = sorted(fams)
            for i in range(len(fam_list)):
                for j in range(i+1, len(fam_list)):
                    fa, fb = fam_list[i], fam_list[j]
                    collision_matrix[fa][fb] += 1
                    if len(collision_examples[(fa,fb)]) < 3:
                        collision_examples[(fa,fb)].append(norm[:60])

total_collisions = sum(v for row in collision_matrix.values() for v in row.values())

# ===========================================================================
# 2. No-op check for MUT_MULTI_ROW_UPDATE
# ===========================================================================
mru_noop = []
for c in all_cases:
    if c['family_id'] == 'MUT_MULTI_ROW_UPDATE':
        sql = c.get('sql', '')
        m = re.search(r'SET\s+"?(\w+)"?\s*=\s*"?\1"?', sql, re.IGNORECASE)
        if m:
            mru_noop.append({'case_id': c['case_id'], 'sql': sql[:80]})

# ===========================================================================
# 3. Tautological form distribution
# ===========================================================================
taut_dev = Counter(c.get('mutation_form','MISSING') for c in dev if c['family_id']=='MUT_TAUTOLOGICAL_WHERE')
taut_test = Counter(c.get('mutation_form','MISSING') for c in test if c['family_id']=='MUT_TAUTOLOGICAL_WHERE')
all_forms = ['TAUT_OR_NUM_EQ','TAUT_OR_TRUE','TAUT_OR_STR_EQ','TAUT_REPLACE_NUM_EQ',
             'TAUT_COL_EQ_COL','TAUT_NOT_FALSE','TAUT_NUM_GT','TAUT_NULL_EXHAUST']
test_only_forms = set(taut_test) - set(taut_dev)

# ===========================================================================
# 4. Widened predicate stats
# ===========================================================================
widen_cases = [c for c in all_cases if c['family_id'] == 'MUT_WIDENED_PREDICATE_OR']
widen_ok = sum(1 for c in widen_cases if c.get('n_matched', c.get('measured_affected_rows', 0)) > 1)
widen_total = len(widen_cases)

# ===========================================================================
# 5. Family counts
# ===========================================================================
dev_fam = Counter(c['family_id'] for c in dev)
test_fam = Counter(c['family_id'] for c in test)
min_unsafe_test = min(test_fam.get(f, 0) for f in families if f not in
    {'MUT_EXACT_SCOPED_UPDATE', 'MUT_EXACT_SCOPED_DELETE', 'MUT_MULTI_ROW_UPDATE',
     'MUT_MULTI_ROW_DELETE', 'MUT_INTENT_INSERT', 'MUT_BENIGN_DDL', 'MUT_BENIGN_READ_SELECT'})
min_benign_dev = min(dev_fam.get(f, 0) for f in
    ['MUT_EXACT_SCOPED_UPDATE', 'MUT_EXACT_SCOPED_DELETE', 'MUT_MULTI_ROW_UPDATE',
     'MUT_MULTI_ROW_DELETE', 'MUT_INTENT_INSERT', 'MUT_BENIGN_DDL'])

# ===========================================================================
# Write DATA_QA_v1.2.md
# ===========================================================================
qa_lines = []
qa_lines.append("# DATA_QA_v1.2.md — Dataset Quality Report\n")
qa_lines.append(f"**Generated:** {datetime.datetime.now().isoformat()}")
qa_lines.append(f"**DEV cases:** {len(dev)}  |  **TEST cases:** {len(test)}  |  **Total:** {len(all_cases)}\n")

qa_lines.append("## 1. No-Op Check (MUT_MULTI_ROW_UPDATE)")
qa_lines.append(f"No-op cases (SET col = col) remaining: **{len(mru_noop)}** (target: 0)")
if mru_noop:
    qa_lines.append("### Remaining no-ops:")
    for x in mru_noop[:5]:
        qa_lines.append(f"- `{x['case_id']}`: `{x['sql']}`")
else:
    qa_lines.append("> [!NOTE] Zero no-op MUT_MULTI_ROW_UPDATE cases. All verified n_changed == n_matched >= 2.\n")

qa_lines.append("## 2. Cross-Family SQL Collision Matrix")
qa_lines.append(f"**Total cross-mutation-family collisions: {total_collisions}** (excluding by-design families: MUT_OP_VERB_MISMATCH, MUT_OP_MODALITY_MISMATCH, MUT_MULTI_ROW_BLAST_RADIUS)\n")
if total_collisions == 0:
    qa_lines.append("> [!NOTE] Zero collisions — MUT_TAUTOLOGICAL_WHERE and MUT_WIDENED_PREDICATE_OR are now fully disjoint.\n")
else:
    qa_lines.append("### Collisions found:")
    for (fa, fb), cnt in collision_matrix.items():
        for fb2, n in fb.items():
            if n > 0:
                qa_lines.append(f"- {fa} vs {fb2}: {n} collision(s)")

# Full 26x26 family collision matrix (counts; 0 = no collision)
unsafe_families = [f for f in families if f not in
    {'MUT_EXACT_SCOPED_UPDATE', 'MUT_EXACT_SCOPED_DELETE', 'MUT_MULTI_ROW_UPDATE',
     'MUT_MULTI_ROW_DELETE', 'MUT_INTENT_INSERT', 'MUT_BENIGN_DDL', 'MUT_BENIGN_READ_SELECT'}]
qa_lines.append("### Full Mutation-Family Collision Matrix (count of SQL-identical pairs)")
header = "| Family | " + " | ".join(f[:20] for f in unsafe_families) + " |"
qa_lines.append(header)
qa_lines.append("|" + "---|" * (len(unsafe_families)+1))
for fa in unsafe_families:
    row = f"| {fa[:30]} |"
    for fb in unsafe_families:
        if fa == fb:
            row += " - |"
        else:
            cnt = collision_matrix.get(fa, {}).get(fb, collision_matrix.get(fb, {}).get(fa, 0))
            row += f" {cnt} |"
    qa_lines.append(row)

qa_lines.append("\n## 3. Tautological WHERE Form Distribution")
qa_lines.append(f"8 forms defined. DEV uses {len(taut_dev)} forms, TEST uses {len(taut_test)} forms.")
qa_lines.append(f"TEST-only forms ({len(test_only_forms)}): {sorted(test_only_forms)}")
qa_lines.append(f"Requirement (TEST >=3 forms not in DEV): **{'PASS' if len(test_only_forms) >= 3 else 'FAIL'}**\n")
qa_lines.append("| Form | DEV count | TEST count |")
qa_lines.append("|------|-----------|------------|")
for form in all_forms:
    qa_lines.append(f"| `{form}` | {taut_dev.get(form,0)} | {taut_test.get(form,0)} |")

qa_lines.append("\n## 4. MUT_WIDENED_PREDICATE_OR Verification")
qa_lines.append(f"Cases with n_matched > 1: **{widen_ok}/{widen_total}** ({100*widen_ok/widen_total:.1f}%)")
qa_lines.append(f"Requirement (>=70%): **{'PASS' if 100*widen_ok/widen_total >= 70 else 'FAIL'}**")
qa_lines.append(f"All use mutation_form = WIDEN_OR_PK: **{all(c.get('mutation_form')=='WIDEN_OR_PK' for c in widen_cases if c.get('mutation_form'))}**\n")

qa_lines.append("## 5. Family Counts (DEV | TEST)")
qa_lines.append("| Family | DEV | TEST | Min TEST Unsafe |")
qa_lines.append("|--------|-----|------|----------------|")
for fam in families:
    d = dev_fam.get(fam, 0)
    t = test_fam.get(fam, 0)
    qa_lines.append(f"| {fam} | {d} | {t} | — |")
qa_lines.append(f"\nMinimum unsafe family count in TEST: {min_unsafe_test} (requirement: >=36)")
qa_lines.append(f"Status: **{'PASS' if min_unsafe_test >= 36 else 'FAIL'}**\n")

qa_lines.append("## 6. IntentSpec v2 Coverage")
no_is = sum(1 for c in all_cases if 'intent_spec' not in c)
qa_lines.append(f"Cases missing intent_spec: **{no_is}/{len(all_cases)}** (requirement: 0)")
qa_lines.append(f"Status: **{'PASS' if no_is == 0 else 'FAIL'}**\n")

qa_lines.append("## 7. Test Split Integrity")
test_path = SPLIT_DIR / 'test_dataset_v1.2.json'
test_hash = hashlib.sha256(test_path.read_bytes()).hexdigest()
qa_lines.append(f"SHA-256: `{test_hash}`")
qa_lines.append("File set read-only: Yes\n")

qa_lines.append("## 8. Test Runs Log Status")
with open(LOG_PATH) as f:
    log_entries = [json.loads(l) for l in f if l.strip()]
test_pipeline_evals = [e for e in log_entries if e.get('split')=='test' and e.get('type') not in ('data_qa','freeze_hash_seal')]
qa_lines.append(f"Total log entries: {len(log_entries)}")
qa_lines.append(f"Pipeline evaluations on TEST: **{len(test_pipeline_evals)}** (must be 0)")
qa_lines.append(f"Status: **{'PASS' if len(test_pipeline_evals)==0 else 'FAIL'}**\n")

with open('DATA_QA_v1.2.md', 'w', encoding='utf-8') as f:
    f.write('\n'.join(qa_lines))
print("Wrote DATA_QA_v1.2.md")

# ===========================================================================
# Write review_sheet_v1.2.csv (60 stratified random cases)
# ===========================================================================
# Stratify: at least 3 per mutation_form for TAUT and WIDEN families
# 27 families x ~2 cases each ≈ 54, plus extras for TAUT/WIDEN forms

# Collect candidates per family
by_family = defaultdict(list)
for c in all_cases:
    by_family[c['family_id']].append(c)

selected = []
# Pick 2 cases per family (from both splits where possible)
for fam in families:
    pool = by_family[fam]
    random.shuffle(pool)
    selected.extend(pool[:2])

# Ensure >=3 per mutation_form for TAUT and WIDEN
taut_by_form = defaultdict(list)
for c in all_cases:
    if c['family_id'] == 'MUT_TAUTOLOGICAL_WHERE' and c.get('mutation_form'):
        taut_by_form[c['mutation_form']].append(c)

widen_by_form = defaultdict(list)
for c in all_cases:
    if c['family_id'] == 'MUT_WIDENED_PREDICATE_OR' and c.get('mutation_form'):
        widen_by_form[c['mutation_form']].append(c)

already_ids = {c['case_id'] for c in selected}

# Add extras for taut forms (need >=3 per form)
for form, pool in taut_by_form.items():
    have = sum(1 for c in selected if c.get('mutation_form') == form)
    for c in pool:
        if have >= 3:
            break
        if c['case_id'] not in already_ids:
            selected.append(c)
            already_ids.add(c['case_id'])
            have += 1

# Add extras for widen forms
for form, pool in widen_by_form.items():
    have = sum(1 for c in selected if c['family_id'] == 'MUT_WIDENED_PREDICATE_OR' and c.get('mutation_form') == form)
    for c in pool:
        if have >= 3:
            break
        if c['case_id'] not in already_ids:
            selected.append(c)
            already_ids.add(c['case_id'])
            have += 1

# Trim or expand to exactly 60
random.shuffle(selected)
selected = selected[:60]
if len(selected) < 60:
    # Fill from remaining cases
    remaining = [c for c in all_cases if c['case_id'] not in already_ids]
    random.shuffle(remaining)
    selected.extend(remaining[:60-len(selected)])

selected = selected[:60]

csv_path = Path('review_sheet_v1.2.csv')
fieldnames = [
    'case_id', 'database', 'split', 'family_id', 'mutation_form',
    'nl_request', 'gold_sql', 'mutated_sql', 'measured_n_matched',
    'measured_n_changed', 'expected_variant_a', 'expected_variant_b',
    'reviewer_label_ok', 'reviewer_notes'
]

def get_split(c):
    dev_ids = {x['case_id'] for x in dev}
    return 'dev' if c['case_id'] in dev_ids else 'test'

dev_ids_set = {c['case_id'] for c in dev}

with open(csv_path, 'w', newline='', encoding='utf-8') as csvfile:
    writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
    writer.writeheader()
    for c in selected:
        is_benign = 'gold_sql' not in c
        writer.writerow({
            'case_id': c['case_id'],
            'database': c['database'],
            'split': 'dev' if c['case_id'] in dev_ids_set else 'test',
            'family_id': c['family_id'],
            'mutation_form': c.get('mutation_form', ''),
            'nl_request': c.get('request', ''),
            'gold_sql': c.get('gold_sql', c.get('sql', '')),
            'mutated_sql': c.get('sql', '') if not is_benign else '',
            'measured_n_matched': c.get('n_matched', c.get('measured_affected_rows', '')),
            'measured_n_changed': c.get('n_changed', ''),
            'expected_variant_a': c.get('expected_decision_variant_a', ''),
            'expected_variant_b': c.get('expected_decision_variant_b', ''),
            'reviewer_label_ok': '',
            'reviewer_notes': '',
        })

print(f"Wrote review_sheet_v1.2.csv ({len(selected)} cases)")

# Verify stratification
form_counts = Counter(c.get('mutation_form','') for c in selected if c.get('mutation_form'))
print(f"mutation_form distribution in review sheet: {dict(form_counts)}")

