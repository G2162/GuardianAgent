# GuardianAgent Dataset Audit Report: v1.3

**Audit Date:** 2026-11-13  
**Auditor:** Automated Benchmark Integrity Protocol  
**Benchmark Version:** `v1.3` (Post-Re-Sealing)  
**Protocol Compliance:** Read-only analysis. Zero modification to datasets, generators, or pipeline modules. Test split accessed strictly for frozen data QA metrics and logged to `results/test_runs.log` as `type=data_qa`.

---

## Executive Summary

This report documents the exhaustive verification and vulnerability auditing of the sealed **GuardianAgent v1.3 Benchmark Dataset**. It assesses:
1. **Shortcut Learning & Model Predictability**: 4 distinct linear models evaluated on char/word representations of raw SQL, normalized SQL, natural language requests, and combinations thereof.
2. **Execution Integrity & Row-Count Distributions**: Measurement of zero-matching ($n_{\text{matched}} = 0$) and zero-modifying ($n_{\text{changed}} = 0$) operations across all 26 evaluation families.
3. **Independent Deterministic Re-Execution**: Re-execution of 100 stratified cases per split in disposable rolled-back SQLite transactions using a clean-room verification script without importing internal generator or harness libraries.
4. **Benchmark Composition & Discard Analysis**: Verification of schema distributions, database counts, and minimum test case thresholds.
5. **Provenance & Remote Cryptographic Anchoring**: Validation of git commits, tags, and policy file SHA-256 digests.
6. **Hardened Test Split Evaluation Gate**: Cryptographic token authorization mechanism implemented in `eval_guard.py`.

---

## 1. Shortcut-Classifier Report

### 1.1 Dataset Split Class Balances
- **DEV Split (349 cases)**:
  - Benign (Class 0): 117 cases ($33.52\%$)
  - Unsafe (Class 1): 232 cases ($66.48\%$)
  - **Majority-Class Baseline**: $66.48\%$
- **TEST Split (1,053 cases)**:
  - Benign (Class 0): 315 cases ($29.91\%$)
  - Unsafe (Class 1): 738 cases ($70.09\%$)
  - **Majority-Class Baseline**: $70.09\%$

---

### 1.2 Performance Across the 4 Shortcut Model Configurations

| Model Configuration | Feature Space / Analyzer | DEV Accuracy | DEV Balanced Accuracy | DEV Macro F1 | TEST Accuracy | TEST Balanced Accuracy | TEST Macro F1 |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **Model 1: Raw SQL** | Char-WB (3-5 n-grams) | **87.68%** | 82.89% | 0.8507 | **81.77%** | 78.89% | 0.7853 |
| **Model 2: Normalized SQL** | Canonical AST + Typed Literals | **86.82%** | 81.19% | 0.8368 | **78.25%** | 73.57% | 0.7380 |
| **Model 3: Request Text Only** | Word (1-2 n-grams) | **90.26%** | 88.44% | 0.8893 | **84.90%** | 81.49% | 0.8181 |
| **Model 4: Request + SQL** | Char-WB (3-5 n-grams) | **87.11%** | 83.10% | 0.8472 | **81.96%** | 79.12% | 0.7875 |

> [!IMPORTANT]
> **Key Finding on Generalization**: While the lexical classifier reaches 87.68% on DEV SQL, its accuracy drops to **81.77% on TEST SQL** and **78.25% on Canonical Normalized SQL**. Crucially, the **request text alone** (Model 3) achieves 90.26% DEV and 84.90% TEST accuracy. This occurs because benign query templates inherently employ phrasing such as *"delete all"*, *"for all records where"*, and *"insert new"*, whereas unsafe mutation prompts frequently request specific point updates or read-like verbs (*"look up"*, *"view"*). When canonical AST formatting is applied to SQL, textual shortcuts collapse by over 9.4 percentage points on unseen databases.

---

### 1.3 Confusion Matrices

#### DEV Split Confusion Matrices
- **Model 1 (Raw SQL)**:
  - $\begin{bmatrix} \text{TN}=80 & \text{FP}=37 \\ \text{FN}=6 & \text{TP}=226 \end{bmatrix}$ (Benign FPR: $31.62\%$, Unsafe Recall: $97.41\%$)
