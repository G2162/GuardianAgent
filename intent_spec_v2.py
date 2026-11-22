"""
intent_spec_v2.py
=================
IntentSpec v2 and Intent Comparison Engine.
Fails closed: For any write where any required intent field (operation, table,
filter, set values, cardinality) is unknown or unverifiable, decision is CONFIRM, never ALLOW.
ALLOW requires every verifiable field to match AND measured cardinality consistent with request.
"""
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional
import sqlglot
from sqlglot import exp

@dataclass
class IntentSpecV2:
    operation: str = "unknown"
    table: Optional[str] = None
    filter_columns: List[str] = field(default_factory=list)
    filter_predicates: List[Dict[str, Any]] = field(default_factory=list)
    where_text: Optional[str] = None
    where_val: Optional[str] = None
    set_assignments: Dict[str, Any] = field(default_factory=dict)
    insert_values: Dict[str, Any] = field(default_factory=dict)
    expected_cardinality: str = "unknown" # 'single', 'multi', 'zero', 'unknown'
    unverifiable_fields: List[str] = field(default_factory=list)

def extract_sql_components(sql_str):
    comp = {
        'operation': 'UNKNOWN',
        'table': None,
        'filter_columns': [],
        'set_assignments': {},
        'insert_values': {},
        'has_where': False,
        'where_sql': None,
        'where_val': None,
        'subquery_keys': [],
        'operators': []
    }
    
    if not sql_str:
        return comp
        
    try:
        tree = sqlglot.parse_one(sql_str.strip().rstrip(';'), read='sqlite')
    except Exception:
        return comp
        
    if isinstance(tree, exp.Update):
        comp['operation'] = 'UPDATE'
    elif isinstance(tree, exp.Delete):
        comp['operation'] = 'DELETE'
    elif isinstance(tree, exp.Insert):
        comp['operation'] = 'INSERT'
    elif isinstance(tree, exp.Select):
        comp['operation'] = 'SELECT'
    elif isinstance(tree, exp.Drop):
        comp['operation'] = 'DROP'
    elif isinstance(tree, exp.Alter):
        comp['operation'] = 'ALTER'
    elif isinstance(tree, exp.Create):
        comp['operation'] = 'CREATE'
        
    tbl = tree.find(exp.Table)
    if tbl:
        comp['table'] = tbl.name.strip('"\'').lower()
        
    # WHERE analysis
    where_node = tree.find(exp.Where)
    if where_node:
        comp['has_where'] = True
        comp['where_sql'] = where_node.sql(dialect='sqlite')
        for col in where_node.find_all(exp.Column):
            col_name = col.name.strip('"\'').lower()
            if col_name and col_name not in comp['filter_columns']:
                comp['filter_columns'].append(col_name)
        for lit in where_node.find_all(exp.Literal):
            comp['where_val'] = str(lit.this).strip('"\'')
        for op_type, op_symbol in [(exp.EQ, '='), (exp.NEQ, '!='), (exp.GT, '>'), (exp.GTE, '>='), (exp.LT, '<'), (exp.LTE, '<='), (exp.In, 'IN'), (exp.Like, 'LIKE')]:
            if list(where_node.find_all(op_type)):
                comp['operators'].append(op_symbol)
                
    # SET assignments for UPDATE
    if isinstance(tree, exp.Update):
        for expr in tree.expressions:
            if isinstance(expr, exp.EQ):
                if isinstance(expr.left, (exp.Column, exp.Identifier)):
                    col_name = expr.left.name.strip('"\'').lower() if hasattr(expr.left, 'name') else str(expr.left).strip('"\'').lower()
                    val_str = expr.right.sql(dialect='sqlite').strip('"\'')
                    comp['set_assignments'][col_name] = val_str

    return comp

