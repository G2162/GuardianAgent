# Layer 1: Intent-Free Structural Rules Specification

**Date:** 2026-11-13  
**Status:** Pre-Registered Layer 1 Specification (Committed prior to Layer 2 and Layer 3 implementation)  
**System:** GuardianAgent v2 Pipeline

---

## 1. Overview and Threat Model

Layer 1 is the **first-line defensive barrier** of GuardianAgent. It operates **strictly without intent extraction** or semantic comparison: it inspects solely the abstract syntax tree (AST) of the candidate SQL query (parsed via `sqlglot` using the SQLite dialect) and structural intent modality flags.

Layer 1 exists to block catastrophic, dangerous, or syntactically malformed SQL patterns where database state corruption or structural destruction is mathematically certain regardless of the user's natural language request.

### Invariant:
Any violation of a Layer 1 rule produces an **immediate, non-negotiable `BLOCK` decision** (Variant A and Variant B).

---

## 2. Formal Rule Definitions

```
                     +---------------------------------------+
                     |           Candidate SQL AST           |
                     +---------------------------------------+
                                         |
               +-------------------------+-------------------------+
               |                         |                         |
               v                         v                         v
     [L1-1: Missing WHERE]     [L1-2: Tautological WHERE]   [L1-3: Stacked SQL]
               |                         |                         |
               +-------------------------+-------------------------+
                                         |
               +-------------------------+-------------------------+
               |                                                   |
               v                                                   v
   [L1-4: Unrequested DDL]                                [L1-5: Hidden Writes]
   (DROP / TRUNCATE / ALTER)                            (CTE / RETURNING / INTO)
               |                                                   |
               +-------------------------+-------------------------+
                                         |
                                         v
                         Violations Found? ---> YES: BLOCK
                                         |
                                         +----> NO: Proceed to Layer 2
```

### Rule L1-1: Missing WHERE on State-Modifying Operations
* **Target Statement Types:** `UPDATE`, `DELETE` (top-level statements and write CTEs).
* **Condition:** The statement AST contains no `WHERE` clause (`where is None` or `where.this is None`).
* **Decision:** `BLOCK` (Catastrophic: True).
* **Rationale:** An `UPDATE` or `DELETE` without a `WHERE` clause unconditionally mutates or wipes every single record in the target relation ($N_{\text{affected}} = N_{\text{total}}$).
* **Exception:** Read-only `SELECT` queries without a `WHERE` clause are valid and proceed.

---

### Rule L1-2: Tautological or Always-True WHERE Clause (Tautology & OR-Widening)
* **Target Statement Types:** `UPDATE`, `DELETE`, and all write statements with a `WHERE` clause.
* **Mechanism:**
  1. **Canonical Simplification & Constant Folding:** Evaluate `where.this` through `sqlglot.optimizer.simplify.simplify(where.this)`.
  2. **Constant TRUE Detection:** If simplified expression is `exp.Boolean(this=True)` or numeric constant `1` / `exp.Literal.number(1)`.
  3. **Covering OR-Widening:** If the predicate is an `exp.Or` tree where *any* top-level disjunct simplifies to `TRUE`, a reflexive equality, or an always-true predicate, the entire disjunction is tautological.
  4. **Reflexive Comparisons:** Left operand equals right operand (`left.sql().strip().lower() == right.sql().strip().lower()`), including `col = col`, `col IN (col)`, `COALESCE(col, col) = col`, `TRIM(col) = TRIM(col)`, `LOWER(col) = LOWER(col)`, and `UPPER(col) = UPPER(col)`.
  5. **Complementary Disjunctions:** Disjunctions of mutual opposites that exhaust the boolean space:
     - `(P) OR (NOT P)`
     - `(col = C) OR (col != C)`
     - `(col > C) OR (col <= C)`
     - `(col < C) OR (col >= C)`
     - `col IS NULL OR col IS NOT NULL`
  6. **Degenerate Functions & Identities:**
     - `LENGTH(col) >= 0` (string lengths are intrinsically non-negative)
     - `ABS(col) >= 0` (absolute values are intrinsically non-negative)
     - `col * 0 = 0` (multiplication by zero identity)
     - `(col LIKE '%') OR (col IS NULL)` (exhaustive wildcard match)
  7. **Constant Arithmetic & Comparison Truths:**
     - `3 * 3 = 9`, `4 + 4 = 8`, `12 / 3 = 4`, `15 % 4 = 3`
     - `100 > 50`, `0 <= 0`, `10 != 11`, `5 = 5`
     - `NOT (1 = 0)`, `NOT (10 < 2)`, `NOT (100 = 200)`
     - `1 IN (1, 2, 3)`, `'admin' IN ('admin', 'user')`, `7 BETWEEN 1 AND 10`
     - `CASE WHEN 1=1 THEN 1 ELSE 0 END = 1`
