# Comprehensive Scientific Audit & Replication Report: GuardianAgent

**Audit Target:** GuardianAgent Research Repository & IEEE Paper Evaluation Package  
**Audit Date:** 2026-11-11  
**Auditor:** Antigravity (Google DeepMind Advanced Agentic Coding Pair Programmer)  
**Evaluated Branch:** `main` (Frozen Pipeline — No pipeline code modified)  
**Execution Environment:** Windows 11 / Python 3.13.15 / SQLite 3.50  
**Verification Harness:** `results/audit/verify_all_claims.py`  
**Output Metrics Manifest:** `results/audit/reproduced_metrics.json`  

---

## 1. Executive Summary & Integrity Scorecard

This audit independently tested and verified every experimental claim, performance metric, latency claim, and evaluation pipeline presented in `evaluation/EXPERIMENTAL_EVALUATION_SECTION.md`, `GuardianAgent_Final_Paper_Results.md`, and the paper abstract.

### Key Audit Findings:
1. **Severe Internal Pipeline Contradiction (V1/V2 vs. Benign Calibration):**  
   The paper reports **100% accuracy on V1** and **98.20% accuracy / 4.50% unsafe miss on V2** alongside a **0.0% false block rate on benign BIRD queries**. **These claims cannot simultaneously hold on the same frozen code.**  
   When the author fixed the benign false-block issue by preventing `FIELD_MISMATCH` on `SELECT` queries from triggering a hard `BLOCK` ($R \ge 7.0$), this code change immediately broke 100 cases in V1 and 107 cases in V2 that expected `BLOCK`. Re-running V1 and V2 on the current frozen pipeline drops V1 accuracy to **93.33%** (16.67% unsafe miss) and V2 accuracy to **92.87%** (17.83% unsafe miss). The paper published pre-fix synthetic numbers alongside post-fix benign numbers.
2. **Oracle Intent Extraction on Synthetic Benchmarks (Audit Question A):**  
   Both V1 (1,500 cases) and V2 (1,500 cases), as well as earlier synthetic runners (`benchmark_runner.py`, `heldout_runner.py`, `controlled_tests.py`), bypassed the natural language intent extraction engine completely by passing `known_intent=case["ground_truth_intent"]`. The reported 100% and 98.20% accuracies test only the downstream rule engine against structured JSON, not the actual end-to-end NLP gateway.
3. **Post-Hoc Data Snooping & Rule Tuning on Held-Out Test Set (Audit Question B):**  
   Pre-calibration GuardianAgent suffered a **48.0% false block rate** (24/50 harmless queries aborted) on the held-out BIRD benign queries. Git history and the backup folder `core_backup_pre_false_block_fix/` prove that the developer iteratively developed monkey-patches in `scratch/test_calibration.py` and `scratch/test_refined_calibration.py` directly against the 342 held-out mutations and 50 benign queries until false blocks reached 0 and interception reached 333/342, then permanently applied those patches to `risk_engine.py`, `intent_analyzer.py`, and `intent_sql_checker.py`.
4. **Latency Provenance Mismatch & Abstract Cherry-Picking:**  
   - The paper's Table I claims a **17.38 ms mean latency** for the 342 Held-Out BIRD Mutations. This is factually false: the actual recorded mean latency for the 342 mutations is **662.40 ms** (median 287.41 ms) due to live SQLite table scan verification. The 17.38 ms figure was taken from the 50 benign queries (which lacked intensive scope checks) and misattributed to the mutation suite.
   - The paper abstract claims a **"2.49 ms mean latency"**. This number comes exclusively from the DBBench multi-turn agent benchmark (`dbbench_60_groq_summary.json`), which evaluated simple single-table operations, cherry-picking the best latency figure in the entire paper.
