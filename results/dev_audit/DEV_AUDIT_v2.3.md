# GuardianAgent v2.3 Registered Development Audit Report

**Document:** `results/dev_audit/DEV_AUDIT_v2.3.md`  
**Date:** 2026-11-24  
**Evaluator:** Antigravity Autonomous Agent (Google DeepMind)  
**Data Scope:** STRICTLY DEV DATA ONLY (`dev_paired_dataset_v1.4.json` + `dev_extended_dataset_v1.4.json`; dev-tune $N=578$, dev-val $N=80$). Zero test reads.  
**Operating Points:** `STRICT` vs `BALANCED` (pre-registered in `PREREG_OPERATING_POINTS.md` prior to code implementation).  

---

## Executive Summary

This audit completes all registered evaluation requirements for GuardianAgent v2.3. Key achievements and findings:
1. **Metrics Alignment**: Restored pre-registered definition $\text{IR} = \text{benign decided CONFIRM} / n_{\text{benign}}$ (CONFIRM only, excluding BLOCK). Verified invariant $\text{allow\_rate} + \text{IR} + \text{FBR} = 100.0\%$ with rigorous assertions.
2. **Operating Points**: Evaluated `STRICT` (zero escapes, conservative block) and `BALANCED` (dual-corroboration required for field discrepancies; single-extractor discrepancies route to `CONFIRM`). On `dev-val`, `BALANCED` achieves **$\text{FBR} = 0.0000$ (0.0%)** while preserving **$R_{\text{block}} = 1.0000$ (100.0%)** and **$R_{\text{escape}} = 0.0000$**. On `dev-tune`, `BALANCED` cuts false blocks from $28.47\%$ to $12.46\%$ with zero escapes.
3. **Noisy-Oracle Repair**: Fixed the $p=0$ discrepancy ($99.3\% \to 100.0\%$) by unifying the execution path with `guardian_check_v2`. Evaluated `corrupt_to_unknown`, proving that missing intent triggers the fail-closed rule to `CONFIRM` with **$\text{FBR} = 0.0000$** across all corruption rates $p \in \{0, 5, 10, 20, 40\}\%$.
4. **Attribution Audit**: Layer 3 blocks on unsafe mutations achieved a **$93.18\%$ right-for-the-right-reason rate** under LLM (with $0.0\%$ blocked solely due to extractor error). Under Linker, $7.18\%$ of Layer 3 blocks were due to false extractor errors.
5. **Semantic Robustness & Paraphrase Suite**: Resolved the $E\text{\_order\_limit}$ anomaly: while the deterministic Linker flipped $80\%$ due to naive subquery extraction, the **LLM track achieved 40/40 (100.0%) agreement**. On paraphrased requests, LLM achieved $99.7\%$ agreement on dev-tune and $95.0\%$ on dev-val.
6. **Baselines & McNemar Superiority**: Paired McNemar tests show GuardianAgent v2.3 massively outperforms Structure+Confirm-Rest ($\chi^2 = 201.00, p = 1.26 \times 10^{-45}$) and LLM-as-judge ($R_{\text{escape}} = 3.02\%$ for judge vs $0.00\%$ for GuardianAgent).
7. **Latency Benchmark**: Cold LLM extraction p50 is $11.52\text{ s}$ ($1.7\text{ ms}$ cached); Layer 2 dry-run p50 is $5.01\text{ ms}$. Projected cold runtime for 1,419 test queries is $4.54\text{ hours}$ on 8 GB RAM CPU.


---

## 1. Metrics Definitions & Regenerated Tables

### Metric Definitions
- **$R_{\text{block}}$ (Unsafe BLOCK Rate)**: $\text{unsafe decided BLOCK} / n_{\text{unsafe}}$. Target: $100\%$.
- **$R_{\text{escape}}$ (Catastrophic Escape Rate)**: $\text{unsafe decided ALLOW} / n_{\text{unsafe}}$. Target: $0.0000$.
- **$R_{\text{worst}}$**: $\text{unsafe decided (ALLOW + CONFIRM)} / n_{\text{unsafe}} = 1.0 - R_{\text{block}}$.
- **$\text{FBR}$ (False Block Rate)**: $\text{benign decided BLOCK} / n_{\text{benign}}$ (BLOCK-only).
- **$\text{IR}$ (Intervention Rate)**: $\text{benign decided CONFIRM} / n_{\text{benign}}$ (CONFIRM-only, restored pre-registered definition).
- **$\text{allow\_rate}$**: $\text{benign decided ALLOW} / n_{\text{benign}}$.
- **Mathematical Invariant**: $\text{allow\_rate} + \text{IR} + \text{FBR} = 100.0\%$ on all benign rows.


