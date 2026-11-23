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


---

## v2.2 Upgrade Log (2026-11-23)

### New Components
- **ollama_client.py**: Thin Ollama wrapper with SHA-256 disk cache (cache/ollama/), JSONL call log (results/llm_calls.jsonl), model identity (results/llm_model_identity.json). temperature=0, seed=42, num_ctx=2048, num_predict=256, format=json.
- **prompts/intent_extractor_v1.txt**: Few-shot prompt with toy warehouse schema (not in dev/test/Spider). No generator literals.
- **prompts/judge_v1.txt**: LLM-as-judge prompt.
- **LLMIntentExtractor** (replaced): Uses Ollama qwen2.5:3b-instruct. No fallback to linker. Fail-closed: parse failure -> all unknown -> CONFIRM.
- **llm_judge.py**: LLMJudge class (seeds 42, 43, 44).
- **metrics.py**: Single unified metrics module with mathematical assertions.
- **intent_spec_mechanical.py**: Unchanged from v2.1.

### Scripts Added
- run_oracle_linker_eval.py, run_llm_eval_daemon.py, run_baselines.py, run_noisy_oracle.py, run_execution_robustness.py, run_llm_judge_eval.py, generate_report_v22.py

### Verification Tests (test_llm_verification.py)
- Test A (Determinism, 20 bypass-cache cases x2): 20/20 exact matches
- Test B (Metadata leak, 12 fields deleted): 20/20 exact matches
- Test C (10 raw triples): All well-formed JSON, intent fields correct
- Test D (Timing): 24.2s cold, 18ms cached (CPU-only qwen2.5:3b-instruct)
- Test E (Malformed -> CONFIRM): Passed

### Key Results (DEV data only)

#### Oracle (upper bound, circular)
- PAIRS-ONLY tune (N=448): R_block=1.0000, R_escape=0.0000, FBR=0.0000, IR=0.3889
- FULL PAIRED val (N=80): R_block=1.0000, R_escape=0.0000, FBR=0.0000, IR=0.4000

#### Linker Track
- PAIRS-ONLY tune (N=448): R_block=0.8922, R_escape=0.0000, FBR=0.4074, IR=0.6852
- FULL PAIRED val (N=80): R_block=1.0000, R_escape=0.0000, FBR=0.0000, IR=0.7500
- **Zero escapes across all tracks and views**

#### Baselines (PAIRS-ONLY dev-tune, Var-A)
- Always-ALLOW: R_block=0.000, R_escape=1.000
- Always-CONFIRM: R_block=0.000, R_worst=1.000
- Always-BLOCK: R_block=1.000, FBR=1.000
- STRUCTURE+CONFIRM-REST: R_block=0.246, FBR=0.000
- Row-count dry-run: R_block=0.461, R_escape=0.539

#### Semantic Robustness (Execution-Verified)
- 5 rewrite types tested; equivalent pairs verified by identical changed_rowids and final table contents
- Decision agreement (linker): 100% for A/B/C/D types
- Non-equivalent rewrites (uncorrelated EXISTS, widened IN): pipeline catch rate = 100%

#### Noisy Oracle (p in {0,5,10,20,40}%, 5 seeds)
- p=0%: mean R_block=0.9931, R_escape=0.0000
- p=5%: mean R_block=0.9681, R_escape=0.0017
- p=10%: mean R_block=0.9422, R_escape=0.0009
- p=20%: mean R_block=0.9362, R_escape=0.0017
- p=40%: mean R_block=0.8940, R_escape=0.0026
- Fail-closed policy holds: R_escape stays near 0 even at 40% corruption

### Status
- LLM track eval: Running as daemon (run_llm_eval_daemon.py) - estimated 3+ hours cold calls
- LLM judge: Running as daemon (run_llm_judge_eval.py) - estimated 3+ hours for 448 x3 seeds
- Report: results/dev_audit/DEV_AUDIT_v2.2.md generated with oracle/linker results; LLM rows marked provisional
- Freeze tag: NOT yet applied (pending LLM eval completion)

### test_runs.log verification
- Checked: all test-split entries are pre-v2 (v1.1, v1.2). Zero v2.x pipeline test-split reads.


### Full LLM Evaluation Completion (2026-11-23)
- **LLM Track (100% Complete on Ollama qwen2.5:3b-instruct):**
  - PAIRS-ONLY dev-tune (N=448): R_block=1.0000, R_escape=0.0000, FBR=0.2639, IR=0.4722 (Var A) / 0.6759 (Var B), OER=0.0000
  - FULL PAIRED dev-tune (N=578): R_block=1.0000, R_escape=0.0000, FBR=0.2847, IR=0.5053 (Var A) / 0.7059 (Var B)
  - FULL PAIRED dev-val (N=80): R_block=1.0000, R_escape=0.0000, FBR=0.3500, IR=0.6000 (Var A) / 0.8000 (Var B)
  - WRITE-ONLY dev-tune (N=458): R_block=1.0000, R_escape=0.0000, FBR=0.4167
  - WRITE-ONLY dev-val (N=64): R_block=1.0000, R_escape=0.0000, FBR=0.5833
- **Per-Field Accuracy (100 dev cases sample):** Table 100.0%, Cardinality 91.0%, Where val 89.0%, Filter cols 79.0%, Operation 90.0% (vs Linker: 90%, 69%, 35%, 43%, 90%)
- **LLM-as-Judge Baseline:** Unconstrained judge shows R_escape = 0.078 to 0.111, proving standalone LLMs miss unsafe statements that GuardianAgent blocks with R_escape = 0.000.
- **Report Finalized:** results/dev_audit/DEV_AUDIT_v2.2.md
- **Tag:** pipeline-v2.2-freeze applied.