5. **Metric Mislabeling ("Strict BLOCK" vs. "Strict Correct"):**  
   The claim of **314 "strict BLOCK"** on held-out BIRD (Table I, Table VI) is a labeling error. The actual number of `BLOCK` decisions is **245–246 (71.93%)**; 87–88 cases were routed to `CONFIRM` (human review). The number 314 represents **strict policy correctness** (where expected decision matched actual decision under `is_correct()`), not 314 blocks.

---

## 2. Detailed Claim-by-Claim Audit & Reproduction Matrix

| Benchmark Target | Paper Claimed Metric | Re-Run / Verified Metric | Status | Primary Script | Root Cause / Discrepancy |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **V1 Synthetic** (1,500 cases) | **100.0%** accuracy<br>**0.631 ms** latency | **93.33%** acc (Standard)<br>**83.33%** acc (Strict)<br>0.898 ms latency | **BROKEN** by later pipeline patch | `benchmark/large_v1_runner.py` | 100 `FIELD_MISMATCH` queries demoted from `BLOCK` to `CONFIRM` by benign calibration patch. Oracle intent used. |
| **V2 Adversarial** (1,500 cases) | **98.20%** accuracy<br>**4.50%** unsafe miss | **92.87%** acc (Standard)<br>**81.33%** acc (Strict)<br>**17.83%** unsafe miss | **BROKEN** by later pipeline patch | `benchmark/large_v2_runner.py` | 107 `FIELD_MISMATCH` queries demoted to `CONFIRM`. Unsafe miss quadrupled from 4.5% to 17.83%. Oracle intent used. |
| **BIRD Held-Out** (342 mutations) | **333 / 342** intercepted (97.37%)<br>**0 / 200** catastrophic escapes | **333 / 342** (97.37%)<br>**0 / 200** (100.0%) | **REPRODUCED** | `bird_eval/scripts/run_fresh_mutation_eval.py` | Safety interception (333) and zero catastrophic escapes (0/200) replicate 100% deterministically. |
| **BIRD Held-Out** (Decision count) | **314** "strict BLOCK" | **246 BLOCK**<br>87 CONFIRM<br>9 ALLOW | **DISCREPANCY** (Mislabeling) | `bird_eval/scripts/run_fresh_mutation_eval.py` | 314 is strict correct matching; actual BLOCK count is 246. Calling it "strict BLOCK" is factually inaccurate. |
| **BIRD Held-Out** (Latency claim) | **17.38 ms** mean latency | **662.40 ms** mean<br>287.41 ms median | **MAJOR DISCREPANCY** | `bird_eval/results/bird_fresh_mutation_eval_results.json` | 17.38 ms is the 50-benign latency; 342-mutation live SQLite scope checks actually average 662.40 ms. |
| **Benign Set** (50 queries) | **31 ALLOW**<br>**19 CONFIRM**<br>**0 BLOCK** | **31 ALLOW** (62.0%)<br>**19 CONFIRM** (38.0%)<br>**0 BLOCK** (0.0%) | **REPRODUCED EXACTLY** | `bird_eval/scripts/evaluate_benign_queries.py` | Reproduces 100%. However, rules were tuned directly on this dataset (data snooping). |
| **DBBench Suite** (60 live tasks) | **46 / 60** success (76.67%)<br>8 ALLOW / 8 CONFIRM / 44 BLOCK | **46 / 60** success<br>8 ALLOW / 8 CONFIRM / 44 BLOCK | **REPRODUCED** (from summary & cache) | `benchmark/dbbench_groq_evaluator.py`<br>`benchmark/dbbench_60_groq_summary.json` | Replicates from cache. Note: `dbbench_60_groq_results.json` only contains 59 tasks (task 60 was omitted from array). |
| **Paper Abstract** (Latency claim) | **2.49 ms** mean latency | **2.49 ms** mean<br>(Median: 1.82 ms) | **TRACED** (Cherry-Picked) | `benchmark/dbbench_60_groq_summary.json` | Traced to DBBench single-table tasks. Misleading to present in abstract as general system latency. |

---

## 3. Deep Dive: Target-by-Target Verification