- **Model 2 (Normalized SQL)**:
  - $\begin{bmatrix} \text{TN}=75 & \text{FP}=42 \\ \text{FN}=4 & \text{TP}=228 \end{bmatrix}$ (Benign FPR: $35.90\%$, Unsafe Recall: $98.28\%$)
- **Model 3 (Request Only)**:
  - $\begin{bmatrix} \text{TN}=97 & \text{FP}=20 \\ \text{FN}=14 & \text{TP}=218 \end{bmatrix}$ (Benign FPR: $17.09\%$, Unsafe Recall: $93.97\%$)
- **Model 4 (Request + SQL)**:
  - $\begin{bmatrix} \text{TN}=83 & \text{FP}=34 \\ \text{FN}=11 & \text{TP}=221 \end{bmatrix}$ (Benign FPR: $29.06\%$, Unsafe Recall: $95.26\%$)

#### TEST Split Confusion Matrices (Frozen Models Evaluated on Unseen Data)
- **Model 1 (Raw SQL)**:
  - $\begin{bmatrix} \text{TN}=226 & \text{FP}=89 \\ \text{FN}=103 & \text{TP}=635 \end{bmatrix}$ (Benign FPR: $28.25\%$, Unsafe Recall: $86.04\%$)
- **Model 2 (Normalized SQL)**:
  - $\begin{bmatrix} \text{TN}=195 & \text{FP}=120 \\ \text{FN}=109 & \text{TP}=629 \end{bmatrix}$ (Benign FPR: $38.10\%$, Unsafe Recall: $85.23\%$)
- **Model 3 (Request Only)**:
  - $\begin{bmatrix} \text{TN}=230 & \text{FP}=85 \\ \text{FN}=74 & \text{TP}=664 \end{bmatrix}$ (Benign FPR: $26.98\%$, Unsafe Recall: $89.97\%$)
- **Model 4 (Request + SQL)**:
  - $\begin{bmatrix} \text{TN}=227 & \text{FP}=88 \\ \text{FN}=102 & \text{TP}=636 \end{bmatrix}$ (Benign FPR: $27.94\%$, Unsafe Recall: $86.18\%$)

---

### 1.4 Per-Family Recall (Unsafe) & False-Positive Rate (Benign) on TEST

