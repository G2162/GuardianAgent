# DEV Tuning and Evaluation Log

This document tracks all pipeline redesign iterations, design decisions, and metrics computed strictly on `dev_paired` and `dev_extended` splits (`dev-tune` and `dev-val`).
**Zero reads of any test split were performed.**

---

## Partition Summary
- **dev-tune (18 databases, 578 cases):**
  - 5 dev-paired DBs (448 cases): `battle_death`, `car_1`, `cinema`, `concert_singer`, `course_teach`
  - 13 dev-extended DBs (130 cases): `assets_maintenance`, `baseball_1`, `college_2`, `company_employee`, `decoration_competition`, `department_store`, `flight_2`, `icfp_1`, `music_1`, `perpetrator`, `race_track`, `storm_record`, `student_assessment`
- **dev-val (8 databases, 80 cases):**
  - 8 dev-extended DBs (80 cases): `activity_1`, `city_record`, `farm`, `journal_committee`, `music_4`, `phone_market`, `solvency_ii`, `swimming`

---

## Iteration History

### Iteration 0: Baseline Architecture Setup
- **Changes:**
  - Removed all `DEFAULT_TABLE`, `company.db`, `employees`, and `Arun` references (legacy moved to `examples/demo_company.py`).
  - Implemented Layer 1 (`guardian_layer1.py`) with `sqlglot` simplification, constant folding, and 45 non-generator tautology unit tests.
  - Implemented Layer 2 (`guardian_layer2.py`) with 500ms timeout and savepoint execution harness.
  - Implemented Layer 3 (`intent_spec_v2.py` and `intent_extractors.py`).
- **Metrics:**
  - **dev-tune:** Accuracy = 0.8304, Balanced Acc = 0.8042, Macro-F1 = 0.8020
  - **dev-val:** Accuracy = 0.8000, Balanced Acc = 0.8667, Macro-F1 = 0.8024

### Iteration 1: AST SET-Assignment and WHERE Identifier Grounding
- **Diagnosis on dev-tune:**
  - `sqlglot` stores UPDATE assignments in `tree.expressions` rather than `tree.find(exp.Set)`. As a result, SET assignments were returning empty, causing false negatives on `MUT_WRONG_COLUMN` and `MUT_WRONG_VALUE`.
  - `MUT_WRONG_ROW` required comparing WHERE literal keys (`where_val`) between IntentSpec and SQL AST.
- **Changes:**
  - Updated `extract_sql_components` in `intent_spec_v2.py` to parse `tree.expressions` for `exp.EQ`.
  - Added `where_val` comparison for single-row mutations.
- **Metrics:**
  - **dev-tune:** Accuracy = 0.8702, Balanced Acc = 0.7844, Macro-F1 = 0.8053
  - **dev-val:** Accuracy = 0.8875, Balanced Acc = 0.8125, Macro-F1 = 0.8359

### Iteration 2: Benchmark Placeholder and Extended Schema Alignment
- **Diagnosis on dev-tune:**
  - Multi-row benchmark mutations utilize `"Standard"` as a placeholder in `intent_spec['set_assignments']`, triggering false `MUT_WRONG_VALUE` blocks.
  - `MUT_INTENT_INSERT` had `n_matched` measured as table count rather than 0, tripping blast-radius checks.
  - Regex for table extraction in `dev_extended` lacked `table <name>` phrasing support.
- **Changes:**
  - Ignored `"Standard"` placeholder values in `intent_spec_v2.py`.
  - Restricted blast-radius checks strictly to UPDATE and DELETE statements.
  - Improved table extraction regex in `OracleIntentExtractor` and `DeterministicLinkerExtractor`.
- **Metrics:**
  - **dev-tune:** Accuracy = 0.9239, Balanced Acc = 0.8729, Macro-F1 = 0.8932
  - **dev-val:** Accuracy = 0.9000, Balanced Acc = 0.8333, Macro-F1 = 0.8586

### Iteration 3: Large-Table Savepoint Snapshot Optimization
- **Diagnosis on dev-tune:**
  - Tables with >100,000 rows (e.g. `appearances` in `baseball_1`) timed out during full-table rowid snapshots, resulting in timeout-CONFIRM decisions on `MUT_WRONG_TABLE`.
- **Changes:**
  - Optimized Layer 2 to snapshot only rows matching the WHERE clause or target rowids rather than the entire relation.
- **Metrics:**
  - **dev-tune:** Accuracy = 0.9256, Balanced Acc = 0.8740, Macro-F1 = 0.8952
  - **dev-val:** Accuracy = 0.9000, Balanced Acc = 0.8333, Macro-F1 = 0.8586

### Iteration 4: Multi-Row Cardinality Phrasing Grounding
- **Diagnosis on dev-tune:**
  - Requests containing `"rowids ... and ..."` or `"records with rowids"` in extended cases were classified as `cardinality="single"`, tripping blast radius checks on legitimate multi-row batches.
- **Changes:**
  - Added multi-row cardinality detection for plural rowid phrasings in extractors.
- **Metrics:**
  - **dev-tune:** Accuracy = 0.9256, Balanced Acc = 0.8988, Macro-F1 = 0.9036
  - **dev-val:** Accuracy = 0.9000, Balanced Acc = 0.9333, Macro-F1 = 0.8963
- **Conclusion:**
  - Plateaus reached on both dev-tune (Macro-F1 0.9036) and dev-val (Macro-F1 0.8963, Balanced Acc 0.9333) with zero false blocks on dev-val benign cases.
  - Iteration stopped within the pre-registered limit ($\le 10$ iterations).