### 3.1 Target 1: Synthetic Benchmarks V1 & V2 (1,500 Cases Each)
- **Paper Claims:**
  - V1: 1,500 cases, 100.0% accuracy, 0.631 ms mean latency, 0.0% unsafe miss rate.
  - V2: 1,500 cases, 98.20% accuracy, 4.50% unsafe miss rate (27/600), 0.628 ms mean latency.
- **Reproduction Command:**
  ```bash
  python benchmark/large_v1_runner.py
  python benchmark/large_v2_runner.py
  ```
- **What Actually Happens When Re-Run:**
  - `large_v1_runner.py`:
    - Evaluated: 1,500 | Correct: 1,400 | Errors: 100 | **Accuracy: 93.33%**
    - Unsafe Miss Rate: **16.67%** (100 / 600 dangerous cases predicted `CONFIRM` instead of `BLOCK`)
    - Mean Latency: 0.898 ms
    - Zero accuracy on category `FIELD_MISMATCH`: 0 / 100 (0.0%)
  - `large_v2_runner.py`:
    - Evaluated: 1,500 | Correct: 1,393 | Errors: 107 | **Accuracy: 92.87%**
    - Unsafe Miss Rate: **17.83%** (107 / 600 dangerous cases predicted `CONFIRM` instead of `BLOCK`)
    - Mean Latency: 0.760 ms
    - Zero accuracy on adversarial categories `NUM_FIELD_STR_SQL` (0/40), `SCOPE_AND_FIELD_MISMATCH` (0/27), `STR_FIELD_NUM_SQL` (0/40).
- **Forensic Root Cause Analysis:**
  Before commit `f470c23` (preserved in `core_backup_pre_false_block_fix/risk_engine.py`), the safety override was:
  ```python
  # Old code (produced 100% V1 and 98.2% V2):
  if "FIELD_MISMATCH" in mismatches:
      risk_score = max(risk_score, 7.0)  # Always BLOCK
  ```
  In commit `f470c23`, to fix the 48.0% false block rate on benign queries, this was changed to:
  ```python
  # New code (currently in production):
  if operation in {"UPDATE", "INSERT", "DELETE"} and "FIELD_MISMATCH" in mismatches:
      risk_score = max(risk_score, 7.0)
  elif operation == "SELECT" and "FIELD_MISMATCH" in mismatches:
      risk_score = max(risk_score, 4.0)  # Demoted to CONFIRM
  ```
  In `heldout_v1_1500_dataset.json`, there are exactly 100 `SELECT` queries with `FIELD_MISMATCH` that expected `BLOCK`. In `adversarial_v2_1500_dataset.json`, there are 107. When the override was softened, all 107 shifted from `BLOCK` to `CONFIRM`.
  Testing `core_backup_pre_false_block_fix` directly against V1 and V2 verifies this 100%:
  - On `core_backup`: V1 accuracy is **100.0%** and V2 accuracy is **98.20%**.
  - On current code: V1 accuracy is **93.33%** and V2 accuracy is **92.87%**.
- **Mode Sensitivity (STANDARD vs. STRICT):**
  If executed with `GUARDIAN_READ_SAFETY_LEVEL=STRICT` (prescribed in `evaluation/reproduction/README.md`), V1 accuracy drops to **83.33%** and V2 to **81.33%**, because read target mismatches escalate to `BLOCK` when the synthetic datasets expected `CONFIRM`.

---

### 3.2 Target 2: Primary Held-Out BIRD Mutations (342 Cases, 10 Schemas)
- **Paper Claims:**
  - 333 / 342 safety intercepted (97.37%)
  - 314 "strict BLOCK"
  - 0 / 200 catastrophic write escapes
  - 17.38 ms mean latency
- **Reproduction Command:**
  ```cmd
  :: Windows CMD / PowerShell
  $env:GUARDIAN_DISABLE_LLM="1"; $env:GUARDIAN_READ_SAFETY_LEVEL="STRICT"
  python bird_eval/scripts/run_fresh_mutation_eval.py
  ```
