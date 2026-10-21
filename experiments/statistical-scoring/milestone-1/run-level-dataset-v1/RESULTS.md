# Milestone 1 Initial Scoring Results

**Dataset:** `stan-issue-run-level-evaluator-replays-v1`  
**Bootstrap:** 2,000 hierarchical replicates  
**Status:** Exploratory

## Evaluator statistics

| Evaluator | Status | Mean score | 95% CI | Case var | Run var | Judge var | Single r | Design r | At 1.0 | Moving runs |
|---|---|---|---|---|---|---|---|---|---|---|
| `CoherenceEvaluator` | provisional | 0.9958 | [0.9792, 1.0000] | 0.0000 | 0.0000 | 0.0010 | 0.0000 | 0.0000 | 98.3% | 1/20 |
| `ConcisenessEvaluator` | provisional | 0.7750 | [0.6833, 0.8667] | 0.0008 | 0.0083 | 0.0542 | 0.0122 | 0.0552 | 55.0% | 13/20 |
| `FaithfulnessEvaluator` | provisional | 0.9917 | [0.9708, 1.0000] | 0.0000 | 0.0000 | 0.0021 | 0.0000 | 0.0000 | 96.7% | 2/20 |
| `senior-review-strict` | included | 0.9435 | [0.9213, 0.9600] | 0.0005 | 0.0005 | 0.0006 | 0.3298 | 0.6084 | 8.3% | 10/20 |

## Key findings

- `ConcisenessEvaluator` has the largest judge variance (0.0542); its off-axis relevance remains a separate validation question.
- `CoherenceEvaluator`, `FaithfulnessEvaluator` have zero corrected case variance in the point estimate.
- The raw reliability / sqrt(step) plug-in rule assigns `senior-review-strict` 97.4% weight, demonstrating boundary sensitivity.
- Averaging the defined bootstrap weight vectors gives `senior-review-strict` a stabilized provisional weight of 71.0%.
- 19 of 2,000 reliability-based bootstrap replicates have no measurable case signal and are omitted from the bootstrap mean.
- The stabilized weights are suitable as a provisional Milestone 1 result, not as finalized production weights.

## Raw candidate weights

| Evaluator | Equal | Reliability | Reliability / step | Reliability / sqrt(step) |
|---|---|---|---|---|
| `ConcisenessEvaluator` | 0.2500 | 0.0833 | 0.0075 | 0.0255 |
| `CoherenceEvaluator` | 0.2500 | 0.0000 | 0.0000 | 0.0000 |
| `FaithfulnessEvaluator` | 0.2500 | 0.0000 | 0.0000 | 0.0000 |
| `senior-review-strict` | 0.2500 | 0.9167 | 0.9925 | 0.9745 |

## Provisional bootstrap-stabilized weights

The provisional vector is the componentwise mean of the jointly normalized weight vectors
from bootstrap replicates where the reliability-based weights are defined.

| Evaluator | Raw point weight | Provisional weight | 95% bootstrap interval |
|---|---|---|---|
| `ConcisenessEvaluator` | 0.0255 | 0.1990 | [0.0000, 1.0000] |
| `CoherenceEvaluator` | 0.0000 | 0.0334 | [0.0000, 0.3027] |
| `FaithfulnessEvaluator` | 0.0000 | 0.0581 | [0.0000, 0.3650] |
| `senior-review-strict` | 0.9745 | 0.7095 | [0.0000, 1.0000] |

## Composite sensitivity

| Weighting | Raw composite | Stabilized composite | 95% CI | Raw median-replay composite | Undefined bootstraps |
|---|---|---|---|---|---|
| equal | 0.9265 | 0.9265 | [0.8990, 0.9534] | 0.9364 | 0 |
| reliability | 0.9295 | 0.8894 | [0.7667, 0.9587] | 0.9334 | 19 |
| inverse_step | 0.9422 | 0.9275 | [0.7833, 0.9560] | 0.9444 | 19 |
| inverse_sqrt_step | 0.9392 | 0.9145 | [0.7750, 0.9553] | 0.9418 | 19 |

## Interpretation guardrails

- Reliability measures repeatable case discrimination, not evaluator validity.
- Raw negative variance estimates are retained in `derived/scoring_results.json` before truncation.
- The intervals are exploratory because the outer bootstrap contains only 10 cases.
- All four evaluators remain in the Milestone 1 weighting experiment; semantic relevance is separate.
- Bootstrap averaging stabilizes boundary estimates but is not a substitute for more data.
- Cross-dataset validation is required before selecting a final weighting rule.

## Milestone decision

The basic scoring pipeline is sound enough to continue: the hierarchy is explicit, the
variance components are reproducible, uncertainty is retained, and failure cases are visible.
The bootstrap-mean reliability / sqrt(step) vector is the provisional Milestone 1 result.
It is suitable for cross-dataset validation, but not yet for a production merge gate.