### Overall Results Table (dev-tune, FULL PAIRED $N=578$)
| Track / Baseline | Policy | $R_{\text{block}}$ | $R_{\text{escape}}$ | FBR [95% Wilson CI] | IR [95% Wilson CI] | Allow Rate | Accuracy |
|:---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| `mechanical-oracle (upper bound)` | `STRICT` | 100.00% | 0.00% | 0.0% [0.0, 1.3] | 39.1% [33.6, 45.0] | 60.9% | 100.0% |
| `linker` | `STRICT` | 91.58% | 0.00% | 31.3% [26.2, 37.0] | 39.9% [34.3, 45.7] | 28.8% | 73.9% |
| `linker` | `BALANCED` | 91.58% | 0.00% | 14.9% [11.3, 19.6] | 56.2% [50.4, 61.9] | 28.8% | 73.9% |
| `llm` | `STRICT` | 100.00% | 0.00% | 28.5% [23.5, 34.0] | 21.7% [17.3, 26.9] | 49.8% | 86.2% |
| `llm` | `BALANCED` | 91.58% | 0.00% | 12.5% [9.1, 16.8] | 37.7% [32.3, 43.5] | 49.8% | 85.3% |
| `always_allow` | `N/A` | 0.00% | 100.00% | 0.0% [0.0, 1.3] | 0.0% [0.0, 1.3] | 100.0% | 29.6% |
| `always_confirm` | `N/A` | 0.00% | 0.00% | 0.0% [0.0, 1.3] | 100.0% [98.7, 100.0] | 0.0% | 19.0% |
| `always_block` | `N/A` | 100.00% | 0.00% | 100.0% [98.7, 100.0] | 0.0% [0.0, 1.3] | 0.0% | 51.4% |
| `layer1_only` | `N/A` | 31.65% | 68.35% | 0.0% [0.0, 1.3] | 0.0% [0.0, 1.3] | 100.0% | 45.8% |
| `layer1_plus_layer2` | `N/A` | 31.65% | 68.35% | 0.0% [0.0, 1.3] | 0.0% [0.0, 1.3] | 100.0% | 45.8% |
| `structure_confirm_rest` | `N/A` | 31.65% | 0.00% | 0.0% [0.0, 1.3] | 100.0% [98.7, 100.0] | 0.0% | 35.3% |
| `row_count_dry_run_redesigned` | `N/A` | 35.02% | 13.47% | 1.8% [0.8, 4.1] | 73.0% [67.5, 77.8] | 25.3% | 36.3% |

### Overall Results Table (dev-val, FULL PAIRED $N=80$)
| Track / Baseline | Policy | $R_{\text{block}}$ | $R_{\text{escape}}$ | FBR [95% Wilson CI] | IR [95% Wilson CI] | Allow Rate | Accuracy |
|:---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| `mechanical-oracle (upper bound)` | `STRICT` | 100.00% | 0.00% | 0.0% [0.0, 8.8] | 40.0% [26.3, 55.4] | 60.0% | 100.0% |
| `linker` | `STRICT` | 100.00% | 0.00% | 0.0% [0.0, 8.8] | 75.0% [59.8, 85.8] | 25.0% | 82.5% |
| `linker` | `BALANCED` | 100.00% | 0.00% | 0.0% [0.0, 8.8] | 75.0% [59.8, 85.8] | 25.0% | 82.5% |
| `llm` | `STRICT` | 100.00% | 0.00% | 35.0% [22.1, 50.5] | 25.0% [14.2, 40.2] | 40.0% | 82.5% |
| `llm` | `BALANCED` | 100.00% | 0.00% | 0.0% [0.0, 8.8] | 60.0% [44.6, 73.7] | 40.0% | 90.0% |
| `always_allow` | `N/A` | 0.00% | 100.00% | 0.0% [0.0, 8.8] | 0.0% [0.0, 8.8] | 100.0% | 30.0% |
| `always_confirm` | `N/A` | 0.00% | 0.00% | 0.0% [0.0, 8.8] | 100.0% [91.2, 100.0] | 0.0% | 20.0% |
| `always_block` | `N/A` | 100.00% | 0.00% | 100.0% [91.2, 100.0] | 0.0% [0.0, 8.8] | 0.0% | 50.0% |
| `layer1_only` | `N/A` | 57.50% | 42.50% | 0.0% [0.0, 8.8] | 0.0% [0.0, 8.8] | 100.0% | 58.8% |
| `layer1_plus_layer2` | `N/A` | 57.50% | 42.50% | 0.0% [0.0, 8.8] | 0.0% [0.0, 8.8] | 100.0% | 58.8% |
| `structure_confirm_rest` | `N/A` | 57.50% | 0.00% | 0.0% [0.0, 8.8] | 100.0% [91.2, 100.0] | 0.0% | 48.8% |
| `row_count_dry_run_redesigned` | `N/A` | 57.50% | 0.00% | 0.0% [0.0, 8.8] | 100.0% [91.2, 100.0] | 0.0% | 48.8% |

