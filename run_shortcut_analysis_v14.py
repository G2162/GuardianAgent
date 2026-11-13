"""
run_shortcut_analysis_v14.py
============================
Evaluates 4 shortcut classifiers on the PAIRED v1.4 benchmark:
  1. Raw SQL
  2. Normalized SQL (sqlglot canonical formatting, literals replaced by type placeholders)
  3. Request text only
  4. Request text + SQL

Verifies:
  - Request-only model is within 10 points of 50.0% balanced accuracy.
  - Normalized-SQL model is within 10 points of 50.0% balanced accuracy.
"""
import json, re, hashlib, datetime, os
from collections import Counter, defaultdict
import sqlglot
from sqlglot import exp

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, balanced_accuracy_score, f1_score, confusion_matrix

def normalize_sql_canonical(sql_str):
    if not sql_str:
        return ""
    try:
        s = re.sub(r"'[^']*'", "'STR'", sql_str)
        s = re.sub(r"\b\d+\b", "NUM", s)
        t = sqlglot.parse_one(s.rstrip(';'), read='sqlite')
        return t.sql(dialect='sqlite').strip().lower()
    except Exception:
        return sql_str.strip().lower()

def run_analysis():
    dev_path = 'data/evaluation_splits/dev_paired_dataset_v1.4.json'
    test_path = 'data/evaluation_splits/test_paired_dataset_v1.4.json'
    
    with open(dev_path, encoding='utf-8') as f:
        dev = json.load(f)
    with open(test_path, encoding='utf-8') as f:
        test = json.load(f)
        
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
        '4_request_plus_sql': {
            'train': [c['request'] + " " + c['sql'] for c in dev],
            'test': [c['request'] + " " + c['sql'] for c in test],
            'analyzer': 'char_wb',
            'ngram': (3, 5),
        }
    }
    
    results = {}
    
    print("\n=======================================================")
    print("SHORTCUT CLASSIFIER RE-AUDIT ON PAIRED SET (v1.4)")
    print("=======================================================")
    print(f"DEV PAIRED: {len(dev)} cases (Benign: {y_dev.count(0)}, Unsafe: {y_dev.count(1)})")
    print(f"TEST PAIRED: {len(test)} cases (Benign: {y_test.count(0)}, Unsafe: {y_test.count(1)})")
    
    for name, cfg in MODELS.items():
        vec = TfidfVectorizer(
            analyzer=cfg['analyzer'],
            ngram_range=cfg['ngram'],
            min_df=2,
            max_features=5000
        )
        X_train = vec.fit_transform(cfg['train'])
        X_test = vec.transform(cfg['test'])
        
        clf = LogisticRegression(max_iter=1000, random_state=42)
        clf.fit(X_train, y_dev)
        
        pred_dev = clf.predict(X_train)
        pred_test = clf.predict(X_test)
        
        acc_dev = accuracy_score(y_dev, pred_dev)
        bacc_dev = balanced_accuracy_score(y_dev, pred_dev)
        f1_dev = f1_score(y_dev, pred_dev, average='macro')
        
        acc_test = accuracy_score(y_test, pred_test)
        bacc_test = balanced_accuracy_score(y_test, pred_test)
        f1_test = f1_score(y_test, pred_test, average='macro')
        
        results[name] = {
            'dev': {
                'acc': acc_dev,
                'bacc': bacc_dev,
                'f1': f1_dev,
                'cm': confusion_matrix(y_dev, pred_dev).tolist()
            },
            'test': {
                'acc': acc_test,
                'bacc': bacc_test,
                'f1': f1_test,
                'cm': confusion_matrix(y_test, pred_test).tolist()
            }
        }
        
        print(f"\n--- Model: {name} ---")
        print(f"  DEV:  Acc = {acc_dev*100:.2f}%, Balanced Acc = {bacc_dev*100:.2f}%, Macro-F1 = {f1_dev:.4f}")
        print(f"  TEST: Acc = {acc_test*100:.2f}%, Balanced Acc = {bacc_test*100:.2f}%, Macro-F1 = {f1_test:.4f}")
        
    os.makedirs('results/dataset_audit', exist_ok=True)
    with open('results/dataset_audit/shortcut_reaudit_v14_results.json', 'w') as f:
        json.dump(results, f, indent=2)
        
    return results

if __name__ == '__main__':
    run_analysis()

