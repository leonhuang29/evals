# Tau3 Calibration Smoke Results

## Collection

The smoke collection completed successfully with the frozen design:

- 12 cases across four Tau3 domains;
- 2 independent agent runs per case;
- 3 judge replays per fixed output; and
- 3 evaluators.

This produced 216 balanced observations. All 24 case-run groups contain the
expected nine evaluator rows, and there are no duplicate observation keys.

## Evaluator behavior

| Evaluator | Mean score | Distinct scores | Fixed outputs with replay movement |
|---|---:|---:|---:|
| GoalSuccessRateEvaluator | 0.792 | 2 | 4/24 |
| HelpfulnessEvaluator | 0.863 | 4 | 11/24 |
| InstructionFollowingEvaluator | 0.917 | 2 | 2/24 |

Instruction Following is close to saturation: 66 of its 72 observations are
`1.0`. Goal Success moves across both agent runs and judge replays. Helpfulness
has the broadest score distribution and the most frequent replay movement.

## Configuration comparison

The configured hierarchical bootstrap used 500 replicates. Neither observed
configuration met the candidate readiness thresholds.

| Cases | Agent runs | Judge replays | Max weight interval width | Composite interval width |
|---:|---:|---:|---:|---:|
| 12 | 2 | 2 | 0.662 | 0.143 |
| 12 | 2 | 3 | 0.614 | 0.133 |

The candidate thresholds are `0.25` for the maximum weight interval width and
`0.10` for the composite interval width. Adding the third replay improved both
measurements, but not enough to treat the 12-case weights as ready.

The full smoke fit produced:

| Evaluator | Reliability | Weight |
|---|---:|---:|
| GoalSuccessRateEvaluator | 0.000 | 0.000 |
| HelpfulnessEvaluator | 0.608 | 0.619 |
| InstructionFollowingEvaluator | 0.920 | 0.381 |

Goal Success received zero estimated reliability because its observed case
variation was fully explained by the estimated agent-run and judge-replay
components in this small sample. This is an estimate from this experiment, not
evidence that the evaluator is inherently useless.

## Held-out Tau3 reward

The native Tau3 reward was not used to fit the weights. Across the 24 agent
runs, 12 received reward `1.0` and 12 received reward `0.0`.

| Score | Correlation with native reward |
|---|---:|
| Equal-weight composite | 0.394 |
| Calibrated composite | 0.300 |

The learned composite did not improve agreement with native task success in
the smoke sample. The result is too small to establish a general conclusion,
but it is a useful warning: reliability measures repeatable discrimination,
not semantic correctness or relevance.

## Decision

The smoke stage validates the collection, replay, tidy-table, variance, and
bootstrap pipeline. It does not establish usable weights or a minimum
calibration size.

Before starting the 80-case collection, confirm whether the experiment is
intended to optimize statistical stability alone or also preserve agreement
with native task success. If native task success is part of the acceptance
criterion, the main analysis should compare equal and calibrated scores at
every case-count checkpoint and retain an explicit fallback when calibration
does not improve the held-out result.
