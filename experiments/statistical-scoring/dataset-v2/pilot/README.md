# Dataset v2 Five-Case Pilot

This directory freezes the first five proposed additions to the run-level evaluator dataset. The
pilot exists to validate dataset construction before spending model and judge calls on all 20 new
cases.

**Status:** complete. All five hidden tests fail at their recorded pre-fix commits and pass after
applying only the known source-file changes. Ten independent Stan patches were then generated, all
ten passed their behavioral hidden test, and each fixed run was scored three times by four
evaluators. The experiment contains 120 score observations and 2,000 hierarchical bootstrap
replicates.

The live configuration is frozen in `experiment_config.json`. The main outputs are:

- `runs/` and `sessions/` for agent outputs, diffs, configuration, and traces;
- `evaluation_report.json` for the raw replayed judge outputs;
- `tidy_evaluations.json` for the normalized run-level table;
- `evaluator_registry.json` for declared evaluator metadata; and
- `analysis/RESULTS.md` and `analysis/scoring_results.json` for statistical results.

## Cases

| Issue | Area | Purpose |
|---|---|---|
| #4601 | Bedrock formatting | Small deterministic normalization bug |
| #4411 | Graph lifecycle | Async lifecycle and invocation-state behavior |
| #4354 | Agent limits | Runtime guardrail validation |
| #4155 | Skills | Filesystem batch resilience and exception contract |
| #3910 | Tool schemas | Pure-function and mutation invariant |

Each case has four independent artifacts:

- a benchmark prompt under `issue_tasks/`, which is the only task text shown to the agent;
- a reference verdict under `references/`, used later as evaluator `expected_output`;
- a hidden test under `hidden_tests/`, which is not copied into the agent's worktree; and
- commit and path provenance in `pilot_manifest.json`.

The prompts preserve the reported behavior and reproduction while omitting dedicated root-cause and
possible-solution sections. This keeps the task grounded in a real issue without directly handing
the implementation to the agent.

## Validation

Structural validation checks the manifest, artifact hashes, candidate provenance, and commit shape:

```bash
python validate_pilot.py
```

Historical execution additionally creates a temporary worktree for each case, copies in its hidden
test, and confirms:

1. the hidden test fails against the recorded pre-fix commit;
2. the failure is a test failure rather than a collection or environment error; and
3. the same test passes after applying only the known source-file diff.

```bash
python validate_pilot.py --execute --repo /path/to/harness-sdk
```

Execution writes `pilot_validation_results.json`. It does not run Stan, call a model, or modify the
provided repository's current checkout.

## Reproduction

Run the agent stage and recheck the exact frozen diffs:

```bash
AWS_PROFILE=codex-DO-NOT-DELETE \
AWS_REGION=us-east-1 \
python run_experiment.py --repo /path/to/harness-sdk
python recheck_hidden_tests.py --repo /path/to/harness-sdk
```

Then replay the fixed runs, build the tidy table, and run the scoring analysis:

```bash
AWS_PROFILE=codex-DO-NOT-DELETE AWS_REGION=us-east-1 python evaluate_experiment.py
python build_tidy_table.py
python analyze_scoring.py
python validate_experiment.py
```

The scripts are resumable. Existing complete run artifacts and completed judge replays are reused.

## Pilot Result

The strict evaluator moved on 8 of 10 fixed runs, but its average replay range was only 0.043.
Conciseness moved on 3 of 10 runs with a much larger average range of 0.15 because each disagreement
is a 0.5 jump. Faithfulness was completely saturated at 1.0.

Only `senior-review-strict` had positive corrected between-case variance in the point estimate, so
the raw reliability-based rule assigned it all of the weight. The bootstrap-mean
`reliability / sqrt(step)` vector was less brittle: 79.3% strict, 11.2% Conciseness, 9.5% Coherence,
and 0% Faithfulness. These are pilot sensitivity results, not replacement production weights; five
outer cases still produce very wide intervals.
