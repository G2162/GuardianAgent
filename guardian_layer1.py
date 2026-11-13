"""
guardian_layer1.py
==================
Layer 1: Intent-Free Structural Rules Engine.
Implements:
  L1-1: Missing WHERE clause on UPDATE/DELETE
  L1-2: Tautological or always-true WHERE clauses (simplification, reflexivity, constant folding, OR-widening)
  L1-3: Stacked statements (multiple executable statements)
  L1-4: Unrequested destructive DDL (DROP, TRUNCATE, ALTER)
  L1-5: Hidden writes (writes embedded in CTEs or disguised under read-phrased requests)

All Layer 1 violations produce an immediate BLOCK decision.
"""
import re
import sqlglot
from sqlglot import exp
from sqlglot.optimizer.simplify import simplify

def normalize_ast_sql(node):
    if node is None:
        return ""
    return node.sql(dialect='sqlite').strip().lower()

def is_reflexive(node):
    """Detects reflexive expressions like col = col, f(col) = f(col), col IN (col)."""
    if isinstance(node, exp.EQ):
        return normalize_ast_sql(node.left) == normalize_ast_sql(node.right)
    if isinstance(node, exp.In):
        if len(node.expressions) == 1:
            return normalize_ast_sql(node.this) == normalize_ast_sql(node.expressions[0])
    return False

def is_complementary_pair(left, right):
    """Detects complementary pairs like (x = c OR x != c), (x > c OR x <= c), (P OR NOT P)."""
    l_str = normalize_ast_sql(left)
    r_str = normalize_ast_sql(right)
    
    # P OR NOT P
    if isinstance(right, exp.Not) and normalize_ast_sql(right.this) == l_str:
        return True
    if isinstance(left, exp.Not) and normalize_ast_sql(left.this) == r_str:
        return True
        
    # col IS NULL OR col IS NOT NULL
    if isinstance(left, exp.Is) and isinstance(right, exp.Is):
        if normalize_ast_sql(left.this) == normalize_ast_sql(right.this):
            l_not = isinstance(left.expression, exp.Not)
            r_not = isinstance(right.expression, exp.Not)
            if l_not != r_not:
                return True
                
    # (x = c OR x != c) / (x <> c OR x = c)
    if (isinstance(left, exp.EQ) and isinstance(right, exp.NEQ)) or (isinstance(left, exp.NEQ) and isinstance(right, exp.EQ)):
        if normalize_ast_sql(left.left) == normalize_ast_sql(right.left) and normalize_ast_sql(left.right) == normalize_ast_sql(right.right):
            return True
            
    # (x > c OR x <= c) / (x < c OR x >= c)
    if (isinstance(left, exp.GT) and isinstance(right, exp.LTE)) or (isinstance(left, exp.LTE) and isinstance(right, exp.GT)):
        if normalize_ast_sql(left.left) == normalize_ast_sql(right.left) and normalize_ast_sql(left.right) == normalize_ast_sql(right.right):
            return True
    if (isinstance(left, exp.LT) and isinstance(right, exp.GTE)) or (isinstance(left, exp.GTE) and isinstance(right, exp.LT)):
        if normalize_ast_sql(left.left) == normalize_ast_sql(right.left) and normalize_ast_sql(left.right) == normalize_ast_sql(right.right):
            return True
            
    return False

def eval_constant_expr(node):
    """Safely evaluates purely constant AST expressions (numbers, arithmetic, literals). Returns value or None."""
    if isinstance(node, exp.Literal):
        if node.is_number:
            try:
                val = float(node.this)
                return int(val) if val.is_integer() else val
            except Exception:
                return None
        elif node.is_string:
            return node.this
    elif isinstance(node, exp.Add):
        l, r = eval_constant_expr(node.left), eval_constant_expr(node.right)
        return (l + r) if (l is not None and r is not None) else None
    elif isinstance(node, exp.Sub):
        l, r = eval_constant_expr(node.left), eval_constant_expr(node.right)
        return (l - r) if (l is not None and r is not None) else None
    elif isinstance(node, exp.Mul):
        l, r = eval_constant_expr(node.left), eval_constant_expr(node.right)
        return (l * r) if (l is not None and r is not None) else None
    elif isinstance(node, exp.Div):
        l, r = eval_constant_expr(node.left), eval_constant_expr(node.right)
        return (l / r) if (l is not None and r is not None and r != 0) else None
    elif isinstance(node, exp.Mod):
        l, r = eval_constant_expr(node.left), eval_constant_expr(node.right)
        return (l % r) if (l is not None and r is not None and r != 0) else None
    elif isinstance(node, exp.Neg):
        v = eval_constant_expr(node.this)
        return -v if v is not None else None
    return None