- **Reproduction Findings:**
  1. **Safety Interception (97.37%):** **REPRODUCED.** Exactly 333 / 342 queries are prevented from autonomous execution (245–246 `BLOCK` + 87–88 `CONFIRM`).
  2. **Catastrophic Escapes (0/200):** **REPRODUCED.** All 200 destructive write operations (`DANGEROUS_DELETE`, `DANGEROUS_DELETE_WHERE`, `DANGEROUS_UPDATE`, `DANGEROUS_DROP`) are blocked autonomously.
  3. **Autonomous Escapes (9/342 = 2.63%):** **REPRODUCED.** Exactly 9 queries escape to `ALLOW` (7 `SCOPE_ESCALATION`, 1 `TARGET_MISMATCH`, 1 `FIELD_INJECT`).
  4. **Strict BLOCK Discrepancy (314):** In Table I and Table VI, the paper reports "Strict BLOCK: 314 (91.81%)". In reality, only **245 or 246 queries are BLOCK** (71.93%). The 314 figure comes from `is_correct()`:
     ```python
     def is_correct(expected: str, actual: str) -> bool:
         if expected == "BLOCK": return actual == "BLOCK"
         elif expected == "CONFIRM": return actual in ("BLOCK", "CONFIRM")
         elif expected == "ALLOW": return actual == "ALLOW"
     ```
     Of the 92 queries where `expected == "CONFIRM"`, 68 were predicted `CONFIRM` and 24 were predicted `BLOCK`. The count 314 is $246 + 68 = 314$ (Strict Correct Decision), NOT 314 Strict Blocks. Calling this column "Strict BLOCK" is misleading.
  5. **Latency Discrepancy (17.38 ms vs. 662.40 ms):**  
     In `evaluation/EXPERIMENTAL_EVALUATION_SECTION.md` Table I, the paper states GuardianAgent mean latency is **17.38 ms**.  
     Calculating mean latency across the 342 items in `bird_eval/results/bird_fresh_mutation_eval_results.json` reveals:
     - Mean: **662.40 ms**
     - Median: **287.41 ms**
     - Min: **243.86 ms**
     - Max: **19,791.47 ms**  
     The author acknowledged in `GuardianAgent_Final_Paper_Results.md` (Line 66):
     > *"On the 50-query benign BIRD evaluation: 17.38 ms mean. On the 342-case held-out mutation benchmark (full per-query SQLite scope checking enabled): 662.40 ms mean."*  
     However, Table I in the paper still printed 17.38 ms under the 342-case column.

---

### 3.3 Target 3: Benign Usability Set (50 Clean BIRD Queries)
- **Paper Claims:**
  - 50 unmutated gold queries across 10 schemas.
  - Decision Matrix: **31 ALLOW (62.0%) / 19 CONFIRM (38.0%) / 0 BLOCK (0.0%)**.
  - Mean Latency: 17.38 ms.
- **Reproduction Command:**
  ```cmd
  $env:GUARDIAN_DISABLE_LLM="1"; $env:GUARDIAN_READ_SAFETY_LEVEL="STRICT"
  python bird_eval/scripts/evaluate_benign_queries.py
  ```
- **Reproduction Findings:**
  - **Decision Matrix:** **REPRODUCED 100% EXACTLY.**
    - `ALLOW`: 31 (62.0%)
    - `CONFIRM`: 19 (38.0%)
    - `BLOCK`: 0 (0.0%)
  - **Interruption Rate:** 19 / 50 (38.0%) due to 16 `FIELD_MISMATCH` and 3 `SCOPE_MISMATCH`.
  - **Context & Caveat:** As proven in Section 4 (Audit Question B), this 0% false block rate was achieved by tuning the codebase specifically against these 50 queries. On the full uncurated BIRD mini-dev set (500 queries), deterministic GuardianAgent produced a **99.20% false-block rate (496 / 500 blocked)** (`bird_eval/full_bird/results/bird_full_final_report.md`).

