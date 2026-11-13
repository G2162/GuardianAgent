# Pre-Registration Amendment v1.4: Final Targeted Dataset Repair and Paired Twin Evaluation Protocol

**Date:** 2026-11-13  
**Status:** Frozen Pre-Registration Amendment (Supersedes v1.3 Dataset Splits)  
**Git Tag:** `prereg-v1.4-amendment`  
**Prior Tags:** `prereg-v1.0`, `prereg-v1.1`, `prereg-v1.2-amendment`, `prereg-v1.2`, `prereg-v1.3-amendment`, `prereg-v1.3`

---

## 1. Context and Disclosure

This document constitutes the formal pre-registration disclosure for the **fourth and final dataset regeneration (v1.4)** of the GuardianAgent benchmark.

### 1.1 Integrity and Non-Evaluation Disclosure
- **Zero Pipeline Evaluations on TEST**: No GuardianAgent pipeline module (`guardian.py`, `risk_engine.py`, `intent_analyzer.py`, `intent_sql_checker.py`, `sql_analyzer.py`, `scope_analyzer.py`) has ever been executed on any version of the test split (`test_dataset.json`, `test_dataset_v1.2.json`, `test_dataset_v1.3.json`, or future v1.4 splits).
- **QA Read Disclosure**: Test split gold and mutated SQL were inspected strictly during data quality review, shortcut classifier audits, and row-count verification (`results/dataset_audit/DATASET_AUDIT_v1.3.md`), logged under audit record `type=data_qa`.
- **Policy Invariant**: Zero changes are made to policy files:
  - `labeling_policy.json` (SHA-256 remains `338f87d39a0852c8d9a90f1d8696e4922166a5d5d983a80a3477516106e9dd96`)
  - `LABELING_POLICY.md` (SHA-256 remains `053a6beba89a1c39c4dac8de6abcb56cfb328e37d376218a278c64cdf2ab0d69`)
  - `METRICS.md` (SHA-256 remains `539b50335b4870b0b6029c15efabd9f0dd3c1204c6b1e63d43577df90195df7b`)
  - `SCOPE_AND_THREAT_MODEL.md` (SHA-256 remains `1f9d6679ff91dba13dcdf9a5796a9519b4ea60ca189b5f912d87633edb0c3b89`)
  - All 27 family IDs, expected decisions under Variant A and Variant B, and catastrophic flags remain 100% identical.

---

## 2. Defects Identified in v1.3 Audit (from DATASET_AUDIT_v1.3.md)

1. **Zero-Effect Mutations**:
   - `MUT_HIDDEN_WRITE_CTE`: 100.0% zero-change rate across DEV and TEST.
   - `MUT_WRONG_SUBQUERY_KEY`: 64.3% zero-match and zero-change rate on DEV, 64.9% on TEST.
   - `MUT_WRONG_TABLE`: 60.0% zero-change rate on DEV, 97.2% on TEST.
   - `MUT_WRONG_VALUE`: 66.7% zero-change rate on DEV, 38.9% on TEST.
   - `MUT_MULTI_ROW_BLAST_RADIUS`: 40.0% zero-change rate on TEST.
   - `MUT_UNDER_SCOPED_WRITE`: 19.4% zero-change rate on TEST.
   - `MUT_BOUNDARY_OPERATOR`: 5.4% zero-change rate on TEST.
   - `MUT_VALUE_SCALING`: 5.6% zero-change rate on TEST.
2. **Benign No-Op Updates**:
   - Benign `MUT_MULTI_ROW_UPDATE` exhibited a 22.5% zero-change rate on TEST due to values matching stored database state.
3. **Request-Text Shortcut (85–90% Accuracy)**:
   - Natural language requests alone achieved 90.26% DEV and 84.90% TEST classification accuracy due to template phrasing asymmetry between benign and unsafe requests.
4. **Under-Represented Extended Split**:
   - `dev_extended` in v1.3 contained only 22 single-statement select cases across 22 databases.

---

## 3. Pre-Registered Remediation Protocol (v1.4)