def is_constant_truth(node):
    """Evaluates constant comparisons and membership tests (e.g. 12/3 = 4, 15%4 = 3, 1 IN (1,2,3))."""
    # Check In membership: literal IN (literals...)
    if isinstance(node, exp.In):
        target = eval_constant_expr(node.this)
        if target is not None:
            candidates = [eval_constant_expr(e) for e in node.expressions]
            if all(c is not None for c in candidates) and target in candidates:
                return True

    # Check Between: val BETWEEN low AND high
    if isinstance(node, exp.Between):
        val = eval_constant_expr(node.this)
        low = eval_constant_expr(node.args.get('low'))
        high = eval_constant_expr(node.args.get('high'))
        if val is not None and low is not None and high is not None:
            if low <= val <= high:
                return True

    # Check Binary Comparisons
    if isinstance(node, (exp.EQ, exp.NEQ, exp.GT, exp.GTE, exp.LT, exp.LTE)):
        l = eval_constant_expr(node.left)
        r = eval_constant_expr(node.right)
        if l is not None and r is not None:
            if isinstance(node, exp.EQ) and l == r:
                return True
            if isinstance(node, exp.NEQ) and l != r:
                return True
            if isinstance(node, exp.GT) and l > r:
                return True
            if isinstance(node, exp.GTE) and l >= r:
                return True
            if isinstance(node, exp.LT) and l < r:
                return True
            if isinstance(node, exp.LTE) and l <= r:
                return True
                
    return False

def is_degenerate_function(node):
    """Detects functions and identities whose comparison is intrinsically always true, e.g. LENGTH(x) >= 0, col * 0 = 0."""
    # col * 0 = 0 or 0 * col = 0
    if isinstance(node, exp.EQ):
        if isinstance(node.left, exp.Mul):
            l_val = eval_constant_expr(node.left.right) if eval_constant_expr(node.left.left) is None else eval_constant_expr(node.left.left)
            r_val = eval_constant_expr(node.right)
            if l_val == 0 and r_val == 0:
                return True
        if isinstance(node.right, exp.Mul):
            r_mul_val = eval_constant_expr(node.right.right) if eval_constant_expr(node.right.left) is None else eval_constant_expr(node.right.left)
            l_val = eval_constant_expr(node.left)
            if r_mul_val == 0 and l_val == 0:
                return True

    if isinstance(node, (exp.GTE, exp.GT)):
        left = node.left
        # Length or Abs
        is_len_or_abs = isinstance(left, (exp.Length, exp.Abs))
        if not is_len_or_abs and isinstance(left, exp.Anonymous):
            is_len_or_abs = left.name.upper() in ('LENGTH', 'ABS')
            
        if is_len_or_abs:
            r_val = eval_constant_expr(node.right)
            if r_val is not None:
                if isinstance(node, exp.GTE) and r_val <= 0:
                    return True
                if isinstance(node, exp.GT) and r_val < 0:
                    return True
                    
    if isinstance(node, exp.Like):
        if isinstance(node.expression, exp.Literal) and node.expression.this == '%':
            return True
            
    return False

def is_tautological_where(expr):
    """
    Evaluates whether an expression inside a WHERE clause is tautological
    (evaluates unconditionally to TRUE or is widened by an always-true disjunct).
    Returns (bool, reason).
    """
    if expr is None:
        return True, "None expression"
        
    # 1. Simplification via sqlglot optimizer
    try:
        simp = simplify(expr)
    except Exception:
        simp = expr
        
    if isinstance(simp, exp.Boolean) and simp.this is True:
        return True, f"constant boolean TRUE ({simp})"
    if isinstance(simp, exp.Literal) and simp.this in ('1', 1, 'TRUE', 'true'):
        return True, f"constant numeric 1/TRUE ({simp})"
        
    # 2. Constant truth check (arithmetic folding, comparisons, IN, BETWEEN)
    if is_constant_truth(simp) or is_constant_truth(expr):
        return True, "constant truth evaluation (e.g. arithmetic/comparison/IN/BETWEEN identity)"
        
    # 3. Reflexive equality (col = col, f(col) = f(col))
    if is_reflexive(simp) or is_reflexive(expr):
        return True, "reflexive equality (col = col)"
        
    # 4. Degenerate functions (LENGTH(col) >= 0, col * 0 = 0)
    if is_degenerate_function(simp) or is_degenerate_function(expr):
        return True, "degenerate function identity (e.g. LENGTH >= 0 or col * 0 = 0)"
        
    # 5. Disjunction analysis (OR-widening & Complementary pairs)
    if isinstance(simp, exp.Or):
        l_taut, l_reason = is_tautological_where(simp.left)
        if l_taut:
            return True, f"OR-widened with tautology on left: {l_reason}"
        r_taut, r_reason = is_tautological_where(simp.right)
        if r_taut:
            return True, f"OR-widened with tautology on right: {r_reason}"
        if is_complementary_pair(simp.left, simp.right):
            return True, "complementary disjunction (P OR NOT P)"
            
    if isinstance(expr, exp.Or):
        l_taut, l_reason = is_tautological_where(expr.left)
        if l_taut:
            return True, f"OR-widened with tautology on left: {l_reason}"
        r_taut, r_reason = is_tautological_where(expr.right)
        if r_taut:
            return True, f"OR-widened with tautology on right: {r_reason}"
        if is_complementary_pair(expr.left, expr.right):
            return True, "complementary disjunction (P OR NOT P)"
            
    # 6. Check if any sub-expression inside an OR evaluates to constant truth
    for or_node in simp.find_all(exp.Or):
        if is_complementary_pair(or_node.left, or_node.right):
            return True, "sub-tree complementary disjunction"
        if isinstance(or_node.left, exp.Boolean) and or_node.left.this is True:
            return True, "sub-tree OR-widening"
        if isinstance(or_node.right, exp.Boolean) and or_node.right.this is True:
            return True, "sub-tree OR-widening"
        if is_constant_truth(or_node.left) or is_constant_truth(or_node.right):
            return True, "sub-tree OR-widening with constant truth"
        if is_degenerate_function(or_node.left) or is_degenerate_function(or_node.right):
            return True, "sub-tree OR-widening with degenerate function"
        if is_reflexive(or_node.left) or is_reflexive(or_node.right):
            return True, "sub-tree OR-widening with reflexive identity"

    for or_node in expr.find_all(exp.Or):
        if is_complementary_pair(or_node.left, or_node.right):
            return True, "sub-tree complementary disjunction"
        if is_constant_truth(or_node.left) or is_constant_truth(or_node.right):
            return True, "sub-tree OR-widening with constant truth"
        if is_degenerate_function(or_node.left) or is_degenerate_function(or_node.right):
            return True, "sub-tree OR-widening with degenerate function"
        if is_reflexive(or_node.left) or is_reflexive(or_node.right):
            return True, "sub-tree OR-widening with reflexive identity"

    return False, None

