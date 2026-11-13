"""
run_shortcut_analysis.py
========================
Runs the 4 variations of the shortcut classifier:
1. Raw SQL text
2. Normalized SQL (sqlglot canonical formatting, literals replaced by type placeholders)
3. Request text only
4. Request text + SQL

Computes on DEV:
- Class balance, majority class baseline, balanced accuracy, macro-F1, confusion matrix
- Per-family recall on unsafe cases
- Per-family false-positive rate on benign cases
- Top 30 features positive & negative for each model

Runs frozen model once on TEST (data_qa) and reports the same metrics.
"""
import json, re, hashlib, datetime
from pathlib import Path
from collections import Counter, defaultdict
import sqlglot
from sqlglot import exp

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, balanced_accuracy_score, f1_score, confusion_matrix, classification_report

with open('data/evaluation_splits/dev_dataset_v1.3.json', encoding='utf-8') as f:
    dev = json.load(f)
with open('data/evaluation_splits/test_dataset_v1.3.json', encoding='utf-8') as f:
    test = json.load(f)

def normalize_sql_canonical(sql_str):
    if not sql_str:
        return ""
    try:
        # replace numbers with NUM, strings with STR
        s = re.sub(r"'[^']*'", "'STR'", sql_str)
        s = re.sub(r"\b\d+\b", "NUM", s)
        t = sqlglot.parse_one(s.rstrip(';'), read='sqlite')
        return t.sql(dialect='sqlite').strip().lower()
    except Exception:
        return sql_str.strip().lower()

y_dev = [1 if c.get('gold_sql') else 0 for c in dev]
y_test = [1 if c.get('gold_sql') else 0 for c in test]

MODELS = {
    '1_raw_sql': {
        'train': [c['sql'] for c in dev],
        'test': [c['sql'] for c in test],
        'analyzer': 'char_wb',
        'ngram': (3, 5),
    },
    '2_norm_sql': {
        'train': [normalize_sql_canonical(c['sql']) for c in dev],
        'test': [normalize_sql_canonical(c['sql']) for c in test],
        'analyzer': 'char_wb',
        'ngram': (3, 5),
    },
    '3_request_only': {
        'train': [c['request'] for c in dev],
        'test': [c['request'] for c in test],
        'analyzer': 'word',
        'ngram': (1, 2),
    },
    '4_request_and_sql': {
        'train': [c['request'] + " ||| " + c['sql'] for c in dev],
        'test': [c['request'] + " ||| " + c['sql'] for c in test],
        'analyzer': 'char_wb',
        'ngram': (3, 5),
    }
}

results = {}

for m_name, cfg in MODELS.items():
    print(f"\n==========================================")
    print(f"Running Shortcut Model: {m_name}")
    print(f"==========================================")
    vec = TfidfVectorizer(analyzer=cfg['analyzer'], ngram_range=cfg['ngram'], max_features=1000)
    X_train = vec.fit_transform(cfg['train'])
    X_test = vec.transform(cfg['test'])

    clf = LogisticRegression(max_iter=1000, random_state=42)
    clf.fit(X_train, y_dev)

    dev_preds = clf.predict(X_train)
    test_preds = clf.predict(X_test)

    # Metrics on DEV
    dev_acc = accuracy_score(y_dev, dev_preds)
    dev_bal_acc = balanced_accuracy_score(y_dev, dev_preds)
    dev_f1 = f1_score(y_dev, dev_preds, average='macro')
    dev_cm = confusion_matrix(y_dev, dev_preds).tolist()

    # Metrics on TEST
    test_acc = accuracy_score(y_test, test_preds)
    test_bal_acc = balanced_accuracy_score(y_test, test_preds)
    test_f1 = f1_score(y_test, test_preds, average='macro')
    test_cm = confusion_matrix(y_test, test_preds).tolist()

    # Per-family recall (unsafe) & FPR (benign) on DEV
    dev_recall_unsafe = {}
    dev_fpr_benign = {}
    for i, c in enumerate(dev):
        fid = c['family_id']
        is_unsafe = bool(c.get('gold_sql'))
        pred = dev_preds[i]
        if is_unsafe:
            if fid not in dev_recall_unsafe:
                dev_recall_unsafe[fid] = {'correct': 0, 'total': 0}
            dev_recall_unsafe[fid]['total'] += 1
            if pred == 1:
                dev_recall_unsafe[fid]['correct'] += 1
        else:
            if fid not in dev_fpr_benign:
                dev_fpr_benign[fid] = {'fp': 0, 'total': 0}
            dev_fpr_benign[fid]['total'] += 1
            if pred == 1:
                dev_fpr_benign[fid]['fp'] += 1

    # Per-family recall (unsafe) & FPR (benign) on TEST
    test_recall_unsafe = {}
    test_fpr_benign = {}
    for i, c in enumerate(test):
        fid = c['family_id']
        is_unsafe = bool(c.get('gold_sql'))
        pred = test_preds[i]
        if is_unsafe:
            if fid not in test_recall_unsafe:
                test_recall_unsafe[fid] = {'correct': 0, 'total': 0}
            test_recall_unsafe[fid]['total'] += 1
            if pred == 1:
                test_recall_unsafe[fid]['correct'] += 1
        else:
            if fid not in test_fpr_benign:
                test_fpr_benign[fid] = {'fp': 0, 'total': 0}
            test_fpr_benign[fid]['total'] += 1
            if pred == 1:
                test_fpr_benign[fid]['fp'] += 1

    # Top 30 features
    feat_names = vec.get_feature_names_out()
    coefs = clf.coef_[0]
    top_pos = sorted(zip(coefs, feat_names), reverse=True)[:30]
    top_neg = sorted(zip(coefs, feat_names))[:30]

    results[m_name] = {
        'dev': {
            'accuracy': round(dev_acc, 4),
            'balanced_accuracy': round(dev_bal_acc, 4),
            'macro_f1': round(dev_f1, 4),
            'confusion_matrix': dev_cm,
            'recall_unsafe': {f: round(d['correct']/d['total'], 3) for f, d in dev_recall_unsafe.items()},
            'fpr_benign': {f: round(d['fp']/d['total'], 3) for f, d in dev_fpr_benign.items()},
        },
        'test': {
            'accuracy': round(test_acc, 4),
            'balanced_accuracy': round(test_bal_acc, 4),
            'macro_f1': round(test_f1, 4),
            'confusion_matrix': test_cm,
            'recall_unsafe': {f: round(d['correct']/d['total'], 3) for f, d in test_recall_unsafe.items()},
            'fpr_benign': {f: round(d['fp']/d['total'], 3) for f, d in test_fpr_benign.items()},
        },
        'top_unsafe_features': [(f, round(float(w), 3)) for w, f in top_pos],
        'top_benign_features': [(f, round(float(w), 3)) for w, f in top_neg],
    }

    print(f"  DEV:  Acc={dev_acc*100:.2f}%, BalAcc={dev_bal_acc*100:.2f}%, MacroF1={dev_f1:.4f}")
    print(f"  TEST: Acc={test_acc*100:.2f}%, BalAcc={test_bal_acc*100:.2f}%, MacroF1={test_f1:.4f}")

out_path = 'results/dataset_audit/shortcut_analysis_results.json'
with open(out_path, 'w', encoding='utf-8') as f:
    json.dump(results, f, indent=2)

print(f"\nSaved all shortcut analysis results to {out_path}")

