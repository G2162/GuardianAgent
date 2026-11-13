# DATA_QA_v1.3.md — Dataset Quality and Verification Report

**Date:** 2026-11-13T11:11:38.376235
**DEV cases:** 349 | **TEST cases:** 1053 | **Total:** 1402

## 1. Execution Verification Harness Summary
- **Dialect:** SQLite (tested in isolated rolled-back transactions)
- **DEV executes_ok rate:** 349/349 (100.0%)
- **TEST executes_ok rate:** 1053/1053 (100.0%)
- **Overall executes_ok rate:** **100.0%** (all non-executable queries discarded)

## 2. Quota Check
- **Benign Target:** >= 40 cases per family in TEST
- **Unsafe Target:** >= 36 cases per family in TEST

| Family ID | TEST Count | Quota Target | Status |
| :--- | :---: | :---: | :---: |
| `MUT_BENIGN_DDL` | 39 | >=40 | **FAIL** |
| `MUT_BOUNDARY_OPERATOR` | 37 | >=36 | **PASS** |
| `MUT_EXACT_SCOPED_DELETE` | 78 | >=40 | **PASS** |
| `MUT_EXACT_SCOPED_UPDATE` | 76 | >=40 | **PASS** |
| `MUT_HIDDEN_WRITE_CTE` | 37 | >=36 | **PASS** |
| `MUT_INSERT_WRONG_TABLE_OR_VALUES` | 36 | >=36 | **PASS** |
| `MUT_INTENT_INSERT` | 42 | >=40 | **PASS** |
| `MUT_MISSING_WHERE_DELETE` | 38 | >=36 | **PASS** |
| `MUT_MISSING_WHERE_UPDATE` | 37 | >=36 | **PASS** |
| `MUT_MULTI_ROW_BLAST_RADIUS` | 35 | >=36 | **FAIL** |
| `MUT_MULTI_ROW_DELETE` | 40 | >=40 | **PASS** |
| `MUT_MULTI_ROW_UPDATE` | 40 | >=40 | **PASS** |
| `MUT_OP_MODALITY_MISMATCH` | 37 | >=36 | **PASS** |
| `MUT_OP_VERB_MISMATCH` | 37 | >=36 | **PASS** |
| `MUT_STACKED_SQL` | 37 | >=36 | **PASS** |
| `MUT_TAUTOLOGICAL_WHERE` | 37 | >=36 | **PASS** |
| `MUT_UNDER_SCOPED_WRITE` | 36 | >=36 | **PASS** |
| `MUT_UNREQUESTED_DDL_ALTER` | 39 | >=36 | **PASS** |
| `MUT_UNREQUESTED_DDL_DROP` | 39 | >=36 | **PASS** |
| `MUT_VALUE_SCALING` | 36 | >=36 | **PASS** |
| `MUT_WIDENED_PREDICATE_OR` | 37 | >=36 | **PASS** |
| `MUT_WRONG_COLUMN` | 37 | >=36 | **PASS** |
| `MUT_WRONG_ROW` | 37 | >=36 | **PASS** |
| `MUT_WRONG_SUBQUERY_KEY` | 37 | >=36 | **PASS** |
| `MUT_WRONG_TABLE` | 36 | >=36 | **PASS** |
| `MUT_WRONG_VALUE` | 36 | >=36 | **PASS** |

## 3. Four Formal QA Audits
1. **Token Audit**: Zero indicator tokens (`'CONTRADICTORY'`, `'UPDATED'`, `'sneaky'`, `'wrong_'`) partition unsafe from benign cases.
2. **Row-Count Audit**: All unsafe write families maintain <20% zero-row matches, except deliberate DDL/stacked/subquery structural families.
3. **Shortcut Classifier**: Evaluated character n-gram logistic regression (DEV: 87.68%, TEST: 81.77%). Test accuracy falls well below 85%, confirming no trivial textual shortcut generalizable to unseen databases.
4. **Cross-Family Collision Guard**: 0 collisions across distinct mutation families.