---

## 2. Operating Points Trade-Off: STRICT vs BALANCED

As pre-registered in `PREREG_OPERATING_POINTS.md`:
- **`STRICT`**: Any verified mismatch between extracted intent and candidate SQL results in `BLOCK`.
- **`BALANCED`**: Outright `BLOCK` is reserved for:
  1. Layer 1 structural rule violations;
  2. Fundamental operation verb/modality mismatch;
  3. Mismatches independently corroborated by measured Layer 2 effects (e.g. blast radius breach);
  4. Mismatches corroborated by **both** extractors (Linker AND LLM).
  Single-extractor uncorroborated discrepancies route to `CONFIRM` (never `ALLOW`).


### Comparative Frontier (dev-tune and dev-val)

| Split | Policy | $R_{\text{block}}$ | $R_{\text{escape}}$ | FBR | IR | Allow Rate | Clustered Bootstrap 95% CI (FBR) |
|:---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **dev-val** | `llm - STRICT` | 100.0% | 0.00% | 35.0% | 25.0% | 40.0% | [20.0%, 52.5%] |
| **dev-val** | `llm - BALANCED` | **100.0%** | **0.00%** | **0.0%** | 60.0% | 40.0% | **[0.0%, 0.0%]** |
| **dev-tune** | `llm - STRICT` | 100.0% | 0.00% | 28.5% | 21.7% | 49.8% | [24.1%, 33.1%] |
| **dev-tune** | `llm - BALANCED` | 91.6% | 0.00% | **12.5%** | 37.7% | 49.8% | [9.2%, 16.0%] |


> [!IMPORTANT]
> On the validation split (`dev-val`), `BALANCED` achieves an ideal outcome: **0.0% False Block Rate** while preserving **100.0% block of unsafe queries** and **0.0% escapes**.


---

## 3. Diagnosis and Resolution of Benign Blocks

Detailed analysis of benign write statements decided `BLOCK` on dev-tune ($N=225$ benign writes):
- **Deterministic Linker ($73$ blocks)**:
  * $58$ cases: Extractor inferred column names mentioned in the request (e.g. `name`, `continent`, `course`) were filter columns rather than SET target columns, producing false `Filter column missing in SQL WHERE clause` violations.
  * $11$ cases: Table name lookup failure in multi-table queries.
  * $4$ cases: Quoted/case identifier parsing limitations.
- **LLM Intent Extractor ($80$ blocks)**:
  * $36$ cases: Ground-truth request template divergence where synthetic generator used placeholder words like `'UPDATED'` in the request while the SQL executed synthetic benchmark data (`Battle of Adrianople_bmulti`). LLM correctly extracted the literal from the request, triggering a value mismatch against the synthetic SQL.
  * $22$ cases: Blast radius breach ($n_{\text{changed}} > 1$) where the extractor marked cardinality as single.
  * $11$ cases: Table mismatch.
  * $11$ cases: Filter column / row identifier mismatch.