---

### 3.4 Target 4: DBBench Live Agent Evaluation (60 Tasks)
- **Paper Claims:**
  - 60 tasks evaluated with Groq LLaMA-3 / GPT-OSS-120B.
  - Task Success: **46 / 60 (76.67%)**.
  - Decision Matrix: **8 ALLOW / 8 CONFIRM / 44 BLOCK**.
  - Latency: 2.49 ms mean, 1.82 ms median.
- **Reproduction Command:**
  ```bash
  python benchmark/dbbench_groq_evaluator.py
  # Offline verification from frozen summary and cache:
  python results/audit/verify_all_claims.py
  ```
- **Reproduction Findings:**
  - Summary file `benchmark/dbbench_60_groq_summary.json` records:
    - `DBBENCH.correct`: 46 / 60 (76.67%)
    - `GUARDIAN.ALLOW`: 8 (13.33%)
    - `GUARDIAN.CONFIRM`: 8 (13.33%)
    - `GUARDIAN.BLOCK`: 44 (73.33%)
    - `LATENCY.mean`: 2.49 ms, `median`: 1.82 ms
  - **Artifact Inconsistency Found:**
    `benchmark/dbbench_60_groq_results.json` only contains **59 records** (tasks 1 through 59; task 60 is missing from the list). However, task 60 is present in the input dataset `tasks_cleaned.json` and present in the disk cache `dbbench_groq_cache.json`.
    Executing task 60 independently through `guardian_check` produces:
    - Decision: `BLOCK` (score 7.0)
    - Standalone execution matches reference SQL.
    Adding task 60 completes the set to exactly 60 tasks, 46 correct, and 8 ALLOW / 8 CONFIRM / 44 BLOCK.

---

### 3.5 Target 5: Origin of Abstract Latency Claim (2.49 ms)
- **Paper Claim:** The abstract claims that GuardianAgent operates with an overall **"2.49 ms mean latency"**.
- **Forensic Investigation:**
  - Search across all git tracked files reveals that `2.49 ms` appears in exactly one benchmark:
    `benchmark/dbbench_60_groq_summary.json: "mean": 2.49`
  - In `GuardianAgent_Final_Paper_Results.md` (Line 164), it is explicitly listed as:
    > *"DBBench Inline Agent (60 live agent tasks, intent extraction included): 2.49 ms mean (1.82 ms median)"*
- **Audit Conclusion:**  
  Citing "2.49 ms mean latency" in the paper abstract as if it characterizes the entire system is **cherry-picking**. In DBBench, each task operates on a single small SQLite table in memory with simple predicates. When evaluated on realistic relational schemas from BIRD:
  - Benign queries average **17.38 ms**.
  - Adversarial mutations with live SQLite scope verification average **662.40 ms**.
  Reporting 2.49 ms without stating that it applies only to synthetic single-table benchmarks is misleading.

---

## 4. Special Audit Inquiries

### Inquiry (a): Was Ground-Truth Intent Used Instead of the Intent Extractor in Any Evaluation?
**YES. Ground-truth intent was used to bypass `analyze_intent()` across all major synthetic benchmark evaluations.**

In `guardian.py` (lines 514–522):
```python
if known_intent is not None:
    intent = known_intent
else:
    intent = analyze_intent(user_request)
```
Whenever `known_intent` is supplied, `analyze_intent()` is **completely skipped**.

#### Comprehensive Audit of Evaluation Runners:
1. **`benchmark/large_v1_runner.py` (Line 257):**
   ```python
   intent = case["ground_truth_intent"]
   result = guardian_check(user_request, sql, known_intent=intent)
   ```
   **Bypassed intent extractor.**
2. **`benchmark/large_v2_runner.py` (Line 225):**
   ```python
   intent = case["ground_truth_intent"]
   result = guardian_check(user_request, sql, known_intent=intent)
   ```
   **Bypassed intent extractor.**
3. **`benchmark/benchmark_runner.py` (Line 339):**
   `known_intent=ground_truth_intent` — **Bypassed intent extractor.**
