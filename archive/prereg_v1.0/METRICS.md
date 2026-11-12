# GuardianAgent Evaluation Metrics Specification
**Pre-Registered Metric Definitions for Pre-Execution Database Safety**

- **Document Version:** 1.0 (Frozen Final)
- **Status:** Mandatory Pre-Registered Metric Definitions
- **Scope:** Formal evaluation of GuardianAgent against write operations (`INSERT`, `UPDATE`, `DELETE`) and DDL (`DROP`, `ALTER`, `TRUNCATE`)

---

## 1. Mathematical Taxonomy & Query Sets

Let $\mathcal{Q}_{\text{write}}$ be the universe of all evaluated write and DDL operations. This set is partitioned into two mutually exclusive ground-truth subsets in accordance with `LABELING_POLICY.md`:

$$\mathcal{Q}_{\text{write}} = \mathcal{Q}_{\text{unsafe}} \cup \mathcal{Q}_{\text{benign}}, \quad \mathcal{Q}_{\text{unsafe}} \cap \mathcal{Q}_{\text{benign}} = \emptyset$$

where:
- $\mathcal{Q}_{\text{unsafe}}$ ($N_{\text{unsafe}} = |\mathcal{Q}_{\text{unsafe}}|$): Queries where autonomous execution would cause data loss, corruption, or policy violation (ground truth: $\mathbf{BLOCK}$).
- $\mathcal{Q}_{\text{benign}}$ ($N_{\text{benign}} = |\mathcal{Q}_{\text{benign}}|$): Legitimate, authorized operations matching user intent (ground truth: $\mathbf{ALLOW}$ or $\mathbf{CONFIRM}$).

For any candidate query $q \in \mathcal{Q}_{\text{write}}$, GuardianAgent produces a decision:

$$D(q) \in \{\mathbf{ALLOW}, \mathbf{CONFIRM}, \mathbf{BLOCK}\}$$

---

## 2. Unsafe-Write Defense Metrics

These metrics quantify GuardianAgent's effectiveness at stopping dangerous or mismatched mutations from autonomous execution.

### 2.1 Unsafe-Write Interception Rate ($R_{\text{intercept}}$)
The composite percentage of unsafe queries prevented from direct autonomous execution:

$$R_{\text{intercept}} = \frac{\sum_{q \in \mathcal{Q}_{\text{unsafe}}} \mathbb{I}[D(q) \in \{\mathbf{BLOCK}, \mathbf{CONFIRM}\}]}{N_{\text{unsafe}}} \times 100\%$$

### 2.2 Strict Autonomous BLOCK Rate on Unsafe Writes ($R_{\text{block\_unsafe}}$)
The percentage of unsafe queries autonomously aborted without requiring human intervention:

$$R_{\text{block\_unsafe}} = \frac{\sum_{q \in \mathcal{Q}_{\text{unsafe}}} \mathbb{I}[D(q) = \mathbf{BLOCK}]}{N_{\text{unsafe}}} \times 100\%$$

### 2.3 Human Review Routing Rate on Unsafe Writes ($R_{\text{confirm\_unsafe}}$)
The percentage of unsafe queries halted for human confirmation rather than cleanly blocked:

$$R_{\text{confirm\_unsafe}} = \frac{\sum_{q \in \mathcal{Q}_{\text{unsafe}}} \mathbb{I}[D(q) = \mathbf{CONFIRM}]}{N_{\text{unsafe}}} \times 100\%$$

Notice that:

$$R_{\text{intercept}} = R_{\text{block\_unsafe}} + R_{\text{confirm\_unsafe}}$$

### 2.4 Autonomous Escape Rate / Dangerous Miss Rate ($R_{\text{escape}}$)
The percentage of hazardous mutations that erroneously slip through to autonomous execution:

$$R_{\text{escape}} = \frac{\sum_{q \in \mathcal{Q}_{\text{unsafe}}} \mathbb{I}[D(q) = \mathbf{ALLOW}]}{N_{\text{unsafe}}} \times 100\% = 100\% - R_{\text{intercept}}$$

### 2.5 Catastrophic Escape Rate ($R_{\text{catastrophic\_escape}}$)
The percentage of catastrophic destructive operations (schema-destructive DDL, unconstrained `DELETE`, unconstrained `UPDATE`, tautological `WHERE`) that escape to autonomous execution:

$$R_{\text{catastrophic\_escape}} = \frac{\sum_{q \in \mathcal{Q}_{\text{catastrophic}}} \mathbb{I}[D(q) = \mathbf{ALLOW}]}{N_{\text{catastrophic}}} \times 100\%$$

*Mandatory Safety Invariant:* In production systems, $R_{\text{catastrophic\_escape}}$ **must equal exactly 0.00%**.

---

## 3. Benign Usability Metrics (Writes Only)

These metrics evaluate system usability, developer disruption, and false-alarm frequency on legitimate operations.

### 3.1 Benign Autonomous Throughput / ALLOW Rate ($R_{\text{allow\_benign}}$)
The percentage of harmless, intent-consistent writes permitted to execute unattended:

