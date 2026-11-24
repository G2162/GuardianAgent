# Pre-Registration of GuardianAgent v2.3 Operating Points

**Document:** `PREREG_OPERATING_POINTS.md`  
**Date:** 2026-11-24  
**Status:** Pre-registered Protocol (committed strictly BEFORE implementation of code changes)  
**Target:** Registered Evaluation of GuardianAgent v2.3 on DEV and TEST Splits  

---

## 1. Motivation and Rationale

GuardianAgent's Layer 3 comparator evaluates consistency between extracted user intent (`IntentSpecV2`) and candidate SQL AST components. In previous iterations (v2.1 and v2.2), Layer 3 operated under a single deterministic policy lookup where any verified mismatch between intent and SQL resulted in a `BLOCK` decision.

While this policy guarantees an escape rate to `ALLOW` of $0.0000$ ($R_{\text{escape}} = 0.0000$), it incurs an elevated False Block Rate ($\text{FBR} \approx 26.4\%\text{--}40.7\%$) on benign statements whenever an extractor experiences schema grounding or parsing inaccuracies on benign writes. Because benign statements decided `CONFIRM` prompt an interactive human review rather than causing silent destruction or complete termination, routing ambiguous or single-extractor discrepancies to `CONFIRM` provides an attractive operational trade-off: **zero escapes, dramatically lower false blocks, and controlled operator review**.

To prevent post-hoc policy tuning or test-set optimization, we formally pre-register **two fixed operating points** for Layer 3. Both operating points will be evaluated and reported on DEV splits and on the cryptographically sealed TEST split. Neither operating point is chosen after seeing test results.

---

## 2. Formal Specification of Operating Points

### Policy A: `STRICT` (Reference / Conservative Baseline)
`STRICT` preserves the exact behavior of GuardianAgent v2.2:
1. **Layer 1:** Any intent-free structural rule violation (tautologies, stacked queries, DDL, hidden writes) fires `BLOCK` or `CONFIRM` as defined by the structural rule.
2. **Layer 2:** Execution failure, timeout, or blast-radius breach on single-row writes ($n_{\text{changed}} > 1$) in a rolled-back transaction fires `CONFIRM`.
3. **Layer 3:** 
   - Any verified mismatch between intent and SQL (operation verb, target table, filter columns, set assignments, or cardinality) results in **`BLOCK`**.
   - Any write with unknown or unverifiable required fields fails closed to **`CONFIRM`**.
   - A decision of **`ALLOW`** requires every verifiable field to match AND measured cardinality to match the request.

---

### Policy B: `BALANCED` (Dual-Corroboration & Risk-Calibrated Layer 3)
`BALANCED` reduces false blocks while strictly preserving fail-closed safety by requiring high-confidence evidence before issuing an outright `BLOCK`:
1. **Layer 1 Invariant:** All Layer 1 structural rule violations that fire `BLOCK` remain **`BLOCK`** (no relaxation of intent-free structural rules).
2. **Verb & Modality Invariant:** Any fundamental operation verb mismatch (e.g. intent is `SELECT` or `UPDATE` but SQL is `DELETE` or `DROP`) immediately fires **`BLOCK`**.
3. **Dual-Extractor Corroboration:** For field-level discrepancies (table name, filter columns, set values, or cardinality):
   - A mismatch fires **`BLOCK`** if it is corroborated by **both** extractors (the Deterministic Linker AND the LLM Intent Extractor agree on the discrepancy), OR if it is independently supported by measured Layer 2 effects (e.g., measured affected rows contradict single-row intent).
   - If a discrepancy rests on a **single extractor** while the other extractor either abstains/is unknown or agrees with the SQL, the decision is calibrated to **`CONFIRM`** (never `ALLOW`).
4. **Fail-Closed Write Safety:** Any write with unknown, unverifiable, or conflicting fields defaults to **`CONFIRM`**, never `ALLOW`. An `ALLOW` decision strictly requires affirmative match across all verifiable fields.

---

## 3. Evaluation & Reporting Commitment

1. **Both operating points (`STRICT` and `BALANCED`) will be reported side-by-side** on dev-tune ($N=578$), dev-val ($N=80$), and test splits across all registered metrics:
   - $R_{\text{block}}$ (Unsafe BLOCK rate)
   - $R_{\text{worst}}$ (Unsafe ALLOW + CONFIRM rate)
   - $R_{\text{escape}}$ (Unsafe ALLOW rate)
   - $\text{FBR}$ (Benign BLOCK rate)
   - $\text{IR}$ (Benign CONFIRM rate)
   - $\text{allow\_rate}$ (Benign ALLOW rate)
   - $95\%$ Wilson confidence intervals and 1,000-sample database-clustered bootstrap confidence intervals.
2. **No Post-Hoc Selection:** Neither operating point will be selected or modified after inspecting test data.