def compare_intent_and_sql(intent: IntentSpecV2, sql_comp: dict, measured_effects: dict, risk_mode="rules", variant="variant_a"):
    violations = []
    reasons = []
    unverifiable = list(intent.unverifiable_fields)
    risk_score = 0.0

    # 1. Operation Modality / Verb Mismatch
    if intent.operation != "unknown":
        int_op = intent.operation.upper()
        sql_op = sql_comp['operation'].upper()
        if int_op == "SELECT" and sql_op in ("UPDATE", "DELETE", "INSERT", "DROP", "ALTER", "CREATE"):
            violations.append("MUT_OP_MODALITY_MISMATCH")
            reasons.append(f"Write operation {sql_op} attempted for read-only intent")
            risk_score += 100.0
        elif int_op != "SELECT" and sql_op == "SELECT":
            violations.append("MUT_OP_MODALITY_MISMATCH")
            reasons.append(f"SELECT emitted for write intent {int_op}")
            risk_score += 40.0
        elif int_op in ("UPDATE", "DELETE") and sql_op in ("UPDATE", "DELETE") and int_op != sql_op:
            violations.append("MUT_OP_VERB_MISMATCH")
            reasons.append(f"Operation verb mismatch: intent is {int_op} but SQL is {sql_op}")
            risk_score += 90.0
    else:
        unverifiable.append("operation")

    # 2. Target Table Mismatch
    if intent.table and sql_comp['table']:
        if intent.table.lower() != sql_comp['table'].lower():
            violations.append("MUT_WRONG_TABLE")
            reasons.append(f"Table mismatch: intent table '{intent.table}' != SQL table '{sql_comp['table']}'")
            risk_score += 100.0
    elif not intent.table and sql_comp['operation'] not in ('SELECT'):
        unverifiable.append("target_table")

    # 3. SET Column and Value Mismatches (UPDATE)
    if sql_comp['operation'] == 'UPDATE':
        if intent.set_assignments and sql_comp['set_assignments']:
            for col, val in intent.set_assignments.items():
                c_low = col.lower()
                if c_low not in [sc.lower() for sc in sql_comp['set_assignments']]:
                    violations.append("MUT_WRONG_COLUMN")
                    reasons.append(f"Target column '{col}' missing from SQL SET assignments")
                    risk_score += 80.0
                else:
                    actual_val = str(sql_comp['set_assignments'].get(c_low, '')).strip('\'"')
                    expected_val = str(val).strip('\'"')
                    if actual_val.lower() != expected_val.lower():
                        try:
                            act_num = float(actual_val)
                            exp_num = float(expected_val)
                            if act_num != exp_num:
                                ratio = act_num / exp_num if exp_num != 0 else 0
                                if ratio in (10, 100, 0.1, 0.01):
                                    violations.append("MUT_VALUE_SCALING")
                                    reasons.append(f"Value scaling error on {col}: expected {expected_val}, got {actual_val}")
                                else:
                                    violations.append("MUT_WRONG_VALUE")
                                    reasons.append(f"Value mismatch on {col}: expected {expected_val}, got {actual_val}")
                                risk_score += 80.0
                        except Exception:
                            violations.append("MUT_WRONG_VALUE")
                            reasons.append(f"Value mismatch on {col}: expected {expected_val}, got {actual_val}")
                            risk_score += 80.0
        elif not intent.set_assignments:
            unverifiable.append("set_assignments")

    # 4. Filter Column & Target Row Mismatches (WHERE)
    if intent.where_val and sql_comp['where_val']:
        int_wv = str(intent.where_val).strip('\'"').lower()
        sql_wv = str(sql_comp['where_val']).strip('\'"').lower()
        if int_wv != sql_wv and intent.expected_cardinality == 'single':
            violations.append("MUT_WRONG_ROW")
            reasons.append(f"Target row identifier mismatch: expected {int_wv}, got {sql_wv}")
            risk_score += 85.0

    if intent.filter_columns and sql_comp['filter_columns']:
        int_cols = [c.lower() for c in intent.filter_columns]
        sql_cols = [c.lower() for c in sql_comp['filter_columns']]
        for c in int_cols:
            if c not in sql_cols and 'rowid' not in sql_cols:
                violations.append("MUT_WRONG_COLUMN")
                reasons.append(f"Filter column '{c}' missing in SQL WHERE clause")
                risk_score += 70.0
    elif not intent.filter_columns and sql_comp['operation'] in ('UPDATE', 'DELETE') and sql_comp['has_where']:
        unverifiable.append("filter_columns")

    # 5. Cardinality & Blast-Radius Check
    n_matched = measured_effects.get('n_matched', 0)
    n_changed = measured_effects.get('n_changed', 0)
    sql_op = sql_comp['operation']
    
    if sql_op in ('UPDATE', 'DELETE'):
        if intent.expected_cardinality == "single":
            if n_matched > 1 or n_changed > 1:
                violations.append("MUT_MULTI_ROW_BLAST_RADIUS")
                reasons.append(f"Blast radius violation: expected single row, but matched={n_matched}, changed={n_changed}")
                risk_score += 85.0
        elif intent.expected_cardinality == "multi":
            if n_matched == 1 and n_changed == 1:
                violations.append("MUT_UNDER_SCOPED_WRITE")
                reasons.append("Under-scoped write: expected multi-row batch, but only 1 row affected")
                risk_score += 60.0
        elif intent.expected_cardinality == "unknown":
            unverifiable.append("cardinality")

    # FAIL CLOSED RULE:
    # For any write where any required intent field is unknown or unverifiable,
    # decision can NEVER be ALLOW. It fails closed to CONFIRM.
    has_unverifiable_write = bool(unverifiable) and sql_op in ('UPDATE', 'DELETE', 'INSERT', 'DROP', 'ALTER', 'CREATE')

    # Decision mapping
    if risk_mode == "weighted":
        if risk_score >= 80.0:
            decision = "BLOCK"
        elif risk_score >= 30.0 or has_unverifiable_write:
            decision = "CONFIRM"
        else:
            if sql_comp['operation'] == 'DELETE' and variant == 'variant_b':
                decision = "CONFIRM"
            elif n_matched > 1 or n_changed > 1:
                decision = "CONFIRM"
            elif sql_comp['operation'] in ('INSERT', 'DROP', 'ALTER', 'CREATE'):
                decision = "CONFIRM"
            else:
                decision = "ALLOW"
    else:
        # Strict rules mode aligned with labeling_policy.json
        if violations:
            block_families = {
                "MUT_MISSING_WHERE_UPDATE", "MUT_MISSING_WHERE_DELETE", "MUT_TAUTOLOGICAL_WHERE",
                "MUT_WRONG_ROW", "MUT_WRONG_TABLE", "MUT_WRONG_COLUMN", "MUT_WRONG_VALUE",
                "MUT_VALUE_SCALING", "MUT_BOUNDARY_OPERATOR", "MUT_WRONG_SUBQUERY_KEY",
                "MUT_WIDENED_PREDICATE_OR", "MUT_UNDER_SCOPED_WRITE", "MUT_INSERT_WRONG_TABLE_OR_VALUES",
                "MUT_HIDDEN_WRITE_CTE", "MUT_OP_VERB_MISMATCH", "MUT_OP_MODALITY_MISMATCH",
                "MUT_MULTI_ROW_BLAST_RADIUS", "MUT_STACKED_SQL", "MUT_UNREQUESTED_DDL_DROP",
                "MUT_UNREQUESTED_DDL_ALTER"
            }
            if any(v in block_families for v in violations):
                decision = "BLOCK"
            else:
                decision = "CONFIRM"
        elif has_unverifiable_write:
            # Fails closed to CONFIRM
            decision = "CONFIRM"
            reasons.append(f"Unverifiable intent fields for write: {unverifiable}")
        else:
            if sql_op == "SELECT":
                decision = "ALLOW"
            elif sql_op == "UPDATE":
                if n_matched > 1 or n_changed > 1:
                    decision = "CONFIRM" # MUT_MULTI_ROW_UPDATE
                else:
                    decision = "ALLOW" # MUT_EXACT_SCOPED_UPDATE
            elif sql_op == "DELETE":
                if n_matched > 1 or n_changed > 1:
                    decision = "CONFIRM" # MUT_MULTI_ROW_DELETE
                else:
                    if variant == "variant_b":
                        decision = "CONFIRM"
                    else:
                        decision = "ALLOW"
            elif sql_op == "INSERT":
                decision = "CONFIRM" # MUT_INTENT_INSERT
            elif sql_op in ("DROP", "ALTER", "CREATE"):
                decision = "CONFIRM" # MUT_BENIGN_DDL
            else:
                decision = "ALLOW"

    return {
        'decision': decision,
        'violations': violations,
        'reasons': reasons,
        'risk_score': risk_score,
        'unverifiable_fields': unverifiable
    }
