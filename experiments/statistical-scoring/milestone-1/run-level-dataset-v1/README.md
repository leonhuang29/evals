# Frozen Run-Level Evaluation Dataset

This directory is the Milestone 1 analysis snapshot for the statistical eval scoring project.
It freezes the score report and the lightweight source artifacts needed to interpret the scores.

## Dataset identity

- Dataset ID: `stan-issue-run-level-evaluator-replays-v1`
- Frozen: 2026-09-29
- Original source: locally supplied `Dataset` bundle; this frozen snapshot is authoritative
- Canonical score report: `source/issue_broad_report.json`
- Harness SDK commit: `803a4d6f906ce940fb769a53a1fc59efacd4dd37`

The report has a balanced `10 tasks x 2 agent runs x 3 judge replays x 4 evaluators` design,
for 240 score rows.

## Contents

- `source/issue_broad_report.json`: canonical score observations
- `source/issue_runs/`: 20 frozen run manifests containing final output and git diff
- `source/issue_tasks/`: the 10 task prompts
- `source/issue_cases.py`: task registry and reference verdicts
- `source/stan_issue_eval_broad.py`: evaluator selection and strict rubric
- `source/stan_issue_evals.py`: case loading and replay construction
- `source/harness_sdk_commit.txt`: pinned repository commit
- `source/README.md`: README shipped with the original dataset
- `dataset_manifest.json`: machine-readable dataset metadata
- `checksums.sha256`: SHA-256 checksums for every frozen source file
- `validate_dataset.py`: integrity and structural validation
- `build_tidy_table.py`: deterministic source-to-tidy transformation
- `derived/tidy_evaluations.json`: normalized table used by later experiments
- `evaluator_registry.json`: declared evaluator scale, unit, axis, and composite metadata
- `validate_evaluator_registry.py`: registry validation against the tidy table
- `SCORING_NOTE.md`: notation, variance model, reliability, weighting, and bootstrap specification
- `scoring_analysis.py`: variance, reliability, weighting, bootstrap, and report implementation
- `test_scoring_analysis.py`: synthetic checks for the statistical formulas
- `validate_scoring_results.py`: integrity checks for point estimates and bootstrap artifacts
- `derived/scoring_results.json`: point estimates and bootstrap interval summaries
- `derived/bootstrap_distributions.json`: complete retained bootstrap distributions
- `RESULTS.md`: human-readable initial results

## Terminology

- A task is one GitHub issue and reference verdict.
- A run is one fixed agent execution, identified by the `-t0` or `-t1` suffix.
- A replay is one evaluator pass over a fixed run. It is stored as `trial` in the source report.
- A score row is one run, replay, and evaluator observation.

Later transformations should rename `trial` to `replay_id` so it is not confused with the run suffix.

## Validation

Run:

```bash
python3 validate_dataset.py
```

The validator checks all source-file hashes, the balanced score design, score bounds, unique cells,
task and run identifiers, run manifests, task prompts, the pinned commit, and the strict-rubric hash.

Build the tidy evaluation table with:

```bash
python3 build_tidy_table.py
```

The output is a JSON object with dataset metadata, a column schema, dimension indexes, and a `rows`
array. Its grain is one row per case, fixed agent run, judge replay, and evaluator.

Validate the evaluator registry with:

```bash
python3 validate_evaluator_registry.py
```

The registry keeps declared score granularity separate from observed score movement. It also records
whether each evaluator is included, provisional, or excluded from the primary coding-quality composite.

## Scope and limitations

This is an analysis snapshot, not a complete replay archive. The original 82 MB `issue_sessions/`
directory is excluded. The frozen report is sufficient for the Milestone 1 tidy table and statistical
analysis, while rerunning the evaluator experiment still requires the original session traces.

The exact `strands-evals` version and default judge model were not recorded in the source report.
The dataset contains only 10 tasks, two runs per task, and scores concentrated near the ceiling.
Results from this snapshot should therefore be treated as provisional until cross-dataset validation.

The frozen files under `source/` should not be edited. Derived tables and analysis outputs should be
written outside that directory.
