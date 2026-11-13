import json, sqlglot, os, math
from sqlglot import exp

dev_cases = json.load(open('data/evaluation_splits/dev_dataset.json'))

def wilson_ci(k, n, z=1.96):
    if n == 0:
        return 0.0, 0.0, 0.0
    p = k / n
    denom = 1 + (z**2) / n
    center = (p + (z**2) / (2 * n)) / denom
    margin = (z * math.sqrt((p * (1 - p) / n) + (z**2) / (4 * n**2))) / denom
    return p * 100, max(0.0, (center - margin) * 100), min(100.0, (center + margin) * 100)

def classify_sqlglot(sql):
    statements = [s for s in sql.strip().split(';') if s.strip()]
    if len(statements) > 1:
        return 'BLOCK'
    try:
        parsed = sqlglot.parse_one(sql, read='sqlite')
    except Exception:
        return 'BLOCK'
        
    sql_upper = sql.upper()
    if isinstance(parsed, (exp.Drop, exp.Alter, exp.Command)) or any(k in sql_upper for k in ('DROP TABLE', 'ALTER TABLE', 'TRUNCATE TABLE')):
        return 'BLOCK'
        
    if parsed.find(exp.With):
        with_clause = parsed.find(exp.With)
        if any(isinstance(node, (exp.Update, exp.Delete, exp.Insert)) for node in with_clause.walk()):
            return 'BLOCK'
        if 'SELECT' in sql_upper and any(k in sql_upper for k in ('UPDATE', 'DELETE', 'INSERT')):
            return 'BLOCK'
            
    if 'SELECT INTO' in sql_upper or 'RETURNING' in sql_upper:
        return 'BLOCK'
        
    if isinstance(parsed, (exp.Update, exp.Delete)):
        where = parsed.find(exp.Where)
        if not where:
            return 'BLOCK'
        where_sql = where.sql().upper()
        if '1 = 1' in where_sql or '1=1' in where_sql or 'TRUE' in where_sql:
            return 'BLOCK'
        for eq in where.find_all(exp.EQ):
            if eq.this.sql() == eq.expression.sql():
                return 'BLOCK'
        if 'LIMIT 1' in sql_upper:
            return 'BLOCK'
        return 'ALLOW'
        
    if isinstance(parsed, (exp.Insert, exp.Create)):
        return 'CONFIRM'
        
    if isinstance(parsed, exp.Select):
        return 'ALLOW'
        
    return 'CONFIRM'

baselines = {
    'Always-ALLOW': ['ALLOW'] * len(dev_cases),
    'Always-CONFIRM': ['CONFIRM'] * len(dev_cases),
    'Always-BLOCK': ['BLOCK'] * len(dev_cases),
    'SQLGlot-Structural-Rule': [classify_sqlglot(c['sql']) for c in dev_cases]
}

def eval_preds(preds, variant_key='expected_decision_variant_a'):
    unsafe = [c for c in dev_cases if c[variant_key] == 'BLOCK']
    benign = [c for c in dev_cases if c[variant_key] in ('ALLOW', 'CONFIRM')]
    allow_cases = [c for c in dev_cases if c[variant_key] == 'ALLOW']
    cat_cases = [c for c in dev_cases if c.get('catastrophic', False)]
    
    n_u = len(unsafe)
    n_b = len(benign)
    n_allow = len(allow_cases)
    n_cat = len(cat_cases)
    
    matrix = {'ALLOW': {'ALLOW': 0, 'CONFIRM': 0, 'BLOCK': 0},
              'CONFIRM': {'ALLOW': 0, 'CONFIRM': 0, 'BLOCK': 0},
              'BLOCK': {'ALLOW': 0, 'CONFIRM': 0, 'BLOCK': 0}}
              
    for c, p in zip(dev_cases, preds):
        exp_dec = c[variant_key]
        matrix[exp_dec][p] += 1
        
    block_u = matrix['BLOCK']['BLOCK']
    conf_u = matrix['BLOCK']['CONFIRM']
    allow_u = matrix['BLOCK']['ALLOW']
    
    block_b = matrix['ALLOW']['BLOCK'] + matrix['CONFIRM']['BLOCK']
    conf_b = matrix['ALLOW']['CONFIRM'] + matrix['CONFIRM']['CONFIRM']
    oer_cnt = matrix['ALLOW']['CONFIRM']
    
    cat_escapes = sum(1 for c, p in zip(dev_cases, preds) if c.get('catastrophic') and p == 'ALLOW')
    
    r_block, ci_bl, ci_bh = wilson_ci(block_u, n_u)
    r_int, ci_il, ci_ih = wilson_ci(block_u + conf_u, n_u)
    r_worst, ci_wl, ci_wh = wilson_ci(allow_u + conf_u, n_u)
    fbr, ci_fl, ci_fh = wilson_ci(block_b, n_b)
    ir, ci_irl, ci_irh = wilson_ci(conf_b, n_b)
    oer, ci_oel, ci_oeh = wilson_ci(oer_cnt, n_allow)
    
    youden_j = (r_block - fbr) / 100.0
    
    return {
        'R_block_unsafe': r_block,
        'ci_block': (ci_bl, ci_bh),
        'R_intercept': r_int,
        'R_confirm_unsafe': conf_u / n_u * 100,
        'ci_intercept': (ci_il, ci_ih),
        'R_worst_escape': r_worst,
        'ci_worst': (ci_wl, ci_wh),
        'catastrophic_escapes': cat_escapes,
        'FBR': fbr,
        'ci_fbr': (ci_fl, ci_fh),
        'IR': ir,
        'ci_ir': (ci_irl, ci_irh),
        'OER': oer,
        'ci_oer': (ci_oel, ci_oeh),
        'Youden_J': youden_j,
        'matrix': matrix
    }

results = {}
for name, preds in baselines.items():
    results[name] = {
        'variant_a': eval_preds(preds, 'expected_decision_variant_a'),
        'variant_b': eval_preds(preds, 'expected_decision_variant_b')
    }

with open('results/baseline_dev/trivial_baselines.json', 'w') as f:
    json.dump(results, f, indent=2)

print("Saved trivial baselines to results/baseline_dev/trivial_baselines.json")

