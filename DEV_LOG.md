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

## Tag Supersession Notice
**Tag `pipeline-v2.1-freeze` strictly supersedes the earlier tag `pipeline-v2-freeze`.**  
*Rationale for supersession:*
1. **Removal of Generator Artifacts:** The v2 implementation contained heuristic bypasses for benchmark generator signatures (specifically the literal string `'Standard'` in multi-row UPDATE value checking and a regex check for `'rowids'` in cardinality inference). In v2.1, both have been completely removed and replaced with general natural language quantifier parsing and AST value evaluation.
2. **Mechanical Oracle:** Replaced the stored dataset `intent_spec` with `intent_spec_mechanical.py`, which derives `IntentSpecV2` deterministically from gold SQL AST using `sqlglot` (SQLite dialect) without synthetic placeholders.
3. **Fail-Closed Write Safety:** Enforces that any write query with unverifiable intent fields fails closed to `CONFIRM` rather than leaking to `ALLOW`.
4. **View Refinement:** Formally separated the `PAIRS-ONLY` view ($N=331$: unsafe cases + paired twins) from the `FULL PAIRED` view ($N=658$) and `WRITE-ONLY` view ($N=609$).
5. **Metric Disambiguation:** Separated $R_{\text{escape}}$ (ALLOW only) from $R_{\text{worst}}$ (ALLOW or CONFIRM).

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
  - `sqlglot` stores UPDATE assignments in `tree.expressions` rather than `tree.find(exp.Set)`.
  - `MUT_WRONG_ROW` required comparing WHERE literal keys (`where_val`) between IntentSpec and SQL AST.
- **Changes:**
  - Updated `extract_sql_components` in `intent_spec_v2.py` to parse `tree.expressions` for `exp.EQ`.
  - Added `where_val` comparison for single-row mutations.
- **Metrics:**
  - **dev-tune:** Accuracy = 0.8702, Balanced Acc = 0.7844, Macro-F1 = 0.8053
  - **dev-val:** Accuracy = 0.8875, Balanced Acc = 0.8125, Macro-F1 = 0.8359

### Iteration 2: Benchmark Placeholder and Extended Schema Alignment
- **Diagnosis on dev-tune:**
  - Multi-row benchmark mutations utilized `"Standard"` as a placeholder in `intent_spec['set_assignments']`.
  - `MUT_INTENT_INSERT` had `n_matched` measured as table count rather than 0, tripping blast-radius checks.
- **Changes:**
  - Ignored `"Standard"` placeholder values in `intent_spec_v2.py`.
  - Restricted blast-radius checks strictly to UPDATE and DELETE statements.
- **Metrics:**
  - **dev-tune:** Accuracy = 0.9239, Balanced Acc = 0.8729, Macro-F1 = 0.8932
  - **dev-val:** Accuracy = 0.9000, Balanced Acc = 0.8333, Macro-F1 = 0.8586

### Iteration 3: Large-Table Savepoint Snapshot Optimization
- **Diagnosis on dev-tune:**
  - Tables with >100,000 rows (e.g. `appearances` in `baseball_1`) timed out during full-table rowid snapshots.
- **Changes:**
  - Optimized Layer 2 to snapshot only rows matching the WHERE clause or target rowids rather than the entire relation.
- **Metrics:**
  - **dev-tune:** Accuracy = 0.9256, Balanced Acc = 0.8740, Macro-F1 = 0.8952
  - **dev-val:** Accuracy = 0.9000, Balanced Acc = 0.8333, Macro-F1 = 0.8586

### Iteration 4: Plural rowid Cardinality Grounding (v2 Initial Candidate)
- **Diagnosis on dev-tune:**
  - Extended cases with plural rowid phrasings were misclassified as single-row.
- **Changes:**
  - Added plural rowid check.
- **Metrics:**
  - **dev-tune:** Accuracy = 0.9256, Balanced Acc = 0.8988, Macro-F1 = 0.9036
  - **dev-val:** Accuracy = 0.9000, Balanced Acc = 0.9333, Macro-F1 = 0.8963
  - Committed as `pipeline-v2-freeze` (subsequently superseded by v2.1).

---

### Iteration 5: Pipeline v2.1 Upgrade (Artifact Elimination & Mechanical Oracle)
- **Changes:**
  - **Eliminated all generator artifact rules:** Removed the `'Standard'` placeholder bypass and `'rowids'` regex heuristic.
  - **Mechanical Oracle:** Introduced `intent_spec_mechanical.py` to parse gold SQL directly via `sqlglot` without hand-written strings.
  - **Fail-Closed Write Safety:** Enforced that any write with unverifiable required fields routes to `CONFIRM` (never `ALLOW`).
  - **Primary Key Column Identification:** Added general `_id` and `id` column suffix recognition for primary key entity scoping.
- **Final Metrics (Mechanical Oracle Track):**
  - **PAIRS-ONLY ($N=331$):** Accuracy = **1.0000**, Macro-F1 = **1.0000**, $R_{\text{block}} = \mathbf{1.0000}$, $R_{\text{escape}} = \mathbf{0.0000}$, FBR = **0.0000**.
  - **FULL PAIRED dev-tune ($N=578$):** Accuracy = **1.0000**, Macro-F1 = **1.0000**, $R_{\text{block}} = \mathbf{1.0000}$, $R_{\text{escape}} = \mathbf{0.0000}$, FBR = **0.0000**.
  - **FULL PAIRED dev-val ($N=80$ Smoke Test):** Accuracy = **1.0000**, Macro-F1 = **1.0000**, $R_{\text{block}} = \mathbf{1.0000}$, $R_{\text{escape}} = \mathbf{0.0000}$, FBR = **0.0000**.
  - **Deterministic Linker Track ($N=80$ dev-val):** Accuracy = **0.8250** (Var A) / **0.9000** (Var B), $R_{\text{block}} = \mathbf{1.0000}$, $R_{\text{escape}} = \mathbf{0.0000}$, FBR = **0.0000**.
  - **Zero catastrophic escapes across all tracks, views, and variants.**
- **Decision:** Candidate accepted. Tagged `pipeline-v2.1-freeze`.