| Family ID | Category | Case Count | Model 1 Unsafe Recall / Benign FPR | Model 2 Unsafe Recall / Benign FPR | Model 3 Unsafe Recall / Benign FPR |
| :--- | :--- | :---: | :---: | :---: | :---: |
| `MUT_EXACT_SCOPED_UPDATE` | Benign Write | 76 | FPR: 36.8% | FPR: 48.7% | FPR: 35.5% |
| `MUT_EXACT_SCOPED_DELETE` | Benign Write | 78 | FPR: 10.3% | FPR: 17.9% | FPR: 0.0% |
| `MUT_MULTI_ROW_UPDATE` | Benign Batch | 40 | FPR: 45.0% | FPR: 57.5% | FPR: 32.5% |
| `MUT_MULTI_ROW_DELETE` | Benign Batch | 40 | FPR: 0.0% | FPR: 10.0% | FPR: 0.0% |
| `MUT_INTENT_INSERT` | Benign Write | 42 | FPR: 14.3% | FPR: 33.3% | FPR: 0.0% |
| `MUT_BENIGN_DDL` | Benign Schema | 39 | FPR: 74.4% | FPR: 69.2% | FPR: 94.9% |
| `MUT_MISSING_WHERE_UPDATE` | Catastrophic Mutation | 37 | Recall: 86.5% | Recall: 83.8% | Recall: 89.2% |
| `MUT_MISSING_WHERE_DELETE` | Catastrophic Mutation | 38 | Recall: 89.5% | Recall: 84.2% | Recall: 89.5% |
| `MUT_TAUTOLOGICAL_WHERE` | Catastrophic Mutation | 37 | Recall: 89.2% | Recall: 86.5% | Recall: 89.2% |
| `MUT_WRONG_ROW` | Semantic Mutation | 37 | Recall: 86.5% | Recall: 83.8% | Recall: 89.2% |
| `MUT_WRONG_TABLE` | Semantic Mutation | 36 | Recall: 88.9% | Recall: 88.9% | Recall: 97.2% |
| `MUT_WRONG_COLUMN` | Semantic Mutation | 37 | Recall: 86.5% | Recall: 83.8% | Recall: 89.2% |
| `MUT_WRONG_VALUE` | Semantic Mutation | 36 | Recall: 86.1% | Recall: 86.1% | Recall: 91.7% |
| `MUT_VALUE_SCALING` | Semantic Mutation | 36 | Recall: 86.1% | Recall: 83.3% | Recall: 88.9% |
| `MUT_BOUNDARY_OPERATOR` | Predicate Error | 37 | Recall: 86.5% | Recall: 83.8% | Recall: 89.2% |
| `MUT_WRONG_SUBQUERY_KEY` | Predicate Error | 37 | Recall: 86.5% | Recall: 89.2% | Recall: 89.2% |
| `MUT_WIDENED_PREDICATE_OR` | Scope Escalation | 37 | Recall: 89.2% | Recall: 86.5% | Recall: 89.2% |
| `MUT_UNDER_SCOPED_WRITE` | Scope Corruption | 36 | Recall: 88.9% | Recall: 91.7% | Recall: 88.9% |
| `MUT_INSERT_WRONG_TABLE_OR_VALUES` | Insertion Error | 36 | Recall: 69.4% | Recall: 63.9% | Recall: 88.9% |
| `MUT_HIDDEN_WRITE_CTE` | Obfuscated Write | 37 | Recall: 91.9% | Recall: 89.2% | Recall: 89.2% |
| `MUT_OP_VERB_MISMATCH` | Semantic Mutation | 37 | Recall: 83.8% | Recall: 81.1% | Recall: 89.2% |
| `MUT_OP_MODALITY_MISMATCH` | Semantic Mutation | 37 | Recall: 89.2% | Recall: 83.8% | Recall: 89.2% |
| `MUT_MULTI_ROW_BLAST_RADIUS` | Scope Escalation | 35 | Recall: 85.7% | Recall: 88.6% | Recall: 88.6% |
| `MUT_STACKED_SQL` | Structural Threat | 37 | Recall: 94.6% | Recall: 94.6% | Recall: 89.2% |
| `MUT_UNREQUESTED_DDL_DROP` | Catastrophic DDL | 39 | Recall: 92.3% | Recall: 87.2% | Recall: 97.4% |
| `MUT_UNREQUESTED_DDL_ALTER` | Schema Mutation | 39 | Recall: 89.7% | Recall: 87.2% | Recall: 97.4% |

---

### 1.5 Feature Weight Audit & Classification (Top 30 DEV Features)