4. **`benchmark/heldout_runner.py` (Line 101):**
   `known_intent=ground_truth_intent` — **Bypassed intent extractor.**
5. **`benchmark/heldout_v2_runner.py` (Line 396):**
   `known_intent=ground_truth_intent` — **Bypassed intent extractor.**
6. **`benchmark/run_all_experiments.py` (Lines 174, 232, 297, 440, 497):**
   `known_intent=intent` — **Bypassed intent extractor.**
7. **`controlled_tests.py` (Line 666):**
   `known_intent=test["intent"]` — **Bypassed intent extractor.**
8. **`bird_eval/scripts/run_fresh_mutation_eval.py` (Line 96):**
   Does NOT pass `known_intent`. Uses `analyze_intent()`.
9. **`bird_eval/scripts/evaluate_benign_queries.py` (Line 85):**
   Does NOT pass `known_intent`. Uses `analyze_intent()`.
10. **`benchmark/dbbench_groq_evaluator.py` (Line 378):**
    Does NOT pass `known_intent`. Uses `analyze_intent()`.

**Scientific Verdict:**  
The reported 100% and 98.20% synthetic benchmark numbers reflect **oracle intent evaluation**. They demonstrate how the risk and consequence scoring engine performs when given perfect semantic representations, but do NOT measure the performance of GuardianAgent's actual NLP parser.

---

### Inquiry (b): Were Thresholds or Rules Changed After Looking at the Held-Out Set?
**YES. Critical safety rules, thresholds, and regex parsers were modified and tuned directly on the held-out BIRD dataset.**

#### Forensic Timeline & Git History Evidence:
1. **The Pre-Calibration Baseline (Commit `f470c23`):**  
   On September 26, 2026, the developer evaluated GuardianAgent against the 50 benign gold queries from the held-out BIRD benchmark. It resulted in **24 false blocks out of 50 queries (48.0% false block rate)**, because any query with a `FIELD_MISMATCH` triggered a mandatory override to $R \ge 7.0$ (`BLOCK`), and join queries frequently triggered `TARGET_MISMATCH`.
2. **The Backup Directory:**  
   Prior to applying fixes, the developer backed up the exact unmodified files into:  
   `core_backup_pre_false_block_fix/` (`guardian.py`, `intent_analyzer.py`, `intent_sql_checker.py`, `risk_engine.py`).
3. **The Tuning Process in `scratch/`:**  
   The developer authored scratch scripts that loaded `bird_eval/results/bird_fresh_mutations_dataset.json` (the held-out test set!) and monkey-patched the core engine:
   - `scratch/test_calibration.py` (Lines 63–127): Loaded the held-out test set, monkey-patched `intent_analyzer._clean` and `risk_engine._apply_safety_overrides`, and measured the resulting decisions.
   - `scratch/test_refined_calibration.py` (Lines 36–118): Added `ENGLISH_STOPWORDS`, modified descriptor extraction, patched `intent_sql_checker._check_filter_target` with substring matching, and re-tested iteratively until the benign false blocks reached exactly 0.
4. **Committing the Tuned Rules to Production:**  
   The monkey-patches were then hard-coded directly into the production codebase:
   - **`risk_engine.py`:** Softened `FIELD_MISMATCH` on `SELECT` from $R = 7.0$ (`BLOCK`) to $R = 4.0$ (`CONFIRM`).
   - **`intent_analyzer.py`:** Added a 37-word `ENGLISH_STOPWORDS` list to `_clean()` to prevent words like *"all"*, *"the"*, *"in"* from being treated as entities.
   - **`intent_sql_checker.py`:** Added regex lookups in `FROM` and `JOIN` clauses and predicate value substrings to prevent `TARGET_MISMATCH`.

**Scientific Verdict:**  
This is a direct violation of Rule 1 (*"Never tune thresholds, weights, or rules on the test/held-out data"*). The 50 benign queries and 342 mutations were not true held-out data; the pipeline was adjusted until it achieved the desired 0% false-block rate on that specific sample.

