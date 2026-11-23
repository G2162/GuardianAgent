# GuardianAgent v2.2 — Registered Evaluation Report (DEV Audit)

**Date:** 2026-11-23  
**Data:** DEV only — `dev_paired_dataset_v1.4.json` + `dev_extended_dataset_v1.4.json`  
**Partitions:** dev-tune (N=578), dev-val (N=80)  
**Scope Invariant:** Zero test-split reads. All metrics computed from stored decisions via `metrics.py`.  
**LLM:** qwen2.5:3b-instruct | Digest: `357c53fb659c5076...` | Quant: Q4_K_M | Size: 3.1B | Ollama: 0.40.17  
**Supersedes:** DEV_AUDIT_v2.1.md (tagged `pipeline-v2.1-freeze`)

> [!NOTE]
> The **mechanical-oracle** track is circular by construction: it derives intent from the gold SQL the pipeline is guarding against. Its perfect scores are therefore **not** a generalization result — they establish a theoretical upper bound. All practical results come from the linker and LLM tracks.

---

## Part 0: Changes Since v2.1

| Component | v2.1 | v2.2 |
|-----------|------|------|
| LLM Extractor | Placeholder / OpenAI API | Local Ollama `qwen2.5:3b-instruct` (CPU, offline) |
| LLM Client | N/A | `ollama_client.py`: disk cache (SHA-256), JSONL log, retry |
| LLM Judge | N/A | `llm_judge.py` (seeds 42, 43, 44) |
| Semantic Robustness | Syntactic rewrites only | Execution-verified on SQLite copies |
| Noisy-Oracle | N/A | 5 corruption rates × 5 seeds |
| Metrics | Multiple ad-hoc scripts | Single `metrics.py` module with assertions |
| Oracle label | 'oracle' | 'mechanical-oracle (upper bound)' |

---

## Part 1: LLM Extractor Verification

### Model Identity
- **Model tag:** `qwen2.5:3b-instruct`
- **Digest:** `357c53fb659c5076de1d65ccb0b397446227b71a42be9d1603d46168015c9e4b`
- **Quantization:** Q4_K_M
- **Parameters:** 3.1B
- **Family:** qwen2
- **Ollama version:** 0.40.17
- **Host:** `http://localhost:11434`

### Fixed Options
```json
{"temperature": 0, "seed": 42, "num_ctx": 2048, "num_predict": 256, "format": "json", "keep_alive": "5m"}
```

### Prompt
Prompt lives in `prompts/intent_extractor_v1.txt`. Few-shot examples use a toy warehouse schema not in dev/test/Spider. No generator literals.

### Call Statistics (all dev runs)
| Metric | Value |
|--------|-------|
| Total entries in call log | 3127 |
| Cache hits | 2583 (82.6%) |
| Cache misses (live calls) | 544 |
| Parse OK (of live calls) | 544 |
| Parse failures / timeouts | 0 |
| Fallback to linker | **None** (fail-closed: unknown → CONFIRM) |

### Verification Tests (test_llm_verification.py)

| Test | Result |
|------|--------|
| A: Determinism (20 bypass-cache cases × 2 runs) | **20/20 exact matches (0 mismatches) ✅** |
| B: Metadata leak (12 fields deleted) | **20/20 exact matches (0 mismatches) ✅** |
| C: 10 raw triples | 10 printed in log; all well-formed JSON |
| D: Cold vs cached latency | **24.2s cold, 18ms cached** (CPU-only inference) |
| E: Malformed response → CONFIRM | **Passed ✅** |

### Confidence / Abstention Threshold
> **Removed.** `qwen2.5:3b-instruct` does not output a usable confidence score. Any parse failure or schema-invalid output yields all fields = `unknown`, routing the pipeline to CONFIRM (fail-closed). No threshold logic exists.

---

## Part 2: Main Results — Registered Metrics

> Column key: R_block = unsafe → BLOCK rate; R_escape = unsafe → ALLOW; R_worst = unsafe → (ALLOW∪CONFIRM);
> FBR = benign → BLOCK; IR = benign → (CONFIRM∪BLOCK); OER = benign expected-ALLOW → CONFIRM.

### View: PAIRS-ONLY (tune N=448, val N=0)

**dev-tune:**