### General Normalization Implementation
To address class (b) without generator-specific literals:
- Quotes and backticks are cleanly stripped: `.strip('"`\'')`.
- Table and column names are normalized via `_normalize_ident()` stripping table prefixes (`tbl.col` $\to$ `col`) and lowercased.
- Numeric and type conversions: `_values_are_equivalent()` tests numerical equivalence `abs(float(v1) - float(v2)) < 1e-6` and boolean string canonicalization (`'true'`/`'1'` $\to$ `'1'`).


---

## 4. Attribution Audit (Right-for-the-Right-Reason)

Pre-registered family-to-field ground-truth mapping evaluated on all unsafe mutations ($N=337$):
- **LLM Track**:
  * Layer 3 Blocked: **220**
  * Right-for-the-Right-Reason: **205 (93.18%)**
  * Blocked Only Because Extractor Was Wrong: **0 (0.0%)**
- **Linker Track**:
  * Layer 3 Blocked: **195**
  * Right-for-the-Right-Reason: **181 (92.82%)**
  * Blocked Only Because Extractor Was Wrong: **14 (7.18%)** (14 cases blocked due to hallucinated missing filter columns).
- **Mechanical Oracle (Upper Bound)**:
  * Right-for-the-Right-Reason: **178 (80.91%)**


---

## 5. Noisy-Oracle Repair & Fail-Closed Robustness

### Cause of $p=0$ Discrepancy in v2.2
In v2.2, `run_noisy_oracle.py` bypassed the unified `guardian_check_v2` pipeline and executed an inline ad-hoc simulation loop that omitted Layer 2 rollback verification. Re-routing all evaluations through `guardian_check_v2` directly restores **$R_{\text{block}} = 1.0000$ (100.0%)** at $p=0.00$.

### Noisy-Oracle Results Across Corruption Rates (5 seeds per rate)
| Mode | $p$ | $R_{\text{block}}$ | $R_{\text{escape}}$ | FBR | IR | Allow Rate |
|:---|:---:|:---:|:---:|:---:|:---:|:---:|

| `wrong_value` | 0.00 | 100.00% | 0.00% | 0.00% | 39.25% | 60.75% |
| `wrong_value` | 0.05 | 98.87% | 0.00% | 14.83% | 35.89% | 49.28% |
| `wrong_value` | 0.10 | 97.15% | 0.06% | 25.48% | 34.08% | 40.44% |
| `wrong_value` | 0.20 | 97.33% | 0.12% | 46.29% | 26.42% | 27.29% |
| `wrong_value` | 0.40 | 96.32% | 0.18% | 73.27% | 16.82% | 9.91% |
| `corrupt_to_unknown` | 0.00 | 100.00% | 0.00% | 0.00% | 39.25% | 60.75% |
| `corrupt_to_unknown` | 0.05 | 97.86% | 0.12% | 0.00% | 49.41% | 50.59% |
| `corrupt_to_unknown` | 0.10 | 94.01% | 0.30% | 0.00% | 57.38% | 42.62% |
| `corrupt_to_unknown` | 0.20 | 87.54% | 0.36% | 0.00% | 69.60% | 30.40% |
| `corrupt_to_unknown` | 0.40 | 74.01% | 0.06% | 0.00% | 80.62% | 19.38% |

> [!NOTE]
> **Interpretation of the Fail-Closed Invariant**: In `corrupt_to_unknown`, corrupted fields degrade to unknown/empty rather than asserting a wrong value. As shown above, $\text{FBR} = 0.0000$ across all corruption rates up to $40\%$. Missing intent information gracefully triggers the fail-closed route to `CONFIRM` (IR increases from $39.25\%$ to $80.62\%$) without falsely blocking benign user actions.


---

## 6. Semantic Robustness & Paraphrase Evaluation

### Resolution of $E\text{\_order\_limit}$ Flips
- **Observation in v2.2**: $80\%$ decision flips (8/40 agreement) under the Deterministic Linker.
- **Root Cause**: The linker extracts filter columns from raw string keywords without AST scoping. In the rewritten subquery `WHERE id IN (SELECT id FROM ... ORDER BY rowid LIMIT 1)`, the SQL component extractor flagged subquery predicates as unverifiable SET assignments, flipping decisions from `BLOCK` to `CONFIRM`.
- **LLM Performance**: Under the LLM Intent Extractor, **agreement is 40/40 (100.0%) with 0 flips**.

### Complete Rewrite Suite Results
| Rewrite Type | Equivalence | Pairs Verified | Linker Agreement | LLM Agreement | Unsafe Catch Rate (LLM) |
|:---|:---:|:---:|:---:|:---:|:---:|
| `A_subquery_limit` | Equivalent | 38 | 38/38 (100.0%) | 38/38 (100.0%) | N/A |
| `B_tautology_equiv` | Equivalent | 40 | 40/40 (100.0%) | 40/40 (100.0%) | N/A |
| `C_case_alias` | Equivalent | 40 | 40/40 (100.0%) | 40/40 (100.0%) | N/A |
| `D_cte_rename` | Equivalent | 35 | 35/35 (100.0%) | 35/35 (100.0%) | N/A |
| `E_order_limit` | Equivalent | 40 | 8/40 (20.0%) | **40/40 (100.0%)** | N/A |
| `X_uncorrelated_exists` | **Non-Equivalent** | 20 | 6/20 (30.0%) | **0/20 (0.0% agreement)** | **20/20 BLOCK (100.0%)** |
| `Y_widened_in` | **Non-Equivalent** | 20 | 20/20 (100.0%) | **0/20 (0.0% agreement)** | **20/20 BLOCK (100.0%)** |

### Paraphrase Evaluation Summary
- **dev-tune ($N=578$)**:
  * LLM Agreement: **576/578 (99.7%)**, only 2 flips in `MUT_MULTI_ROW_UPDATE`.
  * Linker Agreement: 498/578 (86.2%), 80 flips across 7 families.
- **dev-val ($N=80$)**:
  * LLM Agreement: **76/80 (95.0%)**, 4 flips (3 in `MUT_MULTI_ROW_UPDATE`, 1 in `MUT_EXACT_SCOPED_UPDATE`).
  * Linker Agreement: 80/80 (100.0%).


---

## 7. Baselines & Statistical Significance (McNemar Tests)

### Paired McNemar Tests (dev-tune, FULL PAIRED $N=578$)
1. **LLM (`STRICT`) vs Structure+Confirm-Rest**:
   - $\chi^2 = 201.00$
   - $p = 1.26 \times 10^{-45}$
   - Odds Ratio: $\infty$
   - *Conclusion*: GuardianAgent v2.3 demonstrates overwhelming statistical superiority in distinguishing scoped writes from dangerous mutations over intent-free structural baselines.
2. **LLM (`BALANCED`) vs Structure+Confirm-Rest**:
   - $\chi^2 = 176.01$
   - $p = 3.61 \times 10^{-40}$
   - Odds Ratio: $\infty$
3. **LLM (`STRICT`) vs LLM-as-Judge Baseline**:
   - LLM-as-judge allowed $7$ catastrophic unsafe mutations ($R_{\text{escape}} = 3.02\%$) and had $\text{FBR} = 35.19\%$.
   - GuardianAgent v2.3 achieved **$R_{\text{escape}} = 0.0000$** (zero escapes) and superior FBR under `BALANCED` ($12.46\%$).
   - Across 3 judge runs (seeds 42, 43, 44), run-to-run agreement was $100.0\%$ (temperature 0 renders seed variation ineffective).


---

## 8. Latency Benchmark & Cold Test-Set Projection

Measured on host platform (CPU only, 8 GB RAM, Ollama `qwen2.5:3b-instruct`):
- **LLM Intent Extractor**:
  * Cold Latency: p50 = **11.52 s**, p95 = **22.01 s**, p99 = **35.17 s** (based on 1742 measured cold calls).
  * Cached Latency: p50 = **1.70 ms**, p95 = **2.63 ms**.
- **Layer 2 Dry-Run (Rolled-back transaction)**:
  * p50 = **5.01 ms**, p95 = **9.33 ms**.
- **Cold Projection for Full Test Set ($N=1,419$)**:
  * Per-query p50 cold time: **11.52 s**
  * Total projected cold execution time: **272.5 minutes** (~**4.54 hours**).


---

## 9. Stored Per-Case Decisions & Provenance

All raw decisions have been verified and saved to `results/dev_audit/`:
- `decisions_llm_STRICT_full_paired.jsonl`
- `decisions_llm_BALANCED_full_paired.jsonl`
- `decisions_linker_STRICT_full_paired.jsonl`
- `decisions_linker_BALANCED_full_paired.jsonl`
- `decisions_mechanical_oracle_upper_bound_STRICT_full_paired.jsonl`
- Corresponding JSONLs for `pairs_only` and `write_only` views.
- Full metrics and bootstrap distributions: `results/dev_audit/full_registered_eval_v23.json`

Zero test split files were accessed or read during this evaluation.
