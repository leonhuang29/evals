# Design Document for Statistical Evals Project

**Owner:** leyhuang  
**Status:** Revised after design review  
**Last updated:** October 2, 2026

## Summary

This project will add a calibration step to the `strands-evals` workflow. The product should not
ship one universal set of evaluator weights. Evaluator behavior can depend on the dataset, task
domain, rubric, judge model, and output distribution, so weights learned from one experiment may not
be appropriate for another.

Instead, `strands-evals` should ship the apparatus that allows a customer to generate a calibration
profile for their own experiment. The first execution can use an equal-weight average and report
that it is uncalibrated. Repeated scoring data can then be used to estimate evaluator noise,
reliability, and uncertainty, after which the system can learn experiment-specific weights and
recompute previous reports under the same profile.

An important research question for this project is whether evaluator statistics transfer across
datasets and judge configurations. If they do, `strands-evals` may eventually provide optional
defaults or priors. If they do not, calibration should remain experiment-specific.

## Problem

Evaluation reports commonly combine evaluator outputs using a simple average. This is easy to
understand, but it hides several sources of distortion.

First, many evaluators are LLM judges and can return different scores when the same fixed output is
scored repeatedly. A score change may therefore reflect judge variability rather than a meaningful
quality difference.

Second, evaluators operate at different granularities. A coarse evaluator may move by `0.50` in one
step, while a detailed rubric may move by approximately `0.04`. Under equal weighting, one coarse
judgment can move the composite much more than one fine-grained judgment.

Third, a single score does not communicate uncertainty. A report score of `0.78` compared with
`0.75` does not tell the customer whether the difference is meaningful or ordinary evaluator
variation.

Finally, evaluator behavior may be specific to the experiment. An evaluator that discriminates
well on one dataset may saturate or become noisy on another. This makes globally predefined weights
difficult to justify.

## Goals

The project will:

* Define a normalized representation for evaluator observations.
* Separate case variation, agent-run variation, and judge-replay variation.
* Generate experiment-specific evaluator weights automatically.
* Report uncertainty for learned weights and composite scores.
* Preserve raw evaluator scores so historical reports can be recomputed after calibration.
* Measure how strongly calibration depends on dataset, evaluator, and judge configuration.
* Establish a cold-start behavior for experiments without calibration data.

## Non-Goals

The initial project will not:

* Ship the weights learned from the Stan coding dataset as universal defaults.
* Claim that statistical reliability proves an evaluator measures the correct product quality.
* Guarantee a production-ready CI merge gate during the P0 milestones.
* Require every evaluator or experiment to use a coding-specific rubric.

## Terminology

* **Case:** One input or task in an evaluation dataset.
* **Agent run:** One agent attempt on a case.
* **Judge replay:** A repeated evaluator call on the same fixed agent output.
* **Calibration profile:** A versioned record of the experiment configuration, estimated variance
  components, weighting method, weights, and uncertainty.
* **Uncalibrated score:** A composite produced before enough repeated observations exist to estimate
  experiment-specific weights.

## Initial Experimental Evidence

The initial study used fixed Stan agent runs from real GitHub issues. Each fixed run was evaluated
three times by four evaluators. Because the agent output was held constant, movement across these
three replays measured judge variability rather than changes in the agent answer.

Across 20 fixed runs, 26 of 80 run/evaluator pairs changed score across replays. Movement differed
substantially by evaluator:

* `ConcisenessEvaluator`: 13 of 20 fixed runs moved.
* `senior-review-strict`: 10 of 20 moved.
* `FaithfulnessEvaluator`: 2 of 20 moved.
* `CoherenceEvaluator`: 1 of 20 moved.

Movement frequency alone was not sufficient to describe evaluator behavior. Conciseness had an
average replay range of `0.325` and a maximum range of `0.50`, while `senior-review-strict` moved in
much smaller increments. This demonstrated that evaluator noise and evaluator granularity must be
considered together.

With four equally weighted evaluators, one `0.50` Conciseness step changes the composite by `0.125`.
One `1/24` strict-rubric step changes it by approximately `0.0104`. A single Conciseness category
change therefore affects the composite about twelve times as much as one strict-rubric increment.