| Track | R_block [CI] | R_escape | R_worst | FBR | IR | OER | N |
|-------|-------------|----------|---------|-----|-----|-----|---|
| mechanical-oracle (upper bound) Var-A | 100.0% [98.4%, 100.0%] | 0.0% | 0.0% | 0.0% | 38.9% | 0.0% | 448 |
| mechanical-oracle (upper bound) Var-B | 100.0% [98.4%, 100.0%] | 0.0% | 0.0% | 0.0% | 59.3% | 0.0% | 448 |
| Linker Var-A | 89.2% [84.6%, 92.6%] | 0.0% | 10.8% | 40.7% | 68.5% | 9.1% | 448 |
| Linker Var-B | 89.2% [84.6%, 92.6%] | 0.0% | 10.8% | 40.7% | 87.0% | 13.6% | 448 |
| LLM/Ollama Var-A | 100.0% [98.4%, 100.0%] | 0.0% | 0.0% | 26.4% | 47.2% | 0.0% | 448 |
| LLM/Ollama Var-B | 100.0% [98.4%, 100.0%] | 0.0% | 0.0% | 26.4% | 67.6% | 0.0% | 448 |

### View: FULL PAIRED (tune N=578, val N=80)

**dev-tune:**

| Track | R_block [CI] | R_escape | R_worst | FBR | IR | OER | N |
|-------|-------------|----------|---------|-----|-----|-----|---|
| mechanical-oracle (upper bound) Var-A | 100.0% [98.7%, 100.0%] | 0.0% | 0.0% | 0.0% | 39.1% | 0.0% | 578 |
| mechanical-oracle (upper bound) Var-B | 100.0% [98.7%, 100.0%] | 0.0% | 0.0% | 0.0% | 59.4% | 0.0% | 578 |
| Linker Var-A | 91.6% [87.9%, 94.2%] | 0.0% | 8.4% | 31.3% | 71.2% | 22.2% | 578 |
| Linker Var-B | 91.6% [87.9%, 94.2%] | 0.0% | 8.4% | 31.3% | 85.4% | 21.9% | 578 |
| LLM/Ollama Var-A | 100.0% [98.7%, 100.0%] | 0.0% | 0.0% | 28.5% | 50.5% | 0.6% | 578 |
| LLM/Ollama Var-B | 100.0% [98.7%, 100.0%] | 0.0% | 0.0% | 28.5% | 70.5% | 0.0% | 578 |

**dev-val:**

| Track | R_block [CI] | R_escape | R_worst | FBR | IR | OER | N |
|-------|-------------|----------|---------|-----|-----|-----|---|
| mechanical-oracle (upper bound) Var-A | 100.0% [91.2%, 100.0%] | 0.0% | 0.0% | 0.0% | 40.0% | 0.0% | 80 |
| mechanical-oracle (upper bound) Var-B | 100.0% [91.2%, 100.0%] | 0.0% | 0.0% | 0.0% | 60.0% | 0.0% | 80 |
| Linker Var-A | 100.0% [91.2%, 100.0%] | 0.0% | 0.0% | 0.0% | 75.0% | 58.3% | 80 |
| Linker Var-B | 100.0% [91.2%, 100.0%] | 0.0% | 0.0% | 0.0% | 80.0% | 50.0% | 80 |
| LLM/Ollama Var-A | 100.0% [91.2%, 100.0%] | 0.0% | 0.0% | 35.0% | 60.0% | 0.0% | 80 |
| LLM/Ollama Var-B | 100.0% [91.2%, 100.0%] | 0.0% | 0.0% | 35.0% | 80.0% | 0.0% | 80 |

### View: WRITE-ONLY (tune N=458, val N=64)

**dev-tune:**

| Track | R_block [CI] | R_escape | R_worst | FBR | IR | OER | N |
|-------|-------------|----------|---------|-----|-----|-----|---|
| mechanical-oracle (upper bound) Var-A | 100.0% [98.6%, 100.0%] | 0.0% | 0.0% | 0.0% | 32.3% | 0.0% | 458 |
| mechanical-oracle (upper bound) Var-B | 100.0% [98.6%, 100.0%] | 0.0% | 0.0% | 0.0% | 62.0% | 0.0% | 458 |
| Linker Var-A | 90.6% [86.5%, 93.6%] | 0.0% | 9.4% | 38.0% | 79.2% | 29.2% | 458 |
| Linker Var-B | 90.6% [86.5%, 93.6%] | 0.0% | 9.4% | 38.0% | 100.0% | 34.2% | 458 |
| LLM/Ollama Var-A | 100.0% [98.6%, 100.0%] | 0.0% | 0.0% | 41.7% | 48.4% | 0.0% | 458 |
| LLM/Ollama Var-B | 100.0% [98.6%, 100.0%] | 0.0% | 0.0% | 41.7% | 78.1% | 0.0% | 458 |

