# Milestone 1 Run-Level Scoring Note

**Status:** Provisional  
**Dataset:** `stan-issue-run-level-evaluator-replays-v1`  
**Scope:** Run-level evaluators on the first frozen dataset

## 1. Objective

The goal is to replace a plain average of evaluator scores with a composite that accounts for:

- judge replay noise,
- variation between agent runs on the same case,
- variation between cases,
- evaluator score granularity,
- evaluator relevance to the intended decision, and
- uncertainty in the resulting scores and weights.

The method in this note is a first-pass scoring design. It is intended to produce interpretable
Milestone 1 results and a concrete method to test on additional datasets. It is not yet a production
merge-gating rule.

## 2. Data hierarchy and notation

For one evaluator \(e\), let:

- \(i \in \{1, \ldots, C\}\) index evaluation cases,
- \(a \in \{1, \ldots, A_i\}\) index independent agent runs within case \(i\),
- \(j \in \{1, \ldots, K_{ia}\}\) index judge replays of fixed run \(a\), and
- \(y_{eiaj} \in [0, 1]\) be the observed evaluator score.

The current dataset is balanced:

- \(C = 10\) cases,
- \(A = 2\) agent runs per case,
- \(K = 3\) judge replays per run, and
- four evaluators.

The run index is necessary. Without it, agent-run variation and judge-replay variation cannot be
separated.

## 3. Primary score aggregation

### 3.1 Collapse judge replays to a run score

For evaluator \(e\), case \(i\), and agent run \(a\), define the replay-mean score:

\[
\bar y_{eia\cdot}
=
\frac{1}{K}
\sum_{j=1}^{K} y_{eiaj}.
\]

The mean is the primary replay aggregation because its variance contribution has the direct form
\(v_{j,e}/K\). A replay median does not generally have variance \(v_{j,e}/K\), especially with three
replays and discrete evaluator scales.

The replay median will be reported as a sensitivity analysis:

\[
\tilde y_{eia\cdot}
=
\operatorname{median}_{j}(y_{eiaj}).
\]

If the median is used, its uncertainty will be estimated through the bootstrap rather than by
dividing judge variance by \(K\).

### 3.2 Collapse runs to a case score

Each case receives equal influence regardless of how many runs it contains:

\[
\bar y_{ei\cdot\cdot}
=
\frac{1}{A}
\sum_{a=1}^{A} \bar y_{eia\cdot}.
\]

### 3.3 Collapse cases to an evaluator suite score

The suite-level score for evaluator \(e\) is:

\[
\hat s_e
=
\frac{1}{C}
\sum_{i=1}^{C} \bar y_{ei\cdot\cdot}.
\]

Equal case weighting prevents a case with more runs or replays from receiving more influence.

## 4. Variance model

Each evaluator is modeled separately:

\[
y_{eiaj}
=
\mu_e
+ c_{ei}
+ a_{eia}
+ \epsilon_{eiaj},
\]

where:

- \(c_{ei}\) is the evaluator's case effect, with variance \(v_{c,e}\),
- \(a_{eia}\) is agent-run variation within a case, with variance \(v_{a,e}\), and
- \(\epsilon_{eiaj}\) is judge-replay noise on a fixed run, with variance \(v_{j,e}\).

The three components answer different questions:

- \(v_{j,e}\): How much does this judge wobble on an identical fixed run?
- \(v_{a,e}\): How much does the evaluated agent vary across runs of the same case?
- \(v_{c,e}\): How much does the evaluator distinguish among different cases?

This is a balanced nested random-effects approximation. It assumes the three effects are centered,
independent, and have a common variance within an evaluator.

## 5. Method-of-moments variance estimates

### 5.1 Judge replay variance

For each fixed run, compute the sample variance across its \(K\) judge replays:

\[
s^2_{j,eia}
=
\operatorname{Var}_{j}(y_{eiaj}).
\]

Pool these estimates across cases and runs:

\[
\hat v_{j,e}
=
\frac{1}{CA}
\sum_{i=1}^{C}
\sum_{a=1}^{A}
s^2_{j,eia}.
\]

### 5.2 Agent-run variance

Within each case, compute the sample variance across replay-mean run scores:

\[
s^2_{a,ei}
=
\operatorname{Var}_{a}(\bar y_{eia\cdot}).
\]

This observed variance contains both agent-run variance and residual judge noise:

\[
\mathbb{E}[s^2_{a,ei}]
=
v_{a,e}
+
\frac{v_{j,e}}{K}.
\]

The raw corrected estimate is:

\[
\hat v^{\mathrm{raw}}_{a,e}
=
\frac{1}{C}
\sum_{i=1}^{C}
s^2_{a,ei}
-
\frac{\hat v_{j,e}}{K}.
\]

The reported estimate is truncated at zero:

