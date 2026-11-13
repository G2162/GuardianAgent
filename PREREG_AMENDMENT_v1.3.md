# Pre-Registration Amendment v1.3: Dataset Quality Defects Remediation and Execution Verification Protocol

**Date:** 2026-11-13  
**Status:** Frozen Pre-Registration Amendment (Supersedes v1.2 Dataset Splits)  
**Git Tag:** `prereg-v1.3-amendment`  
**Prior Tags:** `prereg-v1.0`, `prereg-v1.1`, `prereg-v1.2-amendment`, `prereg-v1.2`

---

## 1. Context and Disclosure

This document constitutes the formal disclosure and pre-registration amendment for the **second dataset regeneration (v1.3)** of the GuardianAgent benchmark.

### 1.1 Integrity and Non-Evaluation Disclosure
- **Zero Pipeline Evaluation Runs on TEST**: As recorded in `results/test_runs.log`, no GuardianAgent pipeline module (`guardian.py`, `risk_engine.py`, `intent_analyzer.py`, `intent_sql_checker.py`, `sql_analyzer.py`, `scope_analyzer.py`) has ever been executed on any version of the test split (`test_dataset.json`, `test_dataset_v1.2.json`, or future v1.3 splits).
- **QA Read Disclosure**: Test split gold and mutated SQL were inspected strictly during data quality review and human auditing (`review_sheet_v1.2.csv`), logged under audit record `type=data_qa`.
- **Policy Invariant**: Zero changes are made to policy files:
  - `labeling_policy.json` (SHA-256 remains `338f87d39a0852c8d9a90f1d8696e4922166a5d5d983a80a3477516106e9dd96`)
  - `LABELING_POLICY.md` (SHA-256 remains `053a6beba89a1c39c4dac8de6abcb56cfb328e37d376218a278c64cdf2ab0d69`)
  - `METRICS.md` (SHA-256 remains `539b50335b4870b0b6029c15efabd9f0dd3c1204c6b1e63d43577df90195df7b`)
  - `SCOPE_AND_THREAT_MODEL.md` (SHA-256 remains `1f9d6679ff91dba13dcdf9a5796a9519b4ea60ca189b5f912d87633edb0c3b89`)
  - All 27 family IDs, their respective category assignments, expected decisions under Variant A and Variant B, and catastrophic flags remain 100% identical.

---

## 2. Defects Identified in v1.2 Dataset Audit

Human review of `review_sheet_v1.2.csv` and automated AST/execution analysis identified seven critical generator flaws requiring this remediation:

1. **Non-Executable Statements & Dialect Mismatch**:
   - PostgreSQL-specific constructs (such as `WITH ... UPDATE` without proper SQLite CTE formatting) and `UPDATE ... LIMIT` statements failing on SQLite engines compiled without `SQLITE_ENABLE_UPDATE_DELETE_LIMIT`.
   - Trailing double semicolons (`;;`) in verb mismatch cases.
2. **Fabricated Gold Queries in Blast-Radius Family**:
   - `MUT_MULTI_ROW_BLAST_RADIUS` previously used dummy/fake single-row queries (e.g., `id = 101` where table max was 8) rather than grounded, empirically verified single-row updates.
3. **Zero-Row Leakage and Semantic Invalidation**:
   - Constant mutations such as `WHERE id = 1000` in `MUT_WRONG_ROW` matching 0 rows, which creates an execution artifact and leaks safety status via `n_matched == 0`.
4. **Generator Token Signatures**:
   - Predictable literal tokens (e.g., `'UPDATED'`, `'V12_UPDATED'`, `'Battle of Adrianople_upd'`) enabling trivial lexical/shortcut classifier separation between benign and unsafe classes without semantic analysis.
5. **String-Replacement Bugs in `MUT_WRONG_VALUE`**:
   - Inadvertent substring replacement corrupting SQL syntax or replacing values with arbitrary sentinel strings.
6. **Unverified Equivalence and Non-Discriminating Mutations**:
   - `MUT_BOUNDARY_OPERATOR` and `MUT_WRONG_SUBQUERY_KEY` instances where mutated SQL matched the exact same rows as the gold SQL.
7. **Type-Incompatible Perturbations**:
   - Attempting to update integer or foreign key columns with arbitrary strings, or mutating columns used directly in the `WHERE` clause filter.

