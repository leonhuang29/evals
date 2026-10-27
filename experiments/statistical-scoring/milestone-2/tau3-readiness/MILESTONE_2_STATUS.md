# Milestone 2 Status: Per-Experiment Calibration

## Objective

Milestone 2 turns the measurement foundation into a reusable per-experiment
calibration procedure. Its goal is not to publish universal evaluator weights.
It must determine when an experiment contains enough repeated evidence to
support learned weights and when strands-evals should retain equal weighting.

## Implemented foundation

The experimental calibrator currently supports:

- variance decomposition across cases, agent runs, and judge replays;
- equal, reliability-only, inverse-step, and inverse-square-root-step candidate
  weights;
- equal-weight fallback when no reliability signal is available;
- hierarchical bootstrap intervals;
- immutable versioned calibration profiles;
- compatibility checks for datasets, evaluator configurations, and report
  structures;
- scoring under the active or candidate weight vectors; and
- raw report retention through `CalibrationResult`.

The Tau3 experiment adds a reproducible external validation harness with frozen
tasks, separate agent runs and judge replays, balanced tidy observations, and a
held-out native reward.

## Smoke-stage findings

The 12-case smoke stage produced 216 balanced rows. It validated collection,
fixed-output replay, variance estimation, bootstrap analysis, and resumability.

It did not produce recommendation-ready weights:

- the maximum weight interval width was approximately `0.61`, above the `0.25`
  candidate threshold;
- the composite interval width was approximately `0.13`, above the `0.10`
  candidate threshold; and
- the learned composite correlated less strongly with held-out Tau3 reward
  than equal weighting (`0.300` versus `0.394`).

These findings are documented in `SMOKE_RESULTS.md`.

## Main-stage checkpoints

The 80-case main stage uses three agent runs and three judge replays. Tasks are
collected round robin across the four domains so checkpoints remain balanced.
Analyses are generated automatically at 12, 20, 40, and 80 cases.

Each checkpoint compares:

- bootstrap definition rate;
- weight interval width;
- composite interval width;
- weight and score drift;
- equal-weight correlation with held-out Tau3 reward; and
- learned-weight correlation with held-out Tau3 reward.

The main collection is complete. It produced 2,160 balanced observations
across 80 cases and 240 case-run groups, with no duplicate or incomplete
observation groups. The complete findings are documented in
`MAIN_RESULTS.md`.

The smallest tested design satisfying every candidate threshold across 100
subsamples was 80 cases, 3 agent runs, and 2 judge replays. This is a
provisional budget for the Tau3 experiment, not a universal minimum.

The learned composite remained less correlated with held-out native reward
than equal weighting (`0.108` versus `0.139` for the provisional design).
Although the difference remained within the candidate degradation guardrail,
the result does not establish a quality improvement.

Saved-profile historical recomputation is also validated. The customer
workflow test serializes a fitted profile, restores it in a new calibrator,
rescores compatible historical reports with the frozen weights, and rejects
reports carrying an incompatible dataset fingerprint.

The equal-to-learned shrinkage comparison is complete. On the provisional
80-case design, full learned weighting reduced score variation from `0.0036`
to `0.0028`, but held-out correlation declined from `0.139` to `0.107`.
No non-zero learned fraction beat equal weighting on the complete-design
subsamples.

The P0 status policy is therefore discrete rather than continuously shrunk:

- `uncalibrated` uses equal weights before a fit;
- `equal_weight_fallback` retains equal weights when evidence is insufficient
  or no reliability signal exists; and
- `calibrated` applies profile weights only after experiment-specific
  readiness criteria pass.

Profile compatibility remains a separate dimension with `compatible`, `stale`,
and `incompatible` states. The full proposal is documented in
`CALIBRATION_STATUS_POLICY.md`.

## Provisional decision rule

A checkpoint is provisionally ready only when:

- at least 95% of bootstrap replicates produce defined results;
- every evaluator weight interval is at most `0.25` wide;
- the composite interval is at most `0.10` wide; and
- held-out correlation is no more than `0.05` worse than equal weighting.

The held-out threshold is a research guardrail, not a product default.

At 12, 20, or 40 cases:

- if all guardrails pass, record the smallest provisional design;
- otherwise continue to the next checkpoint.

At 80 cases:

- if the guardrails pass, propose a provisional calibration procedure;
- if precision fails, report that the experiment is inconclusive;
- if held-out behavior fails, retain equal weighting and investigate the
  evaluator set or weighting objective.

## Remaining Milestone 2 work

- Convert the research stopping rule into a product-facing budget and status
  design.
- Decide how callers provide experiment-specific readiness criteria.
- Decide whether fallback results need a machine-readable reason in the first
  API version.

Milestone 2 is complete only after these decisions are supported by the main
experiment. The existence of a fitted profile alone is not sufficient.
