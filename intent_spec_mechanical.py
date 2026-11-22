"""
intent_spec_mechanical.py
=========================
Derives IntentSpecV2 mechanically from the gold SQL (or ground-truth benign SQL)
using sqlglot AST parsing only.
No placeholders or hand-written fields.
"""
from typing import Optional, Dict, Any
import sqlglot
from sqlglot import exp
from intent_spec_v2 import IntentSpecV2

def derive_mechanical_intent(gold_sql_or_sql: str, request: str = "", family_id: str = "") -> IntentSpecV2:
    """
    Parses gold SQL using sqlglot (dialect='sqlite') to produce IntentSpecV2.
    """
    if not gold_sql_or_sql or not gold_sql_or_sql.strip():
        return IntentSpecV2(operation="unknown", unverifiable_fields=["no_sql_provided"])

    clean_sql = gold_sql_or_sql.strip().rstrip(';')

    try:
        tree = sqlglot.parse_one(clean_sql, read='sqlite')
    except Exception as e:
        return IntentSpecV2(operation="unknown", unverifiable_fields=[f"parse_error: {e}"])

    # 1. Operation
    op = "unknown"
    if isinstance(tree, exp.Update):
        op = "UPDATE"
    elif isinstance(tree, exp.Delete):
        op = "DELETE"
    elif isinstance(tree, exp.Insert):
        op = "INSERT"
    elif isinstance(tree, exp.Select):
        op = "SELECT"
    elif isinstance(tree, exp.Drop):
        op = "DROP"
    elif isinstance(tree, exp.Alter):
        op = "ALTER"
    elif isinstance(tree, exp.Create):
        op = "CREATE"
    else:
        upper = clean_sql.upper()
        if upper.startswith("CREATE"):
            op = "CREATE"
        elif upper.startswith("DROP"):
            op = "DROP"
        elif upper.startswith("ALTER"):
            op = "ALTER"

    # 2. Table
    tbl = None
    tbl_node = tree.find(exp.Table)
    if tbl_node:
        tbl = tbl_node.name.strip('"\'').lower()

    # 3. Filter Columns, Where Text, Where Val
    filter_columns = []
    where_text = None
    where_val = None
    where_node = tree.find(exp.Where)
    if where_node:
        where_text = where_node.sql(dialect='sqlite')
        for col in where_node.find_all(exp.Column):
            c_name = col.name.strip('"\'').lower()
            if c_name and c_name not in filter_columns:
                filter_columns.append(c_name)
        for lit in where_node.find_all(exp.Literal):
            where_val = str(lit.this).strip('"\'')

    # 4. SET assignments for UPDATE
    set_assignments = {}
    if isinstance(tree, exp.Update):
        for expr in tree.expressions:
            if isinstance(expr, exp.EQ):
                if isinstance(expr.left, (exp.Column, exp.Identifier)):
                    c_name = expr.left.name.strip('"\'').lower() if hasattr(expr.left, 'name') else str(expr.left).strip('"\'').lower()
                    val_str = expr.right.sql(dialect='sqlite').strip('"\'')
                    set_assignments[c_name] = val_str

    # 5. Insert Values
    insert_values = {}
    if isinstance(tree, exp.Insert):
        cols = [c.name.strip('"\'').lower() for c in tree.find_all(exp.Column)]
        vals = [v.sql(dialect='sqlite').strip('"\'') for v in tree.find_all(exp.Literal)]
        if cols and len(cols) == len(vals):
            insert_values = dict(zip(cols, vals))

    # 6. Expected Cardinality derived mechanically
    cardinality = "unknown"
    if op in ("UPDATE", "DELETE"):
        # Check if family explicitly specifies multi-row
        if 'MULTI_ROW' in family_id:
            cardinality = "multi"
        elif where_node:
            in_nodes = list(where_node.find_all(exp.In))
            has_multi_in = any(len(node.expressions) > 1 for node in in_nodes)
            if has_multi_in:
                cardinality = "multi"
            elif any(c == 'id' or c == 'rowid' or c.endswith('_id') or c.endswith('id') for c in filter_columns) and not has_multi_in:
                # Primary key or ID equality match
                cardinality = "single"
            else:
                req_lower = request.lower() if request else ""
                if any(w in req_lower for w in (' all ', ' every ', ' each ', 'all records', 'every record')):
                    cardinality = "multi"
                elif any(w in req_lower for w in ('single', 'the record', 'one record', 'the row', 'one row')) or 'is 1' in req_lower or 'is 2' in req_lower:
                    cardinality = "single"
                else:
                    cardinality = "unknown"
        else:
            cardinality = "multi"
    elif op == "INSERT":
        cardinality = "single"
    elif op == "SELECT":
        cardinality = "unknown"

    return IntentSpecV2(
        operation=op,
        table=tbl,
        filter_columns=filter_columns,
        where_text=where_text,
        where_val=where_val,
        set_assignments=set_assignments,
        insert_values=insert_values,
        expected_cardinality=cardinality
    )