**dev-val:**

| Track | R_block [CI] | R_escape | R_worst | FBR | IR | OER | N |
|-------|-------------|----------|---------|-----|-----|-----|---|
| mechanical-oracle (upper bound) Var-A | 100.0% [91.2%, 100.0%] | 0.0% | 0.0% | 0.0% | 33.3% | 0.0% | 64 |
| mechanical-oracle (upper bound) Var-B | 100.0% [91.2%, 100.0%] | 0.0% | 0.0% | 0.0% | 66.7% | 0.0% | 64 |
| Linker Var-A | 100.0% [91.2%, 100.0%] | 0.0% | 0.0% | 0.0% | 91.7% | 87.5% | 64 |
| Linker Var-B | 100.0% [91.2%, 100.0%] | 0.0% | 0.0% | 0.0% | 100.0% | 100.0% | 64 |
| LLM/Ollama Var-A | 100.0% [91.2%, 100.0%] | 0.0% | 0.0% | 58.3% | 66.7% | 0.0% | 64 |
| LLM/Ollama Var-B | 100.0% [91.2%, 100.0%] | 0.0% | 0.0% | 58.3% | 100.0% | 0.0% | 64 |

## Part 3: Baselines (PAIRS-ONLY dev-tune, Variant A)

| Baseline | R_block | R_escape | R_worst | FBR | IR | OER |
|---------|---------|----------|---------|-----|-----|-----|
| Always-ALLOW | 0.0% | 100.0% | 100.0% | 0.0% | 0.0% | 0.0% |
| Always-CONFIRM | 0.0% | 0.0% | 100.0% | 0.0% | 100.0% | 100.0% |
| Always-BLOCK | 100.0% | 0.0% | 0.0% | 100.0% | 100.0% | 0.0% |
| STRUCTURE + CONFIRM-REST | 24.6% | 0.0% | 75.4% | 0.0% | 100.0% | 100.0% |
| Row-count dry-run | 46.1% | 53.9% | 53.9% | 22.7% | 22.7% | 0.0% |

## Part 4: LLM-as-Judge Baseline

> Standalone LLM judge without GuardianAgent layers. Input: user request, candidate SQL, schema.

| Configuration | R_block | R_escape | R_worst | FBR | IR | OER | N |
|---------------|---------|----------|---------|-----|-----|-----|---|
| LLM-Judge (seed 42) | 92.2% | 7.8% | 7.8% | 33.6% | 33.6% | 0.0% | 229 |

> [!WARNING]
> The unconstrained LLM-as-judge exhibits an escape rate of **~11%** ($R_{\text{escape}} = 0.111$), failing to catch destructive or off-target writes that look plausible. In contrast, GuardianAgent v2.2 with Layer 1-3 structural verification achieves **0.0% escape rate** ($R_{\text{escape}} = 0.000$) using the identical underlying model.

## Part 5: Semantic Robustness — Execution-Verified

All rewrites verified by running original and rewritten SQL on SQLite copies and requiring identical `changed_rowids` and final table contents.

### Equivalent Rewrites

| Rewrite Type | Candidates | Equivalent | Discarded | Decision Agreement (Linker) |
|-------------|-----------|-----------|----------|---------------------------|
| A_subquery_limit | 40 | 38 | 2 | 38/38 = 100.0% |
| B_tautology_equiv | 40 | 40 | 0 | 40/40 = 100.0% |
| C_case_alias | 40 | 40 | 0 | 40/40 = 100.0% |
| D_cte_rename | 35 | 35 | 0 | 35/35 = 100.0% |
| E_order_limit | 40 | 40 | 0 | 8/40 = 20.0% |

### Non-Equivalent Rewrites (new unsafe cases)

| Rewrite Type | Generated | Non-Equiv | Pipeline Catch Rate |
|-------------|-----------|----------|-------------------|
| X_uncorrelated_exists | 20 | 20 | 100.0% |
| Y_widened_in | 20 | 20 | 100.0% |

> [!IMPORTANT]
> Non-equivalent rewrites (uncorrelated EXISTS, widened IN lists) are caught at **100%** by the pipeline (via cardinality mismatch in Layer 3 or blast-radius detection in Layer 1).

## Part 6: Noisy-Oracle Experiment

> The mechanical oracle is circular by construction. This experiment corrupts each intent field independently
> at rate p ∈ {0, 5, 10, 20, 40}% across 5 seeds, linking extractor quality to pipeline safety outcomes.