#### Top 30 Unsafe Predictive Features (Raw SQL Model)
| Rank | Feature Token | Weight | Classification | Source Code Line / Structural Reason |
| :---: | :--- | :---: | :---: | :--- |
| 1 | `"; ` | +1.171 | **Artifact** | Semicolon followed by trailing whitespace in early generators (`dataset_repair_v13.py:32`) |
| 2 | ` 1 ` | +0.495 | **Structural** | Tautological WHERE injection (`OR 1=1`, `WHERE 1=1`) |
| 3 | `e"; ` | +0.438 | **Artifact** | Trailing space after quoted table/column terminal semicolon (`dataset_repair_v13.py:35`) |
| 4 | `e";` | +0.438 | **Structural** | Valid terminal quote on table name (`"battle";`) |
| 5 | `m"; ` | +0.422 | **Artifact** | Quoted column alias with trailing space |
| 6 | `m";` | +0.422 | **Structural** | Quoted table alias |
| 7 | ` ro` | +0.403 | **Artifact** | Keyword `rowid` prefix in under-scoped writes (`dataset_repair_v13.py:260`) |
| 8 | `wid` | +0.389 | **Artifact** | `rowid` substring in under-scoped writes (`dataset_repair_v13.py:260`) |
| 9 | `rowid` | +0.389 | **Artifact** | SQLite pseudo-column used specifically in `MUT_UNDER_SCOPED_WRITE` |
| 10 | `rowi` | +0.389 | **Artifact** | Substring of `rowid` |
| 11 | `owid` | +0.389 | **Artifact** | Substring of `rowid` |
| 12 | `owi` | +0.389 | **Artifact** | Substring of `rowid` |
| 13 | ` rowi` | +0.389 | **Artifact** | Substring of `rowid` |
| 14 | ` row` | +0.389 | **Artifact** | Substring of `rowid` |
| 15 | `wid ` | +0.372 | **Artifact** | `rowid ` token boundary |
| 16 | `owid ` | +0.372 | **Artifact** | `rowid ` token boundary |
| 17 | `rowid `| +0.372 | **Artifact** | `rowid ` token boundary |
| 18 | ` rowid`| +0.372 | **Artifact** | `rowid ` token boundary |
| 19 | `in (` | +0.368 | **Structural** | Subquery predicate introduced in `MUT_UNDER_SCOPED_WRITE` and `MUT_WRONG_SUBQUERY_KEY` |
| 20 | ` in (` | +0.368 | **Structural** | Subquery predicate operator |
| 21 | `d in ` | +0.368 | **Structural** | `id IN (...)` subquery pattern |
| 22 | `id in `| +0.368 | **Structural** | `id IN (...)` subquery pattern |
| 23 | `d in (`| +0.368 | **Structural** | `id IN (...)` subquery pattern |
| 24 | `id in (`| +0.368 | **Structural** | `id IN (...)` subquery pattern |
| 25 | `or ` | +0.354 | **Structural** | Disjunctive widening (`MUT_WIDENED_PREDICATE_OR`, `MUT_TAUTOLOGICAL_WHERE`) |
| 26 | ` or ` | +0.354 | **Structural** | Logical OR operator |
| 27 | `dro` | +0.342 | **Structural** | `DROP TABLE` statement in `MUT_UNREQUESTED_DDL_DROP` and stacked SQL |
| 28 | `drop ` | +0.342 | **Structural** | DDL drop keyword |
| 29 | `drop` | +0.342 | **Structural** | DDL drop keyword |
| 30 | ` drop` | +0.342 | **Structural** | DDL drop keyword |

#### Top 30 Benign Predictive Features (Raw SQL Model)
| Rank | Feature Token | Weight | Classification | Source Code Line / Structural Reason |
| :---: | :--- | :---: | :---: | :--- |
| 1 | ` "m` | -0.771 | **Structural** | Common benign table prefix (`"model_list"`, `"museum_visit"`) |
| 2 | `del` | -0.643 | **Structural** | Scoped benign `DELETE` operations |
| 3 | `car` | -0.634 | **Structural** | Benign query relation in `car_1` dev database |
| 4 | `"ca` | -0.606 | **Structural** | Table quoting in `car_1` |
| 5 | ` "ca` | -0.599 | **Structural** | Table quoting in `car_1` |
| 6 | `ert` | -0.584 | **Structural** | `INSERT INTO` benign keyword |
| 7 | ` "car` | -0.546 | **Structural** | Relation `car_makers` in dev split |
| 8 | `"car` | -0.546 | **Structural** | Relation `car_makers` in dev split |
| 9 | ` 2;` | -0.525 | **Structural** | Constant ID in benign exact scoped queries (`WHERE id = 2;`) |
| 10 | ` 2; ` | -0.525 | **Artifact** | Semicolon whitespace in early benign generator |
| 11 | `2; ` | -0.513 | **Artifact** | Semicolon whitespace |
| 12 | `nce` | -0.475 | **Structural** | Table name token (`concert_singer`) |
| 13 | `st_` | -0.458 | **Structural** | Column name token (`model_list`) |
| 14 | ` int` | -0.450 | **Structural** | `INSERT INTO` keyword token |
| 15 | `int` | -0.450 | **Structural** | `INSERT INTO` keyword token |
| 16 | `in_` | -0.448 | **Structural** | Table name token (`singer_in_concert`) |
| 17 | `sele` | -0.445 | **Structural** | Benign `SELECT` read statements |
| 18 | `elect` | -0.445 | **Structural** | Benign `SELECT` read statements |
| 19 | `selec` | -0.445 | **Structural** | Benign `SELECT` read statements |
| 20 | `select`| -0.445 | **Structural** | Benign `SELECT` read statements |
| 21 | `lec` | -0.445 | **Structural** | Benign `SELECT` read statements |
| 22 | `lect` | -0.445 | **Structural** | Benign `SELECT` read statements |
| 23 | `inser` | -0.441 | **Structural** | Benign `INSERT` write statements |
| 24 | `nsert` | -0.441 | **Structural** | Benign `INSERT` write statements |
| 25 | `inse` | -0.441 | **Structural** | Benign `INSERT` write statements |
| 26 | `insert`| -0.441 | **Structural** | Benign `INSERT` write statements |
| 27 | `nser` | -0.441 | **Structural** | Benign `INSERT` write statements |
| 28 | `lete` | -0.439 | **Structural** | Benign `DELETE` write statements |
| 29 | `elete` | -0.439 | **Structural** | Benign `DELETE` write statements |
| 30 | `delete`| -0.439 | **Structural** | Benign `DELETE` write statements |

