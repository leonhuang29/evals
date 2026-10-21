# Proposed Customer Calibration Workflow

Calibration should be an optional, progressive extension of normal evaluation.
Customers should provide the experiment they care about, not a universal set
of weights or a statistically chosen repetition count.

## Cold start

A customer defines cases, evaluators, and a task function, then runs an
evaluation normally. With no calibration evidence available, strands-evals
returns the equal-weight score and labels it `uncalibrated`.

The first report remains useful immediately. Calibration must not block the
basic evaluation workflow.

## Evidence collection

The system preserves raw evaluator observations and can obtain calibration
evidence in two ways:

- reuse compatible reports from earlier executions; and
- collect additional agent runs and judge replays when the customer explicitly
  requests calibration.

Judge replays must reuse fixed outputs so they isolate evaluator variability.
Independent agent runs estimate variation in the agent output. These forms of
repetition are not interchangeable.

The current prototype requires customers to specify `agent_runs` and
`judge_replays`. The intended product should instead accept a time or cost
budget and use progressive checkpoints to decide whether more observations are
worth collecting.

## Calibration result

The calibrator returns:

- the composite score;
- the raw reports used for the fit;
- the learned weights;
- bootstrap uncertainty diagnostics;
- a calibration status; and
- a versioned calibration profile.

The supported statuses distinguish:

- `uncalibrated`: no fit has completed;
- `equal_weight_fallback`: a fit completed but the data did not support learned
  weights; and
- `calibrated`: the fit produced a learned weight vector.

Product readiness requires an additional `insufficient_evidence` decision
derived from uncertainty and held-out guardrails. A numerically fitted weight
vector is not automatically precise enough to recommend.

## Reuse

A compatible profile can score future or historical raw reports under the same
weighting rule. Profiles are tied to the dataset, evaluator definitions, step
sizes, and relevant experiment configuration. Incompatible profiles must be
rejected rather than silently reused.

## Customer responsibility

Customers should decide:

- which cases and evaluators represent their use case;
- how much time or model cost they are willing to spend; and
- whether calibration is required for their decision.

Customers should not calculate variance components, manually assign weights,
or decide how many repetitions are statistically sufficient. The framework
should make that recommendation and retain equal weighting when the evidence
is inconclusive.