The first weighting experiments showed that the statistical pipeline can identify these
differences. They also produced wide bootstrap intervals and dataset-sensitive point estimates.
That result supports shipping a calibration mechanism rather than shipping the learned weights.

## Proposed Customer Workflow

### 1. First execution: uncalibrated

On the first execution, the system does not have enough evidence to estimate judge variability.
The default behavior will be:

* Store every raw evaluator score.
* Produce an equal-weight composite.
* Mark the composite as `uncalibrated`.
* Record the evaluator, rubric, judge model, dataset, and run configuration needed for later
  calibration.

Equal weighting is a cold-start fallback, not a claim that every evaluator is equally useful.

### 2. Collect calibration observations

The system will collect two different forms of repetition:

* Replaying evaluators on fixed outputs estimates judge variability.
* Producing multiple agent runs for the same case estimates agent-run variation.

These operations must remain distinct. Re-running the entire agent experiment changes both the
agent output and judge result, so it cannot isolate judge variability by itself.

### 3. Learn an experiment-specific profile

Once enough observations exist, the calibration algorithm will:

* Build the tidy evaluation table.
* Estimate variance components for each evaluator.
* Calculate evaluator reliability.
* Compare candidate weighting rules.
* Bootstrap the data to estimate uncertainty.
* Produce a versioned calibration profile.

The algorithm should learn the weights automatically. Customers may inspect or override the result,
but they should not need to manually assign every weight.

### 4. Apply calibration consistently

After a profile is created, the system will apply it to current and previous raw evaluator scores.
This ensures that historical and current reports are comparable under the same weighting rule.

The calibration profile must be versioned. Updating the profile should not silently mix reports
that were scored with different weights.

### 5. Recalibrate as evidence accumulates

New observations should update the profile using all applicable calibration data, not only the most
recent execution. The project will investigate whether early learned weights should be shrunk toward
equal weights until enough evidence accumulates.

One candidate is:

```text
applied_weight = (1 - confidence) * equal_weight
               + confidence * learned_weight
```

The confidence term would increase as calibration data grows and uncertainty narrows. This is a
candidate behavior to validate, not a finalized rule.

## Statistical Approach

### Tidy evaluation table

The statistical pipeline uses one row per:

```text
case x agent run x judge replay x evaluator
```

This representation does not change any scores. It makes the hierarchy explicit so the same data
can be grouped correctly for variance estimation and bootstrap resampling.

### Variance components

For each evaluator, the method estimates:

* **Case variation:** Score movement across different cases.
* **Agent-run variation:** Score movement across agent attempts on the same case.
* **Judge variation:** Score movement when the same fixed output is judged repeatedly.

An evaluator is more reliable when it distinguishes cases consistently while showing relatively
little run and judge noise. Reliability measures repeatable discrimination within the calibration
experiment. It does not establish semantic relevance.

### Candidate weighting rules

The project will compare:

* Equal weights.
* Reliability-only weights.
* Reliability divided by declared step size.
* Reliability divided by the square root of declared step size.
* A confidence-based blend between equal and learned weights.

The existing `reliability / sqrt(step)` rule is a candidate, not a shipped default. The project must
evaluate candidate rules by their held-out score stability and transfer behavior rather than by
whether one resulting weight vector appears subjectively balanced.

### Bootstrap uncertainty

The bootstrap resamples cases, runs within cases, and replays within runs while keeping evaluator
vectors together. It produces uncertainty intervals for variance components, weights, and composite
scores.

Wide intervals do not indicate that the bootstrap failed. They indicate that the available
calibration data cannot support a precise weight estimate. The product should expose that state
rather than presenting unstable weights as certain.

## Default Weight Policy

The project will empirically determine whether defaults are appropriate.

The transfer study will vary:

* Dataset and task domain.
* Evaluator set and rubric.
* Judge model and judge configuration.
* Agent model or output distribution.
* Evaluator package version.

If learned statistics remain similar across these conditions, `strands-evals` may provide optional
defaults or priors for matching configurations. If the statistics vary substantially, the product
will provide no universal calibrated weights and will require per-experiment calibration.

An LLM-generated semantic weighting proposal may be studied as an optional prior. It will not be the
primary P0 approach because it adds another noisy model judgment and does not replace empirical
measurement.