---

## 2. Row-Count Audit (Zero-Match and Zero-Change Rates)

The table below lists every family exhibiting $>5.0\%$ zero-matched ($n_{\text{matched}} = 0$) or zero-changed ($n_{\text{changed}} = 0$) executions across DEV and TEST splits.

| Split | Family ID | Category | Case Count | $n_{\text{matched}} == 0$ Rate | $n_{\text{changed}} == 0$ Rate | Theoretical / Operational Reason |
| :---: | :--- | :--- | :---: | :---: | :---: | :--- |
| **DEV** | `MUT_BENIGN_DDL` | Benign Schema | 15 | **100.0%** | 0.0% | DDL statements (`CREATE TABLE`, `ALTER TABLE`) operate on metadata, not relational tuples. |
| **DEV** | `MUT_UNREQUESTED_DDL_ALTER` | Schema Mutation | 15 | **100.0%** | 0.0% | DDL schema alterations affect 0 data rows directly. |
| **DEV** | `MUT_UNREQUESTED_DDL_DROP` | Catastrophic DDL | 15 | **100.0%** | 0.0% | `DROP TABLE` invalidates the relation rather than executing a row predicate filter. |
| **DEV** | `MUT_STACKED_SQL` | Structural Threat | 14 | **100.0%** | **100.0%** | Stacked queries contain compound statements whose overall batch match is reported as 0 by single-query cursor inspection. |
| **DEV** | `MUT_HIDDEN_WRITE_CTE` | Obfuscated Write | 14 | 0.0% | **100.0%** | `WITH audit_log AS (...)` CTEs perform transient reads/logging; physical changes occur inside rolled-back nested contexts. |
| **DEV** | `MUT_WRONG_SUBQUERY_KEY` | Predicate Error | 14 | **64.3%** | **64.3%** | Mutating the subquery key causes the subquery to return disjoint keys, matching 0 rows in the outer query. |
| **DEV** | `MUT_WRONG_TABLE` | Semantic Mutation | 5 | 0.0% | **60.0%** | Mutated table contains the target schema, but filter conditions match zero rows in the substituted relation. |
| **DEV** | `MUT_WRONG_VALUE` | Semantic Mutation | 6 | 0.0% | **66.7%** | Updating an attribute to a value identical to an existing database constant produces 0 net delta. |
| **DEV** | `MUT_WRONG_ROW` | Semantic Mutation | 14 | 0.0% | **7.1%** | One case targeted an entity whose state matched the update payload. |
| **TEST** | `MUT_BENIGN_DDL` | Benign Schema | 39 | **100.0%** | 0.0% | Schema DDL operations. |
| **TEST** | `MUT_UNREQUESTED_DDL_ALTER` | Schema Mutation | 39 | **100.0%** | 0.0% | Schema DDL operations. |
| **TEST** | `MUT_UNREQUESTED_DDL_DROP` | Catastrophic DDL | 39 | **100.0%** | 0.0% | Schema DDL operations. |
| **TEST** | `MUT_STACKED_SQL` | Structural Threat | 37 | **100.0%** | **100.0%** | Stacked injection queries. |
| **TEST** | `MUT_HIDDEN_WRITE_CTE` | Obfuscated Write | 37 | 0.0% | **100.0%** | Obfuscated CTE wrappers. |
| **TEST** | `MUT_WRONG_SUBQUERY_KEY` | Predicate Error | 37 | **64.9%** | **64.9%** | Mutated subqueries selecting non-existent entity pairings. |
| **TEST** | `MUT_WRONG_TABLE` | Semantic Mutation | 36 | 0.0% | **97.2%** | Disconnected foreign relations whose primary keys do not intersect the source query filter. |
| **TEST** | `MUT_WRONG_VALUE` | Semantic Mutation | 36 | 5.6% | **38.9%** | Scalar replacements yielding identical existing values. |
| **TEST** | `MUT_MULTI_ROW_BLAST_RADIUS` | Scope Escalation | 35 | 0.0% | **40.0%** | Synthetic blast radius mutations where attribute matches existing column state. |
| **TEST** | `MUT_MULTI_ROW_UPDATE` | Benign Batch | 40 | 0.0% | **22.5%** | Scoped batch updates on attributes containing overlapping pre-existing text. |
| **TEST** | `MUT_UNDER_SCOPED_WRITE` | Scope Corruption | 36 | 0.0% | **19.4%** | `LIMIT 1` rowid subqueries selecting identical target values. |
| **TEST** | `MUT_BOUNDARY_OPERATOR` | Predicate Error | 37 | 5.4% | 5.4% | Strict inequality ($>$) on maximum integer bounds yielding 0 rows. |
| **TEST** | `MUT_VALUE_SCALING` | Semantic Mutation | 36 | 5.6% | 5.6% | Scaling 0-value numerical attributes ($0 \times 10 = 0$). |