---

### Inquiry (c): Full Inventory of Dead Code, Scratch Scripts, and Obsolete Runners

The repository contains numerous duplicate, legacy, and scratch scripts that should be moved to `archive/` to restore clarity.

#### 1. Scratch Directory (`scratch/`):
All 12 files in `scratch/` are ad-hoc development artifacts and debugging scripts:
- `scratch/ablation_pure_scoring.py`: Ad-hoc ablation test on pure scoring.
- `scratch/ablation_test.py`: Debugging ablation behavior.
- `scratch/audit_escapes.py`: Investigative script examining the 9 escapes.
- `scratch/check_8_blocks.py`: Debugging the intermediate state with 8 false blocks.
- `scratch/check_fields.py`: Field mismatch inspection.
- `scratch/find_9th_escape.py`: Script locating the 9th escape.
- `scratch/inspect_target_mismatch.py`: Target mismatch analysis.
- `scratch/test_benign_1.py`: Single-query test on California Schools question 1.
- `scratch/test_calibration.py`: Initial monkey-patch calibration test against held-out BIRD.
- `scratch/test_controlled_calibrated.py`: Verification that calibration didn't break controlled tests.
- `scratch/test_mismatch.py`: Mismatch signal debugging.
- `scratch/test_refined_calibration.py`: Final monkey-patch calibration script.

#### 2. Root Directory Dead / Prototype Code:
- `agent.py` (223 lines): Interactive prototype demo agent using Gemini and `company.db`. Not part of benchmark evaluation.
- `company.db` (8,192 bytes): Local SQLite database used by `agent.py` and `database.py`.
- `database.py` (65 lines): SQLite helper connecting to `company.db`. Only referenced by `agent.py` and `controlled_tests.py`.
- `database_context.py` (455 lines): Schema analysis module used during early synthetic dataset generation (`benchmark/generate_dataset.py`).
- `dbbench_gemini_test.py` (100 lines): Deprecated script testing Gemini 1.5 on DBBench. Unused.
- `dbbench_prepare.py` (35 lines): One-off script testing dbbench SQL analysis. Unused.
- `dbbench_stats.py` (19 lines): 19-line script printing dbbench task types. Unused.
- `test_alias.py` (76 lines): Hardcoded unit test for 3 SQL alias queries.
- `test_gemini.py` (11 lines): 11-line script testing Google GenAI SDK connection.
- `test_guardian.py` (147 lines): Early prototype tests superseded by `controlled_tests.py`.
- `schema_generalization_test.py` (559 lines): Early synthetic 6-schema test suite. Superseded by BIRD benchmark.

#### 3. Benchmark Directory Superseded / Redundant Runners (`benchmark/`):
- `ablation_runner.py` (18 KB) & `large_ablation_runner.py` (13 KB): Superseded by `benchmark/run_ablation_study.py`.
- `benchmark_runner.py` (19 KB): Early runner on `benchmark_dataset.json`.
- `heldout_runner.py` (16 KB) & `heldout_v2_runner.py` (20 KB): Superseded by `large_v1_runner.py` and `large_v2_runner.py`.
- `dbbench_evaluator.py` (24 KB) & `dbbench_stage2.py` (19 KB): Superseded by `dbbench_groq_evaluator.py`.
- `test_pipeline_single_task.py` (9 KB) & `test_pipeline_groq_single_task.py` (9 KB): Single-task integration tests.
- `inspect_dbbench.py` (1 KB), `check_preprocessing.py` (1 KB), `verify_db_tables.py` (2 KB): One-off debugging utilities.
- `generate_dataset.py`, `generate_heldout.py`, `generate_heldout_v2.py`, `generate_large_v1.py`, `generate_large_v2.py`: Offline dataset generation scripts.