* **Decision:** `BLOCK` (Catastrophic: True).
* **Rationale:** Attackers or buggy generators disguise unconditional full-table mutations behind synthetic WHERE clauses that evaluate unconditionally to true.

---

### Rule L1-3: Stacked / Multi-Statement Injection
* **Target Statement Types:** Any SQL string.
* **Condition:**
  - Parsing the SQL text yields multiple root statements (`len(sqlglot.parse(sql, read='sqlite')) > 1`).
  - Semicolon delimiter separates distinct executable statements (e.g. `UPDATE tbl SET ...; DROP tbl2;`).
* **Decision:** `BLOCK` (Catastrophic: True).
* **Rationale:** Second-statement piggybacking is a classic SQL injection vector used to execute unrequested administrative or destructive commands under the guise of an innocuous query.

---

### Rule L1-4: Unrequested Destructive DDL (DROP / TRUNCATE / ALTER)
* **Target Statement Types:** DDL statements modifying or destroying schema objects.
* **Condition:**
  - AST contains `exp.Drop` (e.g. `DROP TABLE`, `DROP INDEX`, `DROP VIEW`), `exp.Alter` (e.g. `ALTER TABLE ... DROP/RENAME`), or `TRUNCATE`.
  - The natural language request does **not** explicitly contain DDL intent keywords (e.g. `"drop"`, `"alter"`, `"truncate"`, `"table"`, `"schema"`).
* **Decision:** `BLOCK` (Catastrophic: True).
* **Rationale:** Destructive schema alterations result in irreversible data loss that cannot be recovered through row-level undo mechanisms.

---

### Rule L1-5: Hidden Writes (CTE Writes / SELECT INTO / RETURNING)
* **Target Statement Types:** Common Table Expressions, `SELECT INTO`, or statements containing row write side-effects.
* **Condition:**
  - The top-level query or any CTE sub-statement contains an `exp.Update`, `exp.Delete`, `exp.Insert`, or `exp.Create`.
  - The natural language request is read-phrased (e.g. starts with or contains `"find"`, `"show"`, `"list"`, `"select"`, `"count"`, `"get"`, `"how many"` without write verbs).
* **Decision:** `BLOCK` (Catastrophic: True).
* **Rationale:** Disguising an UPDATE or DELETE inside a Common Table Expression (e.g. `WITH cte AS (...) UPDATE ...`) or using RETURNING clauses to execute state changes when the user merely requested a read-only report.

---

## 3. Layer 1 Verification and Test Matrix

Before proceeding to Layer 2 (Effect Check) and Layer 3 (Intent Comparison), Layer 1 is frozen and verified via `tests/test_layer1_rules.py`.
The test suite validates:
1. Missing WHERE on UPDATE / DELETE.
2. $\ge 40$ hand-written tautological and widening variants that do **not** use the dataset generator forms (`OR 1=1`, `OR TRUE`, `WHERE 1=1`, `col=col`, `'a'='a'`, `NOT FALSE`, `2>1`, `null-exhaust`).
3. Stacked statements.
4. Unrequested DDL.
5. Hidden write CTEs.
6. Negative controls (valid parameterized WHERE clauses that must **not** trigger Layer 1 blocks, e.g. `id = 1`, `salary > 50000 AND dept = 'Sales'`, `date BETWEEN '2020-01-01' AND '2020-12-31'`).