def check_layer1_rules(sql, request="", is_ddl_requested=False):
    """
    Main Layer 1 entrypoint.
    Returns:
      is_violation (bool): True if blocked by Layer 1.
      rule_id (str or None): Name of the rule that fired.
      decision (str or None): "BLOCK" on violation, "CONFIRM" on write parse failure, None if passed.
      is_catastrophic (bool): True if marked catastrophic in labeling policy.
    """
    if not sql or not sql.strip():
        return True, "L1-PARSE-EMPTY", "BLOCK", True
        
    clean_sql = sql.strip().rstrip(';')
    
    try:
        stmts = sqlglot.parse(clean_sql, read='sqlite')
    except Exception as e:
        upper = clean_sql.upper()
        if any(w in upper for w in ('UPDATE', 'DELETE', 'INSERT', 'DROP', 'ALTER', 'CREATE')):
            return True, f"L1-PARSE-FAIL: {e}", "CONFIRM", False
        return True, f"L1-PARSE-FAIL: {e}", "BLOCK", True

    if not stmts:
        return True, "L1-PARSE-EMPTY", "BLOCK", True
        
    # Rule L1-3: Stacked statements
    if len(stmts) > 1:
        return True, "Rule L1-3: Stacked / Multi-Statement SQL detected", "BLOCK", True

    stmt = stmts[0]
    
    # Rule L1-4: Unrequested Destructive DDL
    ddl_nodes = list(stmt.find_all(exp.Drop, exp.Alter))
    is_truncate = "TRUNCATE" in clean_sql.upper()
    if ddl_nodes or is_truncate:
        req_lower = request.lower()
        has_ddl_intent = is_ddl_requested or any(w in req_lower for w in ('drop', 'alter', 'truncate', 'table', 'column', 'schema', 'index', 'view'))
        if not has_ddl_intent:
            return True, "Rule L1-4: Unrequested Destructive DDL (DROP/ALTER/TRUNCATE)", "BLOCK", True
            
    # Rule L1-5: Hidden Writes
    writes = list(stmt.find_all(exp.Update, exp.Delete, exp.Insert))
    has_write = isinstance(stmt, (exp.Update, exp.Delete, exp.Insert)) or bool(writes)
    
    if has_write and request:
        req_lower = request.lower()
        read_starters = ('show', 'list', 'find', 'get', 'select', 'display', 'count', 'what', 'how many', 'report', 'view')
        is_read_intent = any(req_lower.startswith(w) for w in read_starters)
        has_write_verbs = any(w in req_lower for w in ('update', 'delete', 'modify', 'insert', 'change', 'remove', 'add', 'drop', 'set', 'truncate'))
        if is_read_intent and not has_write_verbs:
            return True, "Rule L1-5: Hidden Write operation in read-phrased request", "BLOCK", True

    # Rule L1-1 & L1-2: Missing WHERE and Tautological WHERE for state-modifying queries
    target_writes = []
    if isinstance(stmt, (exp.Update, exp.Delete)):
        target_writes.append(stmt)
    for w in stmt.find_all(exp.Update, exp.Delete):
        if w not in target_writes:
            target_writes.append(w)
            
    for write_stmt in target_writes:
        where = write_stmt.find(exp.Where)
        if where is None or where.this is None:
            return True, "Rule L1-1: Missing WHERE clause on state-modifying query", "BLOCK", True
            
        is_taut, reason = is_tautological_where(where.this)
        if is_taut:
            return True, f"Rule L1-2: Tautological/always-true WHERE clause ({reason})", "BLOCK", True

    return False, None, None, False
