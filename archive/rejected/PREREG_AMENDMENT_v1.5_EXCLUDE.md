# REJECTION NOTICE: AMENDMENT OPTION 1 (EXCLUSION) REJECTED

> [!CAUTION]
> **Status: REJECTED (2026-11-24)**
> This amendment was rejected because surgical exclusion of flagged records and their pairs causes 8 test families to drop below the pre-registered 30-case threshold (e.g. MUT_MISSING_WHERE_UPDATE dropping to 4 cases, MUT_WRONG_ROW to 6, MUT_WRONG_COLUMN to 2), severely underpowering per-family statistical evaluation. Crucially, dropping paired cases removes the exact semantic mutation families designed to test the paper's core hypothesis regarding intent verification. Therefore, exclusion is rejected in favor of Option 3 (Ground-Truth Request Repair).

# Pre-Registration Amendment v1.5 (Option 1: Exclude Inconsistent Records)

**Document:** `PREREG_AMENDMENT_v1.5_EXCLUDE.md`  
**Date:** 2026-11-24  
**Status:** DRAFT (Not yet committed or activated)  
**Target:** Dataset v1.5 Resolution via Surgical Exclusion of Inconsistent Records  

---

## 1. Context and Disclosure

During the v1.4 dataset audit (`results/dataset_audit/CONSISTENCY_AUDIT_v1.4.md`), an automated consistency check revealed that a subset of benign and twin write records contain semantic discrepancies between the natural language user request and the executed SQL statement. These arose from synthetic benchmark repair operations in v1.4 (e.g., replacing `'UPDATED'` with `*_bmulti` without updating the natural language request template, and generating altered twin SET assignments without updating the base request text).

### Formal Non-Evaluation Disclosure:
- **Data-QA Read Only**: All test split inspections were conducted strictly as read-only data quality audits (logged under `type=data_qa` in `results/test_runs.log`).
- **Zero Pipeline Execution on Test**: No GuardianAgent pipeline module (`guardian.py`, `guardian_v2.py`, Layer 1, Layer 2, or Layer 3) has ever been executed on the test split.
- **Independence from Pipeline Results**: The exclusion criteria are strictly lexical and AST-based (comparing request literals and column identifiers against candidate/gold SQL). Zero pipeline predictions, decisions, or risk scores were used to identify or select excluded cases.

---

## 2. Specification of Option 1: Exclusion Protocol

Under Option 1, all records exhibiting unresolved request/SQL value or column divergence—along with their paired twins or counterpart unsafe cases sharing the same `pair_id`—are surgically purged from the benchmark.

### 2.1 Post-Exclusion Split Dimensions
- **Test Set (`test_paired_dataset_v1.5`)**:
  * Original cases: **1,419**
  * Excluded cases: **535** (154 directly flagged + 381 paired counterparts)
  * Retained cases: **884** (455 benign, 429 unsafe, 213 twins)
- **Dev Set (`dev_paired_dataset_v1.5`)**:
  * Original cases: **448**
  * Excluded cases: **72** (51 directly flagged + 21 paired counterparts)
  * Retained cases: **376** (165 benign, 211 unsafe, 78 twins)

### 2.2 Family Representation Impact & Trade-Offs
Exclusion completely eliminates false extractor penalties arising from generator discrepancies. However, because pairing requires dropping both halves of a contaminated pair, sample size is significantly reduced:
- **8 families drop below the pre-registered 30-case threshold in TEST**:
  * `MUT_MISSING_WHERE_UPDATE` ($N=4$)
  * `MUT_WRONG_ROW` ($N=6$)
  * `MUT_WRONG_COLUMN` ($N=2$)
  * `MUT_UNDER_SCOPED_WRITE` ($N=11$)
  * `MUT_WRONG_SUBQUERY_KEY` ($N=1$)
  * `MUT_WRONG_TABLE` ($N=22$)
  * `MUT_VALUE_SCALING` ($N=14$)
  * `MUT_WRONG_VALUE` ($N=1$)
- Statistical power for granular per-family evasion testing on these 8 families is impaired.