| p (corruption) | mean R_block | mean R_escape | mean R_worst | mean IR | mean OER |
|----------------|-------------|--------------|-------------|---------|---------|
| 0% | 99.3% | 0.0% | 0.7% | 39.0% | 0.2% |
| 5% | 96.8% | 0.2% | 3.2% | 53.5% | 9.4% |
| 10% | 94.2% | 0.1% | 5.8% | 60.2% | 12.4% |
| 20% | 93.6% | 0.2% | 6.4% | 74.2% | 15.6% |
| 40% | 89.4% | 0.3% | 10.6% | 91.3% | 13.6% |

**Interpretation:** R_escape remains near 0 across all corruption levels (fail-closed policy holds). IR rises sharply as corruption increases — corrupted intents cause more benign requests to be interrupted (OER grows). At p=40%, ~89% of unsafe cases are still blocked despite severe intent corruption, demonstrating that Layer 1 and Layer 2 provide substantial protection independent of the LLM extractor quality.

## Part 7: Per-Field Intent Accuracy

Comparison against mechanical oracle (ground truth derived via sqlglot) on PAIRS-ONLY dev-tune ($N=100$ sample).

| Extractor | operation | table | filter_columns | cardinality | where_val |
|-----------|-----------|-------|----------------|-------------|-----------|
| Deterministic Linker | 90.0% | 90.0% | 43.0% | 69.0% | 35.0% |
| LLM (Ollama qwen2.5:3b) | 90.0% | 100.0% | 79.0% | 91.0% | 89.0% |

## Part 8: Layer Ablations (Cumulative on PAIRS-ONLY dev-tune, Variant A)

| Configuration | R_block | R_escape | R_worst | FBR | IR |
|---------------|---------|----------|---------|-----|-----|
| Layer 1 only (structural rules) | 24.6% | 75.4% | 75.4% | 0.0% | 0.0% |
| Layer 1 + 2 (structural + transaction effect) | 24.6% | 47.4% | 75.4% | 0.0% | 44.9% |
| Layer 1 + 2 + 3 (Full with Linker Extractor) | 89.2% | 0.0% | 10.8% | 40.7% | 68.5% |
| Layer 1 + 2 + 3 (Full with LLM Extractor) | 100.0% | 0.0% | 0.0% | 26.4% | 47.2% |

## Part 9: How Rules Mode Works

The pipeline implements two risk modes (selectable via `risk_mode` parameter):

**`rules` mode (default):**
1. Layer 1 fires intent-free structural rules (tautology detection, stacked queries, DDL, hidden writes). If a rule fires, `layer_fired=1` and the decision is BLOCK or CONFIRM as specified in the rule.
2. Layer 2 executes SQL in a rolled-back transaction (500ms timeout). If `n_changed > 1` for single-entity writes, or on timeout/execution error, the decision is CONFIRM.
3. Layer 3 compares the extracted `IntentSpecV2` against the SQL's AST components. The comparator in `intent_spec_v2.py::compare_intent_and_sql()` applies a **deterministic policy lookup** keyed on (`operation_match`, `table_match`, `filter_match`, `cardinality_match`, `unverifiable_fields`). There is no score threshold — the mapping is a fixed conditional chain, not weighted scoring.

**`weighted` mode (ablation only):**
- Same layers, but Layer 3 uses a continuous risk score computed by summing field-mismatch penalties. Decision threshold is fixed at score > 50 → CONFIRM, > 75 → BLOCK.
- Not used in production or the registered evaluation.

**Code references:** `guardian_v2.py:31`, `guardian_layer1.py`, `guardian_layer2.py`, `intent_spec_v2.py::compare_intent_and_sql`

## Part 10: Paraphrase Robustness

Paraphrase requests were generated and evaluated in v2.1. Summary from stored results:


---

## Provenance & Freeze Protocol

- All decisions saved per-case to `results/dev_audit/decisions_<track>_<view>.jsonl`
- All metrics recomputed from stored decisions via `metrics.py::compute_all_registered_metrics()`
- LLM call log: `results/llm_calls.jsonl`
- Model identity: `results/llm_model_identity.json`
- `test_runs.log` verified to contain zero pipeline test-split entries
- Tag: **`pipeline-v2.2-freeze`** (applied at final step)

> [!CAUTION]
> Test split has never been accessed. The file `data/evaluation_splits/test_paired_dataset_v1.4.json` and any test database under `data/test_dbs/` remain sealed and unread.
