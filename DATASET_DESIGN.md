# GuardianAgent Dataset Design & Split Specification
**Pre-Registered Evaluation Benchmark for Database Mutation Safety (v1.1)**

- **Created:** 2026-11-12
- **Pre-Registration Tag:** `prereg-v1.1`
- **Pipeline Baseline Commit:** `46d12ae955f9924aa704d7e2282c4c45ab778a69`
- **Integrity Manifest:** `test_manifest.json`
- **Execution Guard:** `eval_guard.py`

---

## 1. Zero Database-Overlap Guarantee
To prevent data leakage, schema memorization, or prior knowledge contamination, 18 fresh relational database schemas were selected from Spider. An automated cryptographic audit ([overlap_check.py](file:///d:/Git/GuardianAgent/overlap_check.py)) verified **exact zero overlap** against all 11 databases historically used in GuardianAgent evaluations (`california_schools`, `card_games`, `codebase_community`, `debit_card_specializing`, `european_football_2`, `financial`, `formula_1`, `student_club`, `superhero`, `thrombosis_prediction`, `toxicology`).

---

## 2. Benchmark Composition & Partitioning

The evaluation dataset comprises 1,460 total test-verified database cases across 26 mutation and benign operation families, partitioned strictly by database schema (no database appears in both splits):

| Metric | DEV Split (30%) | TEST Split (70%) | Total Benchmark |
| :--- | :---: | :---: | :---: |
| **Database Count** | 5 | 13 | 18 |
| **Databases** | `battle_death`, `car_1`, `cinema`, `concert_singer`, `course_teach` | `dog_kennels`, `flight_company`, `museum_visit`, `network_1`, `orchestra`, `pets_1`, `poker_player`, `singer`, `store_product`, `tvshow`, `voter_1`, `world_1`, `wta_1` | 18 schemas |
| **Total Query Cases** | 403 | 1,057 | 1,460 |
| **Benign Cases** | 121 | 315 | 436 |
| **Unsafe Cases** | 282 | 742 | 1,024 |
| **Unsafe Family Coverage** | 20 families | 20 families | 20 families |
| **Test Cases Per Unsafe Family** | $\ge 13$ | $\ge 36$ (exceeds $\ge 25$ req.) | $\ge 50$ |
| **Integrity State** | Free Tuning Allowed | **Cryptographically Frozen & Read-Only** | Tracked in `test_manifest.json` |

---

## 3. Mandatory Single-Evaluation Protocol for Test Split

To preserve the statistical validity of the empirical evaluation and prevent adaptive overfitting:
1. **At Most One Evaluation per Pipeline Version:** Each tagged pipeline version may be evaluated on the frozen test split at most **once**. Repeated evaluations with incremental tweaks are strictly prohibited.
2. **Read-Only Test Files:** The test split (`data/evaluation_splits/test_dataset.json`) is set to read-only on disk and verified by SHA-256 before any run.
3. **Automated Audit Logging:** Every test evaluation run must invoke `eval_guard.py`, which appends an immutable audit entry to `results/test_runs.log` containing timestamp, git commit, pipeline version, configuration, intent track, and split name.
4. **No Pipeline Changes Using Test Results:** Under no circumstances may thresholds, weights, AST rules, or regexes be altered based on findings or error inspections from the test split.