#### 4. Unsupported Full BIRD Directory (`bird_eval/full_bird/`):
This directory contains an uncurated evaluation on 500 BIRD mini-dev queries and 4,719 mutations (`results/bird_full_final_report.md`). In deterministic mode, GuardianAgent yielded a **99.20% false-block rate** (496/500 clean queries blocked). It was omitted from the paper in favor of the curated 50-query set.

---

## 5. Actionable Roadmap for Publication-Ready Research

To transform GuardianAgent into rigorous, publishable research that will withstand peer review at an IEEE conference or top-tier software engineering/security venue, implement the following steps:

1. **Re-Synchronize V1/V2 with the Calibrated Pipeline (Report Honest Numbers):**  
   Do not report 100% on V1 and 98.20% on V2. Update the paper to report the actual performance of the calibrated system:
   - V1 (Standard Mode): **93.33% accuracy**, **16.67% unsafe miss rate**.
   - V2 (Standard Mode): **92.87% accuracy**, **17.83% unsafe miss rate**.  
   Frame this transparently: softening the read-field policy from hard `BLOCK` to human `CONFIRM` appropriately traded off synthetic strict-block accuracy to eliminate catastrophic false blocks in production environments.
2. **Explicitly Label Oracle vs. End-to-End Evaluations:**  
   Clearly state that synthetic benchmarks evaluate the **consequence engine with ground-truth intent**, whereas the BIRD benchmark evaluates the **end-to-end pipeline with rule-based intent parsing**.
3. **Correct Benchmark Metric Terminology:**  
   - Rename Table I and Table VI column from "Strict BLOCK" to **"Strict Policy Correctness"** ($N_{\text{correct}} / N_{\text{total}} = 314 / 342 = 91.81\%$).
   - Explicitly disclose the decision breakdown: **246 BLOCK (71.93%)**, **87 CONFIRM (25.44%)**, and **9 ALLOW (2.63%)**.
4. **Correct Latency Reporting:**  
   - In Table I, replace `17.38 ms` with the true held-out mutation latency: **662.40 ms mean (287.41 ms median)**.
   - Explain the latency decomposition: syntax parsing and rule checking takes < 2 ms; live SQLite scope checking on complex multi-table schemas takes ~600 ms.
   - In the abstract, do not state "2.49 ms mean latency" without qualification. State: *"sub-3 ms latency on single-table queries, scaling to ~600 ms when executing deep scope verification on multi-table relational joins."*
5. **Establish a True Unseen Held-Out Test Split:**  
   Because the 50 benign queries and 342 mutations were examined during calibration, construct a truly independent evaluation split (e.g. sample another 10 unseen BIRD databases or Spider 2.0 schemas) frozen before evaluation and never inspected during rule creation.
6. **Move Dead Code and Scratch Files to `archive/`:**  
   Clean up repository structure so that reviewers can navigate code easily.

---

## 6. How to Reproduce All Results in One Command

To re-run the full audit verification suite and generate `results/audit/reproduced_metrics.json`:

```bash
python results/audit/verify_all_claims.py
```

To run individual evaluation scripts:
- **Controlled Tests (39/39 passing):** `python controlled_tests.py`
- **Held-Out BIRD Mutations (342 mutations):**  
  `$env:GUARDIAN_DISABLE_LLM="1"; $env:GUARDIAN_READ_SAFETY_LEVEL="STRICT"; python bird_eval/scripts/run_fresh_mutation_eval.py`
- **Benign Gold Queries (50 queries):**  
  `$env:GUARDIAN_DISABLE_LLM="1"; $env:GUARDIAN_READ_SAFETY_LEVEL="STRICT"; python bird_eval/scripts/evaluate_benign_queries.py`
- **Ablation Study (342 mutations):** `python benchmark/run_ablation_study.py`
- **AST Policy Firewall Baseline:** `python -m pytest bird_eval/ast_firewall/tests -v`
- **V1 Synthetic Runner:** `python benchmark/large_v1_runner.py`
- **V2 Adversarial Runner:** `python benchmark/large_v2_runner.py`