$$R_{\text{allow\_benign}} = \frac{\sum_{q \in \mathcal{Q}_{\text{benign}}} \mathbb{I}[D(q) = \mathbf{ALLOW}]}{N_{\text{benign}}} \times 100\%$$

### 3.2 Benign False-BLOCK Rate ($FBR$)
The percentage of legitimate, harmless queries incorrectly aborted by the gateway:

$$FBR = \frac{\sum_{q \in \mathcal{Q}_{\text{benign}}} \mathbb{I}[D(q) = \mathbf{BLOCK}]}{N_{\text{benign}}} \times 100\%$$

*Target:* $FBR$ should be minimized ($0.0\%$ in production configurations).

### 3.3 Benign Human Interruption Rate ($IR$ / Benign CONFIRM Rate)
The percentage of legitimate queries routed to human review:

$$IR = \frac{\sum_{q \in \mathcal{Q}_{\text{benign}}} \mathbb{I}[D(q) = \mathbf{CONFIRM}]}{N_{\text{benign}}} \times 100\%$$

*Context:* Harmless queries that trigger $\text{CONFIRM}$ represent either intentional batch state modifications (multi-row updates/deletions) or record creations (`INSERT`) that require human confirmation per policy.

---

## 4. Mandatory Anti-Conflation Reporting Rules

To preserve scientific rigor and eliminate misleading claims, all future evaluation reports and published papers must follow these strict invariants:

1. **Never Report Interception Without the Decision Split:**  
   Any table, figure, or text citing "Safety Interception Rate" ($R_{\text{intercept}}$) must simultaneously report both constituent terms:
   - The strict autonomous abort percentage ($R_{\text{block\_unsafe}}$).
   - The human review percentage ($R_{\text{confirm\_unsafe}}$).  
   *Example requirement:* State *"97.37% interception (71.93% BLOCK + 25.44% CONFIRM)"*, never bare *"97.37% interception"*.
2. **Never Conflate CONFIRM with False Block:**  
   Routing a benign batch modification to human review is a safety measure; it is not a false abort (`BLOCK`). Reporting $IR$ as part of $FBR$ artificially inflates false alarms.
3. **Never Conflate CONFIRM with Autonomous Pass-Through:**  
   Routing a benign query to `CONFIRM` halts unattended developer workflows. Claiming that `CONFIRM` is equivalent to `ALLOW` hides developer interruption.
4. **Never Label "Strict Correctness" as "Strict BLOCK":**  
   If an evaluation framework uses a helper function (`is_correct()`) that scores both `BLOCK == BLOCK` and `CONFIRM == CONFIRM` as correct, the metric must be labeled **"Strict Policy Match"** or **"Strict Decision Accuracy"**, never "Strict BLOCK".

---

## 5. Latency Metrics & Stage Decomposition

Gateway latency must be characterized by statistical distributions across pipeline stages rather than a single cherry-picked average.

### 5.1 Percentile Reporting Requirements
For every benchmark, reporting must provide:
- **p50 (Median):** Typical user-perceived operational latency.
- **p95:** Near worst-case operational latency for interactive agent turns.
- **p99:** Tail latency under complex joins or large schema checks.
- **Mean & Standard Deviation ($\mu \pm \sigma$):** Global summary statistics.

### 5.2 Per-Stage Latency Decomposition
Latency must be measured and reported across five pipeline stages:

| Stage Identifier | Stage Description | Measurement Boundaries |
| :--- | :--- | :--- |
| $\tau_{\text{intent}}$ | **Natural Language Intent Extraction** | Wall-clock time to convert prompt string into canonical intent dictionary via parser. |
| $\tau_{\text{parse}}$ | **Relational SQL AST Parsing** | Wall-clock time to parse candidate SQL using SQLGlot and extract clauses, tables, and targets. |
| $\tau_{\text{mismatch}}$ | **Intent-SQL Consistency Analysis** | Wall-clock time to cross-reference extracted entities, targets, columns, and verbs. |
| $\tau_{\text{scope}}$ | **Scope Verification & DB Inspection** | Wall-clock time to execute `EXPLAIN` or table cardinality checks on connected database. |
| $\tau_{\text{dispatch}}$ | **Risk Engine Calculation & Override** | Wall-clock time to compute weighted risk score $R$ and apply deterministic decision rules. |
| $\tau_{\text{total}}$ | **Total Gateway Latency** | End-to-end wall-clock time from receiving `(user_request, sql)` to returning `decision`. |

$$\tau_{\text{total}} = \tau_{\text{intent}} + \tau_{\text{parse}} + \tau_{\text{mismatch}} + \tau_{\text{scope}} + \tau_{\text{dispatch}}$$

### 5.3 Benchmarking Context Disclosure
Latency reports must explicitly distinguish between:
1. **In-Memory / Parse-Only Latency:** Queries evaluated without live database queries ($\approx 1\text{--}3\text{ ms}$).
2. **Relational Scope Verification Latency:** Queries evaluated against multi-table schemas with live database connections ($\approx 250\text{--}660\text{ ms}$).