## Planned Features

### P0

* Tidy evaluation table and validation.
* Evaluator metadata registry for static properties such as step size and scoring unit.
* Variance decomposition and reliability estimation.
* Automatic candidate weighting.
* Bootstrap uncertainty.
* Versioned calibration profiles.
* Equal-weight uncalibrated fallback.
* Historical score recomputation under a selected profile.
* Transferability experiments that determine whether defaults are defensible.

### P1

* Paired baseline-versus-candidate comparison.
* Self-versus-self false-alarm experiments.
* Degraded-variant detection experiments.
* Robust handling of failed, crashed, or empty runs.

### P2

* CLI integration.
* Machine-readable verdicts and exit codes.
* End-to-end CI demonstration.

## Planned Timeline

### Milestone 1: Measurement foundation (1-2 weeks)

**Deliverables:**

* Build and validate the tidy evaluation table.
* Define the evaluator metadata registry.
* Write the scoring note with notation, variance components, and assumptions.
* Reproduce the initial fixed-output replay findings.

**Decision:**

Confirm that evaluator flakiness and granularity are measurable and that the pipeline is sound enough
to support calibration experiments.

### Milestone 2: Per-experiment calibration (1-2 weeks)

**Deliverables:**

* Implement variance decomposition and candidate weighting rules.
* Add equal-weight cold-start behavior.
* Generate versioned calibration profiles.
* Add bootstrap intervals and sensitivity comparisons.
* Test historical score recomputation.

**Decision:**

Choose the first provisional calibration procedure and define the minimum data required before a
profile is considered usable.

### Milestone 3: Transferability and default policy (1-2 weeks)

**Deliverables:**

* Run calibration across multiple datasets.
* Compare multiple evaluator and judge-model configurations.
* Evaluate candidate weights on held-out replays or cases.
* Measure weight drift and score-stability improvement.
* Define how tool-level observations are aggregated or modeled.

**Decision:**

Determine whether `strands-evals` should provide optional defaults, configuration-specific priors, or
no defaults.

### Milestone 4: Comparison design (P1, 1 week)

**Deliverables:**

* Build a paired-comparison method using calibrated scores.
* Measure false alarms through self-versus-self comparisons.
* Measure detection through intentionally degraded variants.

**Decision:**

Choose a first comparison procedure and verdict policy.

### Milestone 5: Product integration and handoff (P2, 1 week)

**Deliverables:**

* Surface calibration and comparison through the CLI.
* Expose machine-readable calibration status, verdicts, and exit codes.
* Run an end-to-end demonstration.
* Publish documentation and recommended next steps.

**Decision:**

Determine whether the comparison procedure is reliable enough for an experimental CI gate.

## Success Metrics

The project will measure:

* Reduction in held-out score variance relative to an equal-weight average.
* Width and stability of bootstrap intervals as calibration data accumulates.
* Weight drift across datasets, evaluators, and judge models.
* Reproducibility of calibration profiles.
* Ability to recompute historical reports consistently.
* Minimum number of cases, agent runs, and judge replays needed for useful calibration.
* For P1 comparison work, self-versus-self false-alarm rate and degraded-variant detection rate.

## Expected Results

The primary output will be a reusable calibration workflow in `strands-evals`, not a fixed set of
weights.

A customer should be able to:

1. Run an experiment and receive an equal-weight score marked as uncalibrated.
2. Collect repeated observations.
3. Generate an experiment-specific calibration profile automatically.
4. View uncertainty and diagnostics for the learned weights.
5. Recompute previous reports using the same versioned profile.
6. Recalibrate as additional evidence becomes available.

The project will also provide an empirical answer to whether any evaluator statistics are stable
enough across configurations to support optional defaults.

## Extension Work

Calibrated evaluator scores could eventually be studied as reinforcement-learning reward signals.
Before that is practical, the signals must be stable, aligned with task quality, and resistant to
reward hacking.

The same framework could support LLM-as-a-jury evaluation. The statistical layer would allow the
team to measure whether multiple judges reduce variance enough to justify their additional inference
cost.

These are follow-up directions rather than direct project deliverables.