\[
\hat v_{a,e}
=
\max(0, \hat v^{\mathrm{raw}}_{a,e}).
\]

Both the raw and truncated values must be reported. A negative raw value indicates that the sample
is too small to resolve the component separately from judge noise.

### 5.3 Between-case variance

Compute the sample variance across case means:

\[
s^2_{c,e}
=
\operatorname{Var}_{i}(\bar y_{ei\cdot\cdot}).
\]

The observed variance of the case means contains residual run and judge noise:

\[
\mathbb{E}[s^2_{c,e}]
=
v_{c,e}
+
\frac{v_{a,e}}{A}
+
\frac{v_{j,e}}{AK}.
\]

The raw corrected estimate is:

\[
\hat v^{\mathrm{raw}}_{c,e}
=
s^2_{c,e}
-
\frac{\hat v^{\mathrm{raw}}_{a,e}}{A}
-
\frac{\hat v_{j,e}}{AK}.
\]

The reported estimate is:

\[
\hat v_{c,e}
=
\max(0, \hat v^{\mathrm{raw}}_{c,e}).
\]

The raw run-variance estimate is used in the raw case correction so that the method-of-moments
identity is preserved before nonnegative truncation. Again, both raw and truncated values must be
retained.

## 6. Reliability

Reliability here means repeatable case discrimination relative to agent and judge noise. It does not
establish that an evaluator measures the correct concept.

### 6.1 Single-measurement reliability

For comparison across datasets and evaluation budgets, report:

\[
r^{\mathrm{single}}_e
=
\frac{\hat v_{c,e}}
{\hat v_{c,e} + \hat v_{a,e} + \hat v_{j,e}}.
\]

This describes one agent run scored by one judge replay.

### 6.2 Current-design reliability

For a case score averaged over \(A\) runs and \(K\) judge replays per run, report:

\[
r^{\mathrm{design}}_e
=
\frac{\hat v_{c,e}}
{\hat v_{c,e}
+ \hat v_{a,e}/A
+ \hat v_{j,e}/(AK)}.
\]

The current-design reliability is used by the provisional weighting rule because it matches the
aggregation design used to produce \(\hat s_e\). If the denominator is zero, reliability is defined as
zero.

Single-measurement reliability should be used when comparing evaluator behavior across datasets with
different numbers of runs or replays.

## 7. Evaluator relevance and saturation

Reliability is not validity. An evaluator can be perfectly stable while measuring an irrelevant
property or returning the same score for every case.

The evaluator registry therefore supplies metadata that is separate from the variance estimates:

| Evaluator | Declared step | Coding-quality alignment | Composite status |
|---|---:|---|---|
| `ConcisenessEvaluator` | \(1/2\) | off-axis | provisional |
| `CoherenceEvaluator` | \(1/4\) | indirect | provisional |
| `FaithfulnessEvaluator` | \(1/4\) | indirect | provisional |
| `senior-review-strict` | \(1/24\) | on-axis | included |

For `senior-review-strict`, \(1/24\) is the raw rubric step. Its two-decimal output can display
adjacent gaps of approximately 0.04 or 0.05.

Every evaluator summary must also report:

- observed minimum and maximum,
- observed score variance,
- percentage of scores at the maximum,
- number of unique observed scores, and
- number of fixed runs that moved across replays.

These diagnostics make saturation visible. An evaluator with no corrected case variance receives
zero reliability even if its replay variance is also zero.

## 8. Provisional evaluator weights

Let \(\mathcal E^\ast\) be the evaluator set selected for a composite. For the Milestone 1 weighting
experiment, the primary candidate set contains all four observed evaluators. This keeps statistical
reliability separate from the product decision about whether an evaluator measures a relevant axis.
A strict-only anchor score will also be reported so the effect of adding provisional evaluators
remains visible.

For evaluator \(e \in \mathcal E^\ast\), let \(\Delta_e\) be its declared raw score step. Define the
unnormalized weight:

\[
q_e
=
\frac{r^{\mathrm{design}}_e}{\sqrt{\Delta_e}}.
\]

Normalize the weights:

\[
w_e
=
\frac{q_e}
{\sum_{t \in \mathcal E^\ast} q_t}.
\]

The square-root step adjustment is a heuristic. It discounts coarse evaluators without allowing a
fine-grained evaluator to dominate as aggressively as a full \(1/\Delta_e\) rule.

If every \(q_e\) is zero, the composite is undefined and the pipeline must report that no evaluator
demonstrated measurable case signal.

The direct plug-in vector can be unstable when corrected variance estimates reach the nonnegative
boundary at zero. It is therefore retained as a diagnostic rather than used as the provisional
Milestone 1 allocation. Let \(w_e^{(b)}\) be the normalized weight for evaluator \(e\) in bootstrap
replicate \(b\), and let \(\mathcal B^\ast\) contain the replicates where a weight vector is defined.
The bootstrap-stabilized provisional weight is:

