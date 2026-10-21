# Statistical Evals Project

This folder contains the design notes, frozen data, and reproducible analysis for the statistical
evaluation scoring project.

## Project map

- `docs/VISION_AND_TIMELINE.md`: project scope, milestones, and planned timeline.
- `docs/EXTENSIONS.md`: follow-on work beyond the initial scoring project.
- `milestone-1/run-level-dataset-v1/`: frozen run-level dataset, tidy table, evaluator registry,
  scoring note, analysis code, bootstrap outputs, and initial results.
- `milestone-2/tau3-readiness/`: pinned Tau3 task selection and experiment contract for studying
  calibration readiness as cases, agent runs, and judge replays increase.
- `dataset-v2/`: candidate audit and provenance for expanding the run-level dataset to 30 cases.

## Current status

The Milestone 1 data pipeline is complete:

- the source dataset is frozen and checksummed;
- the tidy evaluation table is reproducible;
- evaluator scale and unit metadata are recorded;
- judge, agent-run, and between-case variation can be estimated;
- bootstrap uncertainty and weighting sensitivities can be generated.

The remaining issue is the interpretation of evaluator weights, not the integrity of the dataset.
Three decisions must be separated before a provisional weighting rule is selected:

1. **Variance target:** Observed variation across case means is always nonnegative, but it contains
   residual agent-run and judge noise. A de-noised method-of-moments estimate can reach the
   nonnegative boundary at zero when the dataset is too small to resolve case signal from noise.
2. **Evaluator eligibility:** Statistical reliability does not establish evaluator relevance.
   Whether an off-axis evaluator such as Conciseness belongs in the composite must be an explicit
   product decision, not a hidden consequence of the weighting calculation.
3. **Weight stabilization:** Directly normalizing small, boundary-constrained variance estimates can
   assign nearly all weight to one evaluator. With only ten cases, that result should be treated as
   an instability diagnostic rather than a production recommendation.

Milestone 1 uses the mean of the defined hierarchical-bootstrap weight vectors as a stabilization
step. This keeps all four evaluators in the experiment and currently assigns approximately 71% of
the provisional weight to `senior-review-strict`. The raw plug-in vector remains visible as a
diagnostic.

The current Milestone 1 conclusion is:

> The scoring pipeline is sound enough to continue, and the bootstrap-mean weights are suitable as
> a provisional result. They are not ready to serve as production merge-gating weights.

Milestone 2 has started with a domain-balanced Tau3 experiment design. The source repositories,
task selection, repetition counts, evaluator set, held-out native metric, and candidate readiness
criteria are frozen under `milestone-2/tau3-readiness/`. Model execution is pending a Docker
Compose-capable environment.

## Reproduce Milestone 1

Run these commands from `milestone-1/run-level-dataset-v1`:

```bash
python3 validate_dataset.py
python3 validate_evaluator_registry.py
python3 -m unittest test_scoring_analysis.py
python3 scoring_analysis.py
python3 validate_scoring_results.py
```