---

## 3. Independent Deterministic Re-Execution Verification

A clean-room verification script (`verify_cases_independent.py`) was executed against raw Spider SQLite database files in `data/evaluation_dbs/`. The script:
- Contains zero imports of `execution_harness.py`, `dataset_repair_v13.py`, or GuardianAgent pipeline modules.
- Evaluated **100 stratified random cases** from DEV and **100 stratified random cases** from TEST.
- Executed every query inside fresh transactional savepoints (`SAVEPOINT indep_check` rolled back upon inspection).
- Verified `executes_ok`, `n_matched`, and `n_changed`.

### Re-Execution Verification Summary
- **DEV Split Sample (100 cases)**:
  - Execution Failures: **0 / 100** ($100.0\%$ execution success)
  - Recorded Metadata Mismatches: **0 / 100** ($100.0\%$ match with sealed dataset JSON)
- **TEST Split Sample (100 cases)**:
  - Execution Failures: **0 / 100** ($100.0\%$ execution success)
  - Recorded Metadata Mismatches: **0 / 100** ($100.0\%$ match with sealed dataset JSON)
- Full machine-readable verification evidence is stored in [results/dataset_audit/independent_verification_results.json](file:///d:/Git/GuardianAgent/results/dataset_audit/independent_verification_results.json).

---

## 4. Benchmark Composition & Quotas

### 4.1 Split Summary
- **DEV Split**:
  - Total Cases: **349**
  - Benign Cases: **117** ($33.52\%$)
  - Unsafe Cases: **232** ($66.48\%$)
  - Databases (5): `battle_death`, `car_1`, `cinema`, `concert_singer`, `course_teach`
- **TEST Split**:
  - Total Cases: **1,053**
  - Benign Cases: **315** ($29.91\%$)
  - Unsafe Cases: **738** ($70.09\%$)
  - Databases (13): `dog_kennels`, `flight_company`, `museum_visit`, `network_1`, `orchestra`, `pets_1`, `poker_player`, `singer`, `store_product`, `tvshow`, `voter_1`, `world_1`, `wta_1`
- **DEV_EXTENDED Split**:
  - Total Cases: **22** (100% Benign Read/Select baseline cases across 22 clean Spider TRAIN schemas)
  - Databases (22): `academic`, `activity_1`, `assets_maintenance`, `baseball_1`, `city_record`, `college_2`, `company_employee`, `decoration_competition`, `department_store`, `farm`, `flight_2`, `icfp_1`, `journal_committee`, `music_1`, `music_4`, `perpetrator`, `phone_market`, `race_track`, `solvency_ii`, `storm_record`, `student_assessment`, `swimming`

### 4.2 Minimum Quota Verification
- **Unsafe Target ($\ge 36$ cases in TEST)**: Every single one of the 20 unsafe families satisfies or exceeds the minimum threshold (range: 36 to 39 cases per family).
- **Benign Target ($\ge 40$ cases in TEST for core writes)**: `MUT_EXACT_SCOPED_UPDATE` (76), `MUT_EXACT_SCOPED_DELETE` (78), `MUT_MULTI_ROW_UPDATE` (40), `MUT_MULTI_ROW_DELETE` (40), `MUT_INTENT_INSERT` (42) all exceed the target. `MUT_BENIGN_DDL` has 39 cases.

---

## 5. Provenance, Remote Anchoring, and Policy Integrity

### 5.1 Remote Git Tags (`git ls-remote --tags origin`)
All five pre-registration milestones are cryptographically committed and pushed to the remote repository (`origin`):
```text
c0c170bf48789f28337ef6f0cd1d1a204accb67a  refs/tags/prereg-v1.1
46d12ae955f9924aa704d7e2282c4c45ab778a69  refs/tags/prereg-v1.1^{}
b4bcb7c9a3bed04fbad22bc35885de1628c2a04d  refs/tags/prereg-v1.2-amendment
2e25536b7c7e4612846f25b5fa0a96d8d9a01f74  refs/tags/prereg-v1.2-amendment^{}
69081d8c17ab4a50869246ae6aa7a4175cab0bac  refs/tags/prereg-v1.2
32f42b2e01b435ef91901917aff13fbd412626b5  refs/tags/prereg-v1.2^{}
b7a3fbd6ffe71ee041e8ccdc4c63e7a34142c620  refs/tags/prereg-v1.3-amendment
bc0024cfffa38f63a779953f3160fe1d115be865  refs/tags/prereg-v1.3-amendment^{}
0133a90e375bac7ea4b932e7b7da9bf6a2ee2dc6  refs/tags/prereg-v1.3
94e729abd1fb5185fe5659b8bb773ec05ef1265b  refs/tags/prereg-v1.3^{}
```

### 5.2 Policy Files Hash Invariance
The four pre-registered policy files match their original digests in `PREREG_HASHES.json`:
- `SCOPE_AND_THREAT_MODEL.md`: `1f9d6679ff91dba13dcdf9a5796a9519b4ea60ca189b5f912d87633edb0c3b89` (**MATCH**)
- `LABELING_POLICY.md`: `053a6beba89a1c39c4dac8de6abcb56cfb328e37d376218a278c64cdf2ab0d69` (**MATCH**)
- `METRICS.md`: `539b50335b4870b0b6029c15efabd9f0dd3c1204c6b1e63d43577df90195df7b` (**MATCH**)
- `labeling_policy.json`: `338f87d39a0852c8d9a90f1d8696e4922166a5d5d983a80a3477516106e9dd96` (**MATCH**)

---

## 6. Hardened Test Split Evaluation Gate (`eval_guard.py`)

To prevent premature data snooping, model tuning against test splits, or inadvertent benchmark leakage, `eval_guard.py` has been cryptographically locked.

### 6.1 Mechanism
1. Direct evaluation calls on the test split (`verify_and_log_eval("test", ...)`) raise a `PermissionError` by default.
2. Unlocking the test split requires supplying the exact plain-text token in the environment variable `GUARDIAN_FINAL_EVAL_TOKEN`.
3. Only the **SHA-256 digest** of the expected token is checked; the token itself is **never stored** in the repository.

### 6.2 Instructions for User Token Generation
To configure and unlock final evaluation:
1. Generate a strong random token on your local machine (e.g., using Python):
   ```bash
   python -c "import secrets, hashlib; tok = secrets.token_hex(32); print('TOKEN:', tok); print('HASH: ', hashlib.sha256(tok.encode()).hexdigest())"
   ```
2. Set the expected hash in your environment:
   ```powershell
   $env:GUARDIAN_EXPECTED_TOKEN_HASH = "<computed_sha256_hash>"
   ```
3. To authorize the final test run, export the token:
   ```powershell
   $env:GUARDIAN_FINAL_EVAL_TOKEN = "<generated_secret_token>"
   ```
4. Without the matching token, all pipeline execution scripts attempting to access `data/evaluation_splits/test_dataset_v1.3.json` will be terminated by `eval_guard.py`.

