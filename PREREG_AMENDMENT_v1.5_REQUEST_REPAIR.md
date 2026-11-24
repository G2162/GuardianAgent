# Pre-Registration Amendment v1.5: Dataset Ground-Truth Request Repair Protocol

**Document:** `PREREG_AMENDMENT_v1.5_REQUEST_REPAIR.md`  
**Date:** 2026-11-24  
**Status:** Pre-registered Protocol (committed strictly BEFORE dataset repair execution)  
**Git Tag:** `prereg-v1.5-amendment`  
**Prior Tags:** `prereg-v1.0`, `prereg-v1.1`, `prereg-v1.2-amendment`, `prereg-v1.2`, `prereg-v1.3-amendment`, `prereg-v1.3`, `prereg-v1.4`, `prereg-v1.4-amendment`  
**Target Splits:** `dev_dataset_v1.5`, `dev_paired_dataset_v1.5`, `dev_extended_dataset_v1.5`, `test_paired_dataset_v1.5`

---

## 1. Context and Disclosure

During the mechanical Request/SQL consistency audit of Dataset v1.4 (`results/dataset_audit/CONSISTENCY_AUDIT_v1.4.md`), an automated check revealed that natural language user requests diverge from the executed SQL in approximately 27% of benign test writes and across dev splits, along with their paired twins and unsafe partners.

### 1.1 Root Cause of Defect
The divergence stems from synthetic benchmark repair operations in v1.4:
1. In `MUT_MULTI_ROW_UPDATE`, SQL SET literals were updated from generic placeholder `'UPDATED'` to database-grounded values (`*_bmulti`), but the natural language request text was left un-synchronized, asserting the literal `'UPDATED'`.
2. In `build_paired_twins()`, benign twins were constructed with alternate values (`*_alt`) or swapped columns to ensure safe single-row execution on SQLite, but the base record's request text was reused without updating the target literal or column.
3. In `MUT_INTENT_INSERT`, the request template stated setting a column to a sample value `{v1_repr}`, while the SQL generator appended `_ins` or added `9000` to all tuple values in the `INSERT INTO ... VALUES (...)` clause.

### 1.2 Non-Evaluation & Data-QA Disclosure
- **Strictly Data-QA Read**: Test split inspection was conducted solely as a mechanical AST and token audit (logged under `type=data_qa` in `results/test_runs.log`).
- **Zero Pipeline Execution on Test**: No GuardianAgent pipeline module (`guardian.py`, `guardian_v2.py`, Layer 1, Layer 2, or Layer 3) has ever been run on the test split.
- **Independence from Pipeline Outputs**: Neither the detection of inconsistent cases nor the repair protocol relies on any pipeline prediction, score, or classification.

### 1.3 Decision on Amendment Options
Two preliminary options were evaluated:
- **Option 1 (Exclusion)**: Surgically purging flagged records was evaluated and formally **rejected** (`archive/rejected/PREREG_AMENDMENT_v1.5_EXCLUDE.md`). Dropping contaminated pairs causes 8 test families to drop below the pre-registered 30-case threshold (`MUT_WRONG_COLUMN` dropping to 2, `MUT_MISSING_WHERE_UPDATE` to 4, `MUT_WRONG_ROW` to 6), severely impairing statistical power and eliminating the core semantic mutation families that test the paper's main claim.
- **Option 2 (Regeneration)**: Re-running synthetic generator pipelines risks introducing non-deterministic drift across unrelated records.
- **Option 3 (Ground-Truth Request Repair - THIS AMENDMENT)**: A targeted third option is adopted: mechanically reconstructing the natural language request text from the **gold SQL AST** while preserving all non-request fields byte-for-byte.

---

## 2. Invariant Guarantees & Repair Scope

The v1.5 repair is governed by strict mathematical and provenance invariants:

1. **Request-Only Modification Invariant**:
   - The repair changes **ONLY** the `request` text and `request_paraphrase`.
   - All other fields remain **100% byte-identical** to v1.4:
     * `sql` (candidate SQL)
     * `gold_sql` (gold SQL)
     * `family_id` (mutation family)
     * `expected_decision_variant_a` and `expected_decision_variant_b`
     * `database`
     * `case_id`
     * `pair_id`, `is_paired`, `twin_of`
     * `measured_affected_rows`, `n_matched`, `n_changed`, `executes_ok`, `error_message`
     * `catastrophic`
     * `intent_spec`
2. **Dual-Detector Consensus Requirement**:
   - Only records flagged by **both** independent detectors (the original consistency audit detector and the independent AST scoped validator) are repaired.
   - Records flagged by only one detector are preserved unchanged and exported to `results/dataset_audit/single_detector_flags.csv` for transparent audit.
3. **Gold-SQL Alignment Invariant**:
   - The user request represents the user's intended state operation; therefore, the request MUST describe the **GOLD SQL**, never the candidate mutation.
   - For any benign record, its paired twin, and every unsafe mutation sharing the same gold SQL, the exact same repaired request text is used.
4. **Template Diversity ($\ge 4$ Sentence Templates)**:
   - To prevent linguistic uniformity, requests are generated using at least 4 grammatically diverse sentence templates, deterministically selected by `hash(case_id) % N_TEMPLATES`.
5. **Paraphrase Quality Invariant**:
   - For all repaired records, `request_paraphrase` is regenerated using the designated non-extractor model. Paraphrases are programmatically validated to ensure all required ground-truth entities (table, columns, literals) are preserved.

---

## 3. Verification Protocol

1. **Hard Build Gates (`dataset_gates.py`)**:
   - Hard gate terminates build if any record in dev or test splits specifies a literal value or column absent from the gold/candidate SQL AST.
   - Byte-level hash verification proving all non-request fields equal their exact v1.4 values.
2. **Data-QA Re-audit**:
   - Re-running the four shortcut classifiers (request-only, raw SQL, normalized SQL, request+SQL) to prove that request repair does not introduce shortcut leakage.
   - Stratified execution verification of 150 cases per split.
