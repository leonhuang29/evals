# Statistical Eval Scoring and Compare Gate

> Historical planning note. The current product direction and milestones are defined in
> `DESIGN_DOCUMENT_REVISED.md`, which replaces the fixed-weight framing below with an
> experiment-specific calibration workflow.

This is a working project note for the evaluation-statistics internship work around Stan and
`strands-evals`. It narrows the scope to the pieces that matter for a trustworthy compare gate and
gives a concrete timeline for the remaining internship weeks.

## Vision

Build a statistically defensible scoring and comparison layer for agent evaluations so that
`strands-evals` can distinguish real regressions from judge wobble.

In practical terms, the project should answer this question:

> If an agent's eval score moved, how much of that movement is likely to be real and how much is
> likely to be judge noise or scoring artifacts?

The compare gate is the eventual product surface, but the core work is below it:

1. Measure evaluator noise on fixed inputs.
2. Define a score that does not let coarse or noisy evaluators dominate.
3. Compare agents using that score with controlled false-alarm behavior.

## Problem

Current eval scores are not strong enough to gate merges:

- A report score is currently a simple average.
- LLM judges can disagree on identical inputs.
- Evaluators have different step sizes, so equal weighting distorts their influence.
- Missing or crashed runs can contaminate the score if they are treated like real failures.

Without a statistical layer, a small score drop cannot be interpreted honestly.

## Project Scope

### In scope

- Repeated evaluator rescoring on frozen runs.
- Tidy long-form score tables.
- Variance decomposition for judge noise, run-to-run noise, and case variation.
- Reliability-aware evaluator weighting.
- Confidence intervals for scores and weights.
- Paired comparison between baseline and candidate reports.
- A CLI verdict suitable for CI gating.

### Out of scope for the first pass

- Perfect judge modeling.
- Every evaluator in the ecosystem.
- Fully general hierarchical models.
- Production-polished CI before the scoring method is stable.

## Success Criteria

The project is successful if it can show all of the following:

1. Re-scoring the same fixed runs reveals measurable evaluator noise, and that noise is summarized
   clearly enough to guide scoring design.
2. The composite score discounts evaluators that are coarse, noisy, saturated, or off-axis.
3. Agent-vs-itself comparisons usually return `no_change` at the chosen false-alarm rate.
4. Known degraded variants are detected more often than self-vs-self comparisons are falsely flagged.
5. The resulting comparison can be surfaced through `strands-evals compare` with an exit code for CI.

## Working Thesis

The first hard problem is not the compare command. The first hard problem is defining a score that is
worth comparing.

That means the project should proceed in this order:

1. scoring logic
2. uncertainty estimates
3. paired comparison logic
4. CLI and CI integration

## Current Focus

As of week 3, the immediate milestone is a first-pass scoring design:

- define the unit of analysis
- build the tidy score table
- implement evaluator registry metadata, including explicit step sizes
- estimate variance components from repeated rescoring data
- compute reliability-weighted composite scores
- bootstrap uncertainty on the weights and composite score

This is enough to produce a real checkpoint result even before the compare gate exists.

## Key Design Questions

These are the main open questions that the project must resolve explicitly:

1. Tool-level evaluators:
   should tool-call verdicts be averaged to a run-level score first, or should calls be the unit of
   analysis?
2. Replay collapse:
   if replay scores are collapsed with a median, how should judge noise be propagated downstream?
3. Case variance:
   should between-case variance be de-noised, and if so, by what approximation?
4. Saturation:
   how should evaluators with little or no between-case movement be treated in the weighting scheme?
5. Missingness:
   how should infrastructure failures and empty trajectories be excluded and reported?

## Timeline

### Week 3

Goal: stabilize the problem statement and the dataset.

- Confirm what data is already available for repeated rescoring.
- Write down the scoring notation and the candidate weighting method.
- Identify the minimum viable experiment needed for a first empirical result.

Checkpoint:
- a short written vision and plan
- a dataset inventory
- a clear list of open statistical questions

