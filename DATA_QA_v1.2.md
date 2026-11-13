# DATA_QA_v1.2.md — Dataset Quality Report

**Generated:** 2026-11-13T10:46:11.344509
**DEV cases:** 391  |  **TEST cases:** 1034  |  **Total:** 1425

## 1. No-Op Check (MUT_MULTI_ROW_UPDATE)
No-op cases (SET col = col) remaining: **0** (target: 0)
> [!NOTE] Zero no-op MUT_MULTI_ROW_UPDATE cases. All verified n_changed == n_matched >= 2.

## 2. Cross-Family SQL Collision Matrix
**Total cross-mutation-family collisions: 0** (excluding by-design families: MUT_OP_VERB_MISMATCH, MUT_OP_MODALITY_MISMATCH, MUT_MULTI_ROW_BLAST_RADIUS)

> [!NOTE] Zero collisions — MUT_TAUTOLOGICAL_WHERE and MUT_WIDENED_PREDICATE_OR are now fully disjoint.

### Full Mutation-Family Collision Matrix (count of SQL-identical pairs)
| Family | MUT_BOUNDARY_OPERATO | MUT_HIDDEN_WRITE_CTE | MUT_INSERT_WRONG_TAB | MUT_MISSING_WHERE_DE | MUT_MISSING_WHERE_UP | MUT_MULTI_ROW_BLAST_ | MUT_OP_MODALITY_MISM | MUT_OP_VERB_MISMATCH | MUT_STACKED_SQL | MUT_TAUTOLOGICAL_WHE | MUT_UNDER_SCOPED_WRI | MUT_UNREQUESTED_DDL_ | MUT_UNREQUESTED_DDL_ | MUT_VALUE_SCALING | MUT_WIDENED_PREDICAT | MUT_WRONG_COLUMN | MUT_WRONG_ROW | MUT_WRONG_SUBQUERY_K | MUT_WRONG_TABLE | MUT_WRONG_VALUE |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| MUT_BOUNDARY_OPERATOR | - | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| MUT_HIDDEN_WRITE_CTE | 0 | - | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| MUT_INSERT_WRONG_TABLE_OR_VALU | 0 | 0 | - | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| MUT_MISSING_WHERE_DELETE | 0 | 0 | 0 | - | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| MUT_MISSING_WHERE_UPDATE | 0 | 0 | 0 | 0 | - | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| MUT_MULTI_ROW_BLAST_RADIUS | 0 | 0 | 0 | 0 | 0 | - | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| MUT_OP_MODALITY_MISMATCH | 0 | 0 | 0 | 0 | 0 | 0 | - | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| MUT_OP_VERB_MISMATCH | 0 | 0 | 0 | 0 | 0 | 0 | 0 | - | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| MUT_STACKED_SQL | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | - | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| MUT_TAUTOLOGICAL_WHERE | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | - | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| MUT_UNDER_SCOPED_WRITE | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | - | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| MUT_UNREQUESTED_DDL_ALTER | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | - | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| MUT_UNREQUESTED_DDL_DROP | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | - | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| MUT_VALUE_SCALING | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | - | 0 | 0 | 0 | 0 | 0 | 0 |
| MUT_WIDENED_PREDICATE_OR | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | - | 0 | 0 | 0 | 0 | 0 |
| MUT_WRONG_COLUMN | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | - | 0 | 0 | 0 | 0 |
| MUT_WRONG_ROW | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | - | 0 | 0 | 0 |
| MUT_WRONG_SUBQUERY_KEY | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | - | 0 | 0 |
| MUT_WRONG_TABLE | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | - | 0 |
| MUT_WRONG_VALUE | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | - |

## 3. Tautological WHERE Form Distribution
8 forms defined. DEV uses 5 forms, TEST uses 8 forms.
TEST-only forms (3): ['TAUT_NOT_FALSE', 'TAUT_NULL_EXHAUST', 'TAUT_NUM_GT']
Requirement (TEST >=3 forms not in DEV): **PASS**

| Form | DEV count | TEST count |
|------|-----------|------------|
| `TAUT_OR_NUM_EQ` | 3 | 5 |
| `TAUT_OR_TRUE` | 3 | 5 |
| `TAUT_OR_STR_EQ` | 3 | 5 |
| `TAUT_REPLACE_NUM_EQ` | 3 | 5 |
| `TAUT_COL_EQ_COL` | 2 | 5 |
| `TAUT_NOT_FALSE` | 0 | 4 |
| `TAUT_NUM_GT` | 0 | 4 |
| `TAUT_NULL_EXHAUST` | 0 | 4 |

## 4. MUT_WIDENED_PREDICATE_OR Verification
Cases with n_matched > 1: **51/51** (100.0%)
Requirement (>=70%): **PASS**
All use mutation_form = WIDEN_OR_PK: **True**

## 5. Family Counts (DEV | TEST)
| Family | DEV | TEST | Min TEST Unsafe |
|--------|-----|------|----------------|
| MUT_BENIGN_DDL | 15 | 39 | — |
| MUT_BOUNDARY_OPERATOR | 14 | 37 | — |
| MUT_EXACT_SCOPED_DELETE | 29 | 78 | — |
| MUT_EXACT_SCOPED_UPDATE | 28 | 76 | — |
| MUT_HIDDEN_WRITE_CTE | 14 | 37 | — |
| MUT_INSERT_WRONG_TABLE_OR_VALUES | 15 | 36 | — |
| MUT_INTENT_INSERT | 19 | 42 | — |
| MUT_MISSING_WHERE_DELETE | 15 | 38 | — |
| MUT_MISSING_WHERE_UPDATE | 14 | 37 | — |
| MUT_MULTI_ROW_BLAST_RADIUS | 9 | 29 | — |
| MUT_MULTI_ROW_DELETE | 15 | 40 | — |
| MUT_MULTI_ROW_UPDATE | 11 | 31 | — |
| MUT_OP_MODALITY_MISMATCH | 14 | 37 | — |
| MUT_OP_VERB_MISMATCH | 14 | 37 | — |
| MUT_STACKED_SQL | 14 | 37 | — |
| MUT_TAUTOLOGICAL_WHERE | 14 | 37 | — |
| MUT_UNDER_SCOPED_WRITE | 9 | 29 | — |
| MUT_UNREQUESTED_DDL_ALTER | 15 | 39 | — |
| MUT_UNREQUESTED_DDL_DROP | 15 | 39 | — |
| MUT_VALUE_SCALING | 14 | 37 | — |
| MUT_WIDENED_PREDICATE_OR | 14 | 37 | — |
| MUT_WRONG_COLUMN | 14 | 37 | — |
| MUT_WRONG_ROW | 14 | 37 | — |
| MUT_WRONG_SUBQUERY_KEY | 14 | 37 | — |
| MUT_WRONG_TABLE | 14 | 37 | — |
| MUT_WRONG_VALUE | 14 | 37 | — |

Minimum unsafe family count in TEST: 29 (requirement: >=36)
Status: **FAIL**

## 6. IntentSpec v2 Coverage
Cases missing intent_spec: **0/1425** (requirement: 0)
Status: **PASS**

## 7. Test Split Integrity
SHA-256: `44e35b7a13be6585b1540e1b5edf40044be324f62d74fe4cd9a3fe0b1cf401f3`
File set read-only: Yes

## 8. Test Runs Log Status
Total log entries: 6
Pipeline evaluations on TEST: **1** (must be 0)
Status: **FAIL**
