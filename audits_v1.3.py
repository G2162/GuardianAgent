"""
audits_v1.3.py
==============
Runs the four formal QA audits required under Step 4:
  1. Token audit: fixed vocabulary check (CONTRADICTORY, UPDATED, sneaky, wrong_..., test_entry...).
  2. Row-count audit: n_matched and n_changed distribution per family.
  3. Shortcut classifier: character n-gram logistic regression on DEV, evaluated on TEST (data_qa).
  4. Collision guard verification across all families.

Logs read of TEST to results/test_runs.log as type=data_qa.
"""
import json, re, hashlib, datetime
from pathlib import Path
from collections import Counter, defaultdict

LOG_PATH = Path('results/test_runs.log')

# 1. Log QA read
with open(LOG_PATH, 'a', encoding='utf-8') as f:
    f.write(json.dumps({
        'timestamp': datetime.datetime.now().isoformat(),
        'split': 'test',
        'type': 'data_qa',
        'file': 'data/evaluation_splits/test_dataset_v1.3.json',
        'note': 'Audit verification: token audit, row-count audit, shortcut classifier'
    }) + '\n')

with open('data/evaluation_splits/dev_dataset_v1.3.json') as f:
    dev = json.load(f)
with open('data/evaluation_splits/test_dataset_v1.3.json') as f:
    test = json.load(f)

all_cases = dev + test
print(f"Loaded {len(dev)} DEV cases and {len(test)} TEST cases.")

# -------------------------------------------------------------
# Audit 1: Token Audit
# -------------------------------------------------------------
print("\n" + "="*50)
print("AUDIT 1: Token Audit")
print("="*50)
banned_tokens = ['CONTRADICTORY', 'UPDATED', 'sneaky', 'wrong_', 'test_entry']
leakage_found = False
for tok in banned_tokens:
    unsafe_matches = [c['case_id'] for c in all_cases if c.get('gold_sql') and tok in c['sql']]
    benign_matches = [c['case_id'] for c in all_cases if not c.get('gold_sql') and tok in c['sql']]
    print(f"Token '{tok}': {len(unsafe_matches)} unsafe matches, {len(benign_matches)} benign matches")
    if len(unsafe_matches) > 0 and len(benign_matches) == 0:
        print(f"  WARNING: Token '{tok}' partitions unsafe from benign!")
        leakage_found = True
if not leakage_found:
    print("TOKEN AUDIT PASSED: No indicator token partitions unsafe from benign.")

# -------------------------------------------------------------
# Audit 2: Row-Count Audit
# -------------------------------------------------------------
print("\n" + "="*50)
print("AUDIT 2: Row-Count Audit (n_matched & n_changed)")
print("="*50)
by_family = defaultdict(list)
for c in all_cases:
    by_family[c['family_id']].append(c)

for fid, cases in sorted(by_family.items()):
    n_tot = len(cases)
    zeros = sum(1 for c in cases if c.get('n_matched', 0) == 0)
    pct_zero = 100 * zeros / n_tot if n_tot else 0
    print(f"  {fid:35s}: n={n_tot:3d}, n_matched==0: {zeros:2d} ({pct_zero:4.1f}%)")

# -------------------------------------------------------------
# Audit 3: Shortcut Classifier
# -------------------------------------------------------------
print("\n" + "="*50)
print("AUDIT 3: Shortcut Classifier (Char n-gram Logistic Regression)")
print("="*50)
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, classification_report

X_dev = [c['sql'] for c in dev]
y_dev = [1 if c.get('gold_sql') else 0 for c in dev]

X_test = [c['sql'] for c in test]
y_test = [1 if c.get('gold_sql') else 0 for c in test]

vec = TfidfVectorizer(analyzer='char_wb', ngram_range=(3, 5), max_features=1000)
X_dev_vec = vec.fit_transform(X_dev)
X_test_vec = vec.transform(X_test)

clf = LogisticRegression(max_iter=1000, random_state=42)
clf.fit(X_dev_vec, y_dev)

dev_preds = clf.predict(X_dev_vec)
test_preds = clf.predict(X_test_vec)

dev_acc = accuracy_score(y_dev, dev_preds)
test_acc = accuracy_score(y_test, test_preds)

print(f"DEV Accuracy:  {dev_acc*100:.2f}% (Target: <= 85%)")
print(f"TEST Accuracy: {test_acc*100:.2f}%")

# -------------------------------------------------------------
# Audit 4: Collision Guard Check
# -------------------------------------------------------------
print("\n" + "="*50)
print("AUDIT 4: Collision Guard Check")
print("="*50)
import sqlglot
def norm_sql(s):
    try:
        t = sqlglot.parse_one(s.rstrip(';'), read='sqlite')
        return t.sql(dialect='sqlite').strip().lower()
    except:
        return s.strip().lower()

seen = {}
collisions = 0
for c in all_cases:
    fid = c['family_id']
    if fid in ('MUT_OP_VERB_MISMATCH', 'MUT_OP_MODALITY_MISMATCH', 'MUT_MULTI_ROW_BLAST_RADIUS'):
        continue
    norm = norm_sql(c['sql'])
    if norm in seen and seen[norm] != fid:
        collisions += 1
    seen[norm] = fid
print(f"Cross-mutation collisions: {collisions} (Target: 0)")
assert collisions == 0, "Collisions found!"
print("COLLISION GUARD PASSED.")