---

## 3. Protocol for Dataset v1.3 Regeneration

### 3.1 Unified Execution Verification Harness
- **Target Engine**: SQLite (exact dialect).
- **Execution Invariant**: Every single case (both benign and unsafe) must execute against an isolated transactional copy of its target database.
- **Verification Metrics Recorded**:
  - `executes_ok`: Boolean indicating query executed without SQLite engine error.
  - `error_message`: Full error string if execution failed.
  - `n_matched`: Number of rows matched by the target table predicate before mutation.
  - `n_changed`: Number of physical rows modified, computed via full table snapshot diff before and after execution.
  - `schema_changed`: Flag indicating table schema alteration.
- **Discard Policy**: Discard any candidate SQL that fails to execute cleanly (except `MUT_STACKED_SQL` which executes each constituent statement independently, and `DROP`/`ALTER` which must execute on disposable clones).

### 3.2 Specific Family Generator Specifications
- **`MUT_BOUNDARY_OPERATOR`**: Add benign queries with numeric/range predicates (`<`, `>`, `<=`, `>=`). Mutate comparison operators in `WHERE` only. Verify $n_{\text{changed, mut}} \neq n_{\text{changed, gold}}$. Never touch the `SET` clause.
- **`MUT_WRONG_VALUE`**: Select valid values from the column's existing database values or type-consistent scalar shifts. No sentinel tokens.
- **`MUT_VALUE_SCALING`**: Numerical columns only, single `SET` clause, scaling by factors of $10\times$ or $100\times$.
- **`MUT_WRONG_TABLE` / `MUT_INSERT_WRONG_TABLE_OR_VALUES`**: Only substitute tables that contain all referenced column names and pass execution checks. 50% wrong table, 50% wrong values for INSERT.
- **`MUT_WRONG_ROW`**: Select existing, alternate primary key / identifier values where $n_{\text{matched}} \ge 1$.
- **`MUT_WRONG_SUBQUERY_KEY`**: Synthesize valid SQL subqueries against real relations that execute and modify distinct row sets.
- **`MUT_MULTI_ROW_BLAST_RADIUS`**: Ground strictly on verified single-row benign cases. Replace single-row predicate with an existing non-unique attribute matching $\ge 2$ rows.
- **`MUT_UNDER_SCOPED_WRITE`**: Base query must match $\ge 3$ rows; mutation must match $1 \le n_{\text{mut}} < n_{\text{gold}}$ using SQLite-supported syntax: `WHERE rowid IN (SELECT rowid FROM <table> WHERE <predicate> LIMIT <k>)`.
- **`MUT_HIDDEN_WRITE_CTE`**: Restrict to SQLite-compliant syntax (`WITH ...`, `RETURNING`, `INSERT INTO ... SELECT`).
- **Statement Normalization**: Enforce single terminal semicolon (`;`) across all families except stacked queries.
- **`MUT_WRONG_COLUMN`**: Mutate `SET` target to an existing, non-PK column distinct from the `WHERE` clause column.
- **Benign Integrity**: Ensure NL requests match DDL operations exactly (`TEMP` vs permanent). Type compatibility strictly enforced across all benign writes.

### 3.3 Leakage, Shortcut, and Collision Audits
- **Vocabulary Audit**: Ensure zero indicator tokens (`'UPDATED'`, `'wrong_'`, `'CONTRADICTORY'`) partition unsafe from benign cases.
- **Row-Count Distribution**: Ensure no unsafe family exceeds 20% zero-row matches.
- **Shortcut Classifier**: Train a character $n$-gram logistic regression on DEV SQL strings. Verify classification accuracy does not exceed 85%.
- **Cross-Family Collision Guard**: Ensure 0 collisions across distinct mutation families.

---

## 4. Archival of Superseded Dataset v1.2 Hashes

The hashes of the superseded v1.2 files are preserved here:
- `archive/dataset_v1.2/dev_dataset_v1.2.json`: `bb537ede40a93d0f2a1865c49947c51919142aa6dec86ca8a905577880204a6f`
- `archive/dataset_v1.2/test_dataset_v1.2.json`: `44e35b7a13be6585b1540e1b5edf40044be324f62d74fe4cd9a3fe0b1cf401f3`

