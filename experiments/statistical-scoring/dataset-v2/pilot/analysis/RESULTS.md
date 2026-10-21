# Dataset v2 Pilot Scoring Results

**Dataset:** `stan-issue-run-level-evaluator-replays-v2-pilot`  
**Bootstrap:** 2,000 hierarchical replicates  
**Status:** Pilot validation; not production weights

## Evaluator statistics

| Evaluator | Mean | Case var | Run var | Judge var | Design r | At 1.0 | Moving runs | Avg replay range |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `CoherenceEvaluator` | 0.9833 | 0.000000 | 0.002083 | 0.002083 | 0.0000 | 93.3% | 1/10 | 0.0250 |
| `ConcisenessEvaluator` | 0.9167 | 0.000000 | 0.016667 | 0.025000 | 0.0000 | 83.3% | 3/10 | 0.1500 |
| `FaithfulnessEvaluator` | 1.0000 | 0.000000 | 0.000000 | 0.000000 | 0.0000 | 100.0% | 0/10 | 0.0000 |
| `senior-review-strict` | 0.8950 | 0.000165 | 0.001293 | 0.000823 | 0.1736 | 0.0% | 8/10 | 0.0430 |

## Reliability / sqrt(step) weights

| Evaluator | Raw point weight | Bootstrap-mean weight | 95% bootstrap interval |
|---|---:|---:|---:|
| `ConcisenessEvaluator` | 0.0000 | 0.1124 | [0.0000, 0.6464] |
| `CoherenceEvaluator` | 0.0000 | 0.0949 | [0.0000, 0.8383] |
| `FaithfulnessEvaluator` | 0.0000 | 0.0000 | [0.0000, 0.0000] |
| `senior-review-strict` | 1.0000 | 0.7927 | [0.0000, 1.0000] |

## Interpretation

- All 10 agent patches pass their case-specific behavioral hidden test.
- `senior-review-strict` is the only evaluator with positive corrected between-case variance in the point estimate.
- The raw reliability-based weight is therefore a boundary estimate, not evidence that other evaluators are universally worthless.
- `FaithfulnessEvaluator` is fully saturated at 1.0 and contributes no measurable discrimination in this pilot.
- `ConcisenessEvaluator` remains the noisiest in absolute score units because its disagreements are 0.5 jumps.
- 339 of 2,000 reliability-based bootstrap replicates have no measurable case signal and are excluded from the bootstrap-mean vector.
- Five outer cases are enough to exercise the pipeline, but not enough to finalize evaluator weights.

## Decision

The expanded-data pipeline is sound: generation, trace capture, hidden-test verification,
judge replay, tidy-table construction, variance decomposition, and hierarchical bootstrap
all completed reproducibly. The pilot supports continuing with the remaining selected cases.
Its weights are sensitivity evidence only and should not replace the v1 provisional vector.