### Week 4

Goal: implement the first-pass scoring layer.

- Build a tidy long-form table with evaluator, task, run, replay, unit, and score.
- Add an evaluator registry with explicit step sizes and unit metadata.
- Compute per-evaluator judge noise, run noise, case variance, reliability, and weights.
- Add bootstrap confidence intervals for weights and composite score.

Checkpoint:
- code that produces a weight table from real rescoring data
- a short note interpreting which evaluators dominate and why

### Week 5

Goal: pressure-test the scoring method.

- Compare equal-weight scoring against reliability-weighted scoring.
- Study sensitivity to replay collapse choice: median vs mean.
- Resolve the first-pass answer for tool-level evaluators.
- Document edge-case behavior: negative corrected variances, saturated evaluators, missing cells.

Checkpoint:
- a scoring design note that states the chosen method and rejected alternatives

### Week 6

Goal: package the score as a reusable report primitive.

- Turn the scoring logic into a stable report/analysis interface.
- Surface composite score plus uncertainty alongside per-evaluator summaries.
- Ensure crashed or empty runs are excluded from scoring and counted separately.

Checkpoint:
- a report artifact that says more than a plain average

### Week 7

Goal: implement paired comparison.

- Compare baseline and candidate results on matched cases.
- Produce evaluator-level and composite-level verdicts.
- Set a user-facing false-alarm target and pick an initial testing procedure.

Checkpoint:
- a baseline-vs-candidate script that emits `improved`, `regressed`, or `no_change`

### Week 8

Goal: validate comparison behavior.

- Run self-vs-self comparisons to estimate empirical false-alarm behavior.
- Check whether the observed behavior matches the intended threshold closely enough.
- Tighten output and error reporting.

Checkpoint:
- evidence that the method does not over-fire on stable inputs

### Week 9

Goal: test detection on known bad variants.

- Create or collect degraded variants.
- Measure whether the comparison catches real regressions reliably.
- Identify which evaluators contribute signal and which mostly add noise.

Checkpoint:
- a small detection study: self-vs-self versus self-vs-degraded

### Week 10

Goal: integrate into the CLI path.

- Wire the comparison method into `strands-evals compare`.
- Return a clear machine-readable verdict and exit code.
- Make local end-to-end runs straightforward.

Checkpoint:
- end-to-end compare command on a laptop

### Week 11

Goal: demonstrate CI usefulness.

- Add a narrow CI demo path, ideally on a known Stan change or injected regression.
- Document runtime, cost, and operational limits.
- Reduce rough edges in output and docs.

Checkpoint:
- one live or reproducible CI-style gating demo

### Week 12

Goal: close out with usable artifacts.

- Final docs and write-up.
- Summarize empirical findings about evaluator variance and weighting.
- Call out limitations and next steps beyond the internship.

Checkpoint:
- shippable PRs plus a final project memo

## Risks

- The available datasets may be too narrow and too ceiling-heavy, which can hide useful variance.
- Tool-level evaluators may require a different analysis path from run-level evaluators.
- Judge-call cost may limit how many replays or bootstrap runs are practical.
- The ideal comparison procedure may be more complex than can be productionized during one internship.

## Risk Management

- Start with a balanced, frozen rescoring dataset and get one clean result first.
- Prefer a defensible approximation over an elaborate model that cannot be validated in time.
- Keep every decision written down, especially where the method is approximate.
- Separate "research result" from "product integration" so progress does not stall.

## Immediate Next Steps

1. Normalize the current dataset into a tidy long-form table.
2. Implement the first-pass weighting method on run-level evaluators.
3. Produce a weight table with bootstrap intervals.
4. Write a short interpretation note: which evaluators are saturated, noisy, coarse, or useful.

## Short Weekly Status Template

To keep progress legible even with light mentorship, each weekly update should answer:

1. What question did I answer this week?
2. What method did I use?
3. What did I find?
4. What decision does that support?
5. What remains uncertain?
6. What is next?
