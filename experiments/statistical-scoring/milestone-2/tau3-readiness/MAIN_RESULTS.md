# Tau3 Calibration Main Results

## Collection

The main collection completed the frozen maximum design:

- 80 cases, with 20 cases from each Tau3 domain;
- 3 independent agent runs per case;
- 3 judge replays per fixed agent output; and
- 3 evaluators.

This produced 2,160 tidy observations. All 240 case-run groups contain the
expected nine evaluator rows, with no incomplete groups or duplicate
observation keys.

The canonical observations are stored in
`results/main/evaluator_replays.json`. Generated reports for the 12-, 20-, 40-,
and 80-case checkpoints are stored under `results/main/checkpoints/`.

## Configuration comparison

The final analysis repeatedly subsampled the maximum design and applied the
candidate readiness thresholds defined in `experiment_config.json`.

| Cases | Agent runs | Judge replays | Ready fits | Max weight CI width | Composite CI width | Held-out delta |
|---:|---:|---:|---:|---:|---:|---:|
| 12 | 3 | 3 | 0% | 0.545 | 0.156 | -0.047 |
| 20 | 3 | 3 | 0% | 0.333 | 0.125 | -0.026 |
| 40 | 3 | 3 | 57% | 0.222 | 0.087 | -0.032 |
| 80 | 3 | 2 | 100% | 0.145 | 0.063 | -0.032 |
| 80 | 3 | 3 | 100% | 0.119 | 0.063 | -0.032 |

`Ready fits` is the fraction of repeated case subsamples satisfying all
candidate thresholds. The thresholds require at least 95% defined bootstrap
replicates, a maximum weight interval width of 0.25, a composite interval width
of 0.10, and held-out correlation no more than 0.05 below equal weighting.

## Provisional calibration budget

The smallest tested design that satisfied every candidate threshold across all
100 subsamples was:

- 80 cases;
- 3 agent runs per case; and
- 2 judge replays per fixed output.

This design requires 1,440 evaluator observations, one third fewer than the
2,160-observation maximum design. The third judge replay narrowed the weight
interval further, from 0.145 to 0.119, but did not materially narrow the
composite interval.

This is the smallest design in the tested grid, not a universal minimum.
Different datasets, evaluator sets, judge models, or thresholds may require a
different calibration budget.

## Learned weights

Across the 80-case, 3-run, 2-replay subsamples, the mean learned weights were:

| Evaluator | Mean weight |
|---|---:|
| GoalSuccessRateEvaluator | 0.238 |
| HelpfulnessEvaluator | 0.612 |
| InstructionFollowingEvaluator | 0.150 |

The complete 3-replay fit produced similar weights, which indicates that the
weight vector was no longer highly sensitive to the additional replay.
Helpfulness received the largest weight because its estimated reliability was
high and its declared score step was smaller than the two binary evaluators.

## Held-out Tau3 reward

The Tau3 native reward was excluded from calibration and used only as a
held-out task-success signal.

For the provisional 80-case, 3-run, 2-replay design:

| Score | Mean correlation with native reward |
|---|---:|
| Equal-weight composite | 0.139 |
| Learned-weight composite | 0.108 |

The learned score was lower by 0.032. This passes the provisional degradation
guardrail of -0.05, but it is not an improvement over equal weighting. Both
correlations are weak, and the native reward measures task completion rather
than every quality dimension represented by the evaluator set.

The result supports a claim about statistical stability, not semantic
correctness. Equal weighting should remain visible as a baseline, and the
inverse-square-root-step rule should remain a candidate rather than a product
default.

## Shrinkage comparison

The follow-up analysis blended equal and learned weights using:

`applied = (1 - learned_fraction) * equal + learned_fraction * learned`

For the provisional 80-case, 3-run, 2-replay design, increasing the learned
fraction reduced score variation across replay subsamples from 0.0036 to
0.0028. Held-out correlation declined monotonically from 0.139 to 0.107, and
no non-zero learned fraction beat equal weighting in any complete-design
subsample.

This means shrinkage exposes a stability-versus-alignment tradeoff rather than
solving it. P0 should not silently select a continuous blend. The provisional
policy is equal weighting for cold start and insufficient evidence, followed
by the selected learned rule only when experiment-specific readiness criteria
pass. See `CALIBRATION_STATUS_POLICY.md` and
`results/main/SHRINKAGE_COMPARISON.md`.

## Milestone 2 decision

The experiment demonstrates that the calibration pipeline can:

- separate agent-run and judge-replay observations;
- estimate stable variance components and weights when enough evidence exists;
- expose insufficient-data states at smaller suite sizes;
- quantify uncertainty and drift; and
- evaluate a learned score against a held-out signal.

For this Tau3 configuration, 80 cases, 3 agent runs, and 2 judge replays form a
defensible provisional calibration budget under the current research
thresholds. The result does not justify universal weights or a universal
minimum sample size.

Saved-profile reuse is now covered by the customer workflow test: a profile can
be serialized, restored in a fresh calibrator, and applied to compatible
historical reports without refitting, while reports from an incompatible
dataset are rejected.

Before closing Milestone 2, the remaining product-facing work is to define
how experiment-specific readiness criteria are supplied to the API and whether
`equal_weight_fallback` should expose a machine-readable reason. Milestone 3
should then test transfer to another dataset, evaluator set, and judge
configuration.
