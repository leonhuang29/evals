# Run-Level Dataset v2

This directory contains the planning artifacts for expanding the statistical-evals run-level
dataset from 10 to 30 cases.

## Status

The candidate audit and five-case pilot are complete. All five historical regression boundaries
were validated, ten independent agent patches were generated and passed their hidden behavioral
tests, and every fixed run was scored three times by four evaluators.

The completed pilot contains:

```text
5 cases x 2 runs x 3 replays x 4 evaluators = 120 score rows
```

The remaining 15 selected additions have not yet been run.

The proposed dataset contains:

- the original 10 cases, rerun under an explicitly recorded configuration;
- 20 additional Python bug-fix cases from `strands-agents/harness-sdk`;
- 2 independent agent runs per case;
- 3 judge replays per fixed run; and
- the same 4 evaluators used by v1.

The resulting balanced design would contain:

```text
30 cases x 2 runs x 3 replays x 4 evaluators = 720 score rows
```

## Contents

- `CANDIDATE_AUDIT.md`: selection policy, ranked shortlist, deferred candidates, and next steps.
- `candidate_manifest.json`: machine-readable provenance for the 20 selected additions.
- `validate_candidate_manifest.py`: structural validation for the candidate manifest.
- `pilot/`: frozen prompts, reference verdicts, hidden regression tests, and the historical-case
  validator for the first five additions.

## Next checkpoint

The five-case pilot now validates:

- per-case historical checkout construction;
- prompt and reference generation;
- hidden regression-test execution;
- explicit agent and judge model recording;
- session and run artifact capture; and
- compatibility with the existing tidy-table builder.

Run the structural check from `dataset-v2/pilot/`:

```bash
python validate_pilot.py
```

Pass `--execute --repo /path/to/harness-sdk` to additionally prove that each hidden test fails at
the recorded base commit and passes after applying only the known source fix.

The next checkpoint is to use the validated pilot pipeline for the remaining selected cases, then
compare evaluator statistics across the expanded dataset.