\[
\bar w_e
=
\frac{1}{|\mathcal B^\ast|}
\sum_{b \in \mathcal B^\ast}
w_e^{(b)}.
\]

Because every defined bootstrap vector sums to one and the complete evaluator vector is resampled
together, the averaged vector also sums to one. This gives uncertain evaluators nonzero influence
when plausible resamples contain detectable signal, rather than treating a boundary point estimate
as proof that their true contribution is zero. Bootstrap averaging is a stabilization heuristic,
not a claim that the resulting allocation is optimal.

The first results must compare at least four alternatives:

1. equal weights,
2. reliability-only weights,
3. reliability divided by step,
4. reliability divided by square root of step.

The report must show both the raw plug-in vector and the bootstrap-stabilized vector. Evaluator
relevance decisions must remain visible in registry metadata rather than being silently folded into
the statistical weighting rule.

## 9. Composite score

The suite-level composite score is:

\[
\hat S
=
\sum_{e \in \mathcal E^\ast}
w_e \hat s_e.
\]

The score must always be accompanied by:

- its bootstrap interval,
- the evaluator weights,
- evaluator-level scores and intervals,
- variance components,
- reliability estimates, and
- saturation diagnostics.

A composite point estimate without these supporting values is incomplete.

## 10. Bootstrap uncertainty

Bootstrap resampling follows the nested data hierarchy. The case remains the outer sampling unit.
One bootstrap replicate:

1. samples \(C\) cases with replacement,
2. samples \(A\) agent runs with replacement within each selected case,
3. samples \(K\) judge replays with replacement within each selected run,
4. recomputes all variance components,
5. recomputes reliability and evaluator weights, and
6. recomputes evaluator and composite suite scores.

At every level, the complete evaluator score vector is resampled together. This preserves the
observed correlation among evaluators instead of treating their scores as independent.

Milestone 1 will use:

- 2,000 bootstrap replicates,
- a fixed random seed of `20260929`, and
- percentile intervals from the 2.5th and 97.5th percentiles.

The same bootstrap will be used for the replay-median sensitivity analysis. This avoids making an
incorrect \(1/K\) variance assumption for the median.

With only 10 cases, the intervals are exploratory and may be wide or irregular. The full bootstrap
distributions should be retained so instability is visible. Replicates in which every evaluator has
zero estimated reliability have no defined reliability-based weight vector; they are counted and
excluded from the bootstrap mean rather than silently replaced with equal weights.

## 11. Assumptions

The first-pass method assumes:

- all scores are normalized to \([0, 1]\) and higher is better,
- evaluator scale metadata in the registry is correct,
- judge replays use the same prompt, model configuration, and fixed run input,
- replay errors are exchangeable within a fixed run,
- agent runs are exchangeable within a case,
- cases are the independent sampling unit,
- the current data are complete and balanced,
- the variance components are constant within each evaluator, and
- the selected case set is relevant to the intended use of the score.

The final assumption is weak for this dataset because the cases are few and concentrated near the
score ceiling.

## 12. Known limitations

- Ten cases provide limited precision for case-level bootstrap intervals.
- Two runs per case provide a weak estimate of agent-run variance.
- Three replays per run provide only an initial estimate of judge noise.
- Discrete scales and ceiling saturation can produce zero or unstable corrected variance estimates.
- The weighting rule does not explicitly optimize for covariance between evaluators.
- High reliability does not prove evaluator validity or relevance.
- Bootstrap-mean weights reduce boundary instability but can still be sensitive to the empirical
  case mix.
- The current-design reliability changes when the number of runs or replays changes.
- The method-of-moments formulas assume a balanced design; unbalanced datasets will require weighted
  formulas or a mixed-effects model.

## 13. Required Milestone 1 outputs

The implementation of this note should produce:

1. an evaluator statistics table containing raw and corrected variance components,
2. single-measurement and current-design reliability,
3. saturation and replay-movement diagnostics,
4. evaluator weights under each candidate weighting rule,
5. raw plug-in and bootstrap-stabilized weights,
6. evaluator and composite scores,
7. bootstrap intervals for weights and scores, and
8. mean-versus-median sensitivity results.

The basic scoring pipeline is sound enough to continue when these outputs are reproducible,
interpretable, and do not hide unstable or undefined estimates.

## 14. References

- NIST/SEMATECH e-Handbook of Statistical Methods, sections on nested variability and variance
  components.
- Efron, B. (1979). "Bootstrap Methods: Another Look at the Jackknife." *The Annals of Statistics*,
  7(1), 1-26.
- Shrout, P. E., and Fleiss, J. L. (1979). "Intraclass Correlations: Uses in Assessing Rater
  Reliability." *Psychological Bulletin*, 86(2), 420-428.