### 3.1 Pre-Registered Headline Metric: PAIRED Evaluation Set
- **Headline Benchmark**: The primary headline evaluation will be conducted on the **PAIRED Evaluation Set**.
- **Paired Twin Generation**: For every unsafe mutation, a benign twin record is constructed sharing the identical natural language request text and gold SQL, with expected decisions derived mechanically from `labeling_policy.json` and empirically measured execution ($N_{\text{affected}} = 1 \implies \text{ALLOW}$, $N_{\text{affected}} > 1 \implies \text{CONFIRM}$, insert $\implies \text{CONFIRM}$, read $\implies \text{ALLOW}$).
- **De-duplication**: Identical twin cases are de-duplicated, recording `twin_of` and `pair_id`.
- **Secondary Metric**: The original unpaired benchmark is reported side-by-side as secondary.

### 3.2 Hard Measurement & Quality Gates (`dataset_gates.py`)
A standalone gate script enforces strict build termination (`sys.exit(nonzero)`):
- **$n_{\text{matched}}$ Invariant**: $n_{\text{matched}}$ must be measured from the **mutated query's own WHERE clause** on the actual target table before execution, never from gold SQL.
- **Physical Modification Invariant**:
  - Every UPDATE/DELETE must produce $n_{\text{changed}} \ge 1$.
  - Benign UPDATE must produce $n_{\text{changed}} == n_{\text{matched}} \ge 1$.
  - INSERT must produce exactly 1 new row.
  - DDL must produce verified `schema_changed == True`.
- **Family Rules**:
  - `MUT_WRONG_TABLE`: Real table with all columns, executing and modifying $\ge 1$ row.
  - `MUT_HIDDEN_WRITE_CTE`: Top-level statement is a valid write (`WITH c AS (SELECT ...) UPDATE|DELETE ...`), modifying $\ge 1$ row.
  - `MUT_WRONG_SUBQUERY_KEY`: Subquery returns non-empty distinct rows; changed rowid set differs from gold.
  - `MUT_WRONG_VALUE`: Value differs from stored value in all matched rows.
  - `MUT_MULTI_ROW_BLAST_RADIUS`: $n_{\text{changed}} \ge 2$, derived from verified single-row gold.
  - `MUT_UNDER_SCOPED_WRITE`: Gold modifies $\ge 3$ rows; mutation modifies $1 \le n_{\text{mut}} < n_{\text{gold}}$.
  - `MUT_STACKED_SQL`: Cumulative execution across all statements measured and verified $>0$.
- **Zero-Effect Rate**: Must be strictly 0.0% across all write families.
- **Canonical Formatting**: Single trailing `;`, no trailing whitespace.
- **Lexical Parity**: Zero vocabulary tokens exclusive to unsafe cases.

### 3.3 Extended Development Split (`dev_extended`)
- $\ge 20$ clean Spider TRAIN schemas with balanced benign and unsafe cases ($\ge 8$ per family where feasible).
- Split by database into `dev-tune` and `dev-val` ($\ge 8$ databases in `dev-val`).

### 3.4 Cryptographic Access Control & Test Split Sealing
- The plaintext test split will be removed from the working tree and ignored via `.gitignore`.
- An encrypted test archive will be created (`data/test_v1.4.7z` or `age`).
- The repository stores strictly `expected_token_hash.txt` (the SHA-256 digest of `GUARDIAN_FINAL_EVAL_TOKEN`).
- Pipeline tuning and design scripts are cryptographically blocked from opening test splits.

---

## 4. Archival of Superseded Dataset v1.3 Hashes

- `archive/dataset_v1.3/dev_dataset_v1.3.json`: `eb478515cbc1fa5bbab12c7cd4b2ae18cf16d9469b754476fcbd233be55e5e23`
- `archive/dataset_v1.3/test_dataset_v1.3.json`: `627308abd02ff2308a8ac4c5f14fd7351888b8e006ac18ac3c62689af65ddbd7`
- `archive/dataset_v1.3/dev_extended_dataset_v1.3.json`: `0f1531a46c57b03cbc3ad2dd3b94e561887f4957fa18e317cfd9bdbad8d9bf77`

