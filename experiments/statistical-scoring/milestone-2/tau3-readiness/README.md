# Tau3 Calibration Readiness Experiment

This experiment studies how much evidence the calibrator needs before its
weights and composite score become stable enough to use provisionally. It does
not attempt to discover universal evaluator weights.

## Research question

Given one fixed experiment configuration, how do the calibration results change
as we add:

- more cases;
- more independent agent runs per case; and
- more judge replays over each fixed agent output?

The Tau3 native reward is kept outside the learned evaluator composite. It is
used as a held-out quality signal to check whether statistical calibration
preserves or improves agreement with objective task success.

## Frozen design

The design has two collection stages:

| Stage | Cases | Agent runs | Judge replays | Evaluators | Score rows |
|---|---:|---:|---:|---:|---:|
| Smoke | 12, three per domain | 2 | 3 | 3 | 216 |
| Main | 80, twenty per domain | 3 | 3 | 3 | 2,160 |

The four Tau3 domains are `airline`, `retail`, `telecom`, and
`banking_knowledge`. The smoke cases are a subset of the main cases.

The initial evaluator set is intentionally provisional:

- `GoalSuccessRateEvaluator`, step size `1.0`;
- `InstructionFollowingEvaluator`, step size `1.0`; and
- `HelpfulnessEvaluator`, declared step size `0.166`.

The smoke test must confirm that each evaluator can consume the exported Tau3
conversation faithfully. If an evaluator is structurally inappropriate, change
the evaluator set before the main collection and create a new experiment
version.

## Reproducibility contract

`experiment_config.json` pins:

- the Harbor and tau2/tau3 source commits;
- the sampling seed and domain allocation;
- the agent and judge model identities;
- the evaluator versions and declared step sizes;
- the run and replay counts; and
- the analysis grid and candidate readiness thresholds.

`task_manifest.json` is generated deterministically from the pinned source
checkouts. Each selected task records its source ID, Harbor task ID, domain, and
SHA-256 digest of the source task payload.

`prepare_tasks.py` also freezes the generated container runtime to the pinned
tau2/tau3 commit. It adds `websockets`, the one optional dependency imported by
Tau3's shared simulation model even for text-mode oracle and verifier paths.
This prevents a later upstream commit or packaging change from altering the
experiment images.

Regenerate or verify the task selection:

```bash
python freeze_tasks.py \
  --harbor-root /path/to/harbor \
  --tau2-root /path/to/tau2-bench

python validate_experiment.py \
  --harbor-root /path/to/harbor \
  --tau2-root /path/to/tau2-bench
```

The first command rewrites `task_manifest.json`. The second command validates
the local contract and confirms that the manifest still matches the pinned
source data.

Generate the frozen task directories without running any models:

```bash
python prepare_tasks.py \
  --harbor-root /path/to/harbor \
  --tau2-root /path/to/tau2-bench \
  --stage smoke \
  --output-dir /tmp/tau3-calibration-smoke \
  --overwrite
```

Use `--stage main` to prepare the complete 80-task collection.

## Running Harbor with Finch

Harbor does not currently include a built-in Finch environment, so this
experiment provides `finch_environment.py`. It reuses Harbor's existing local
container orchestration while replacing `docker` and `docker compose` with
`finch` and `finch compose`.

Finch Compose does not receive Harbor's process environment and does not support
all Docker Compose cleanup flags. `_finch_compose.py` handles those differences
by resolving only Harbor's non-secret image, resource, and mount placeholders
and removing the unsupported `down --rmi local` option. It does not forward
model credentials.

Start the Finch VM and verify the runtime:

```bash
finch vm start
finch run --rm hello-world
```

Before spending any model calls, run one prepared task with Harbor's oracle
agent. From this directory:

```bash
OPENAI_API_KEY="" OPENAI_BASE_URL="" PYTHONPATH="$(pwd)" \
  uv run --project /path/to/harbor \
  harbor trial start \
  --path /tmp/tau3-calibration-smoke/tau3-airline-2 \
  --agent oracle \
  --env finch_environment:FinchEnvironment \
  --trials-dir /tmp/tau3-finch-oracle-trials
```

This smoke test validates Finch image builds, the multi-container Tau3 runtime,
Harbor's oracle solution, and the native verifier. It does not call an agent
model; the empty OpenAI variables only satisfy the generated task's environment
template. The same `--env finch_environment:FinchEnvironment` option can be
used for later model-backed trials with real provider credentials.

## Collection order

1. Generate only the 12 smoke tasks with `prepare_tasks.py`.
2. Run two independent agent attempts for each smoke task.
3. Save the Harbor `result.json`, trajectory, runtime conversation state, and
   native reward for every attempt.
4. Replay the three evaluators three times against each fixed output.
5. Verify that the resulting table is balanced at
   `case x agent_run x judge_replay x evaluator`.
6. Inspect failures and evaluator compatibility before spending calls on the
   80-task collection.
7. Run the main collection once the smoke stage passes.

Agent reruns and judge replays must remain separate. Re-running a complete
Harbor trial changes the agent output and the simulated user interaction, while
replaying an evaluator over a saved trajectory changes only the judge result.

Replay the evaluators over one completed fixed-output trial:

```bash
python replay_evaluators.py \
  --trial-dir /tmp/tau3-finch-bedrock-smoke/tau3-airline-2-run-0 \
  --agent-run 0 \
  --replays 3 \
  --aws-profile your-profile \
  --output /tmp/tau3-calibration-results/evaluator_replays.json
```

The replay output records the evaluator scope explicitly:
`GoalSuccessRateEvaluator` judges the full session, while
`InstructionFollowingEvaluator` and `HelpfulnessEvaluator` judge the final
complete user-to-agent trace. The Tau3 native reward is copied onto each row as
a held-out metric and is not included in the learned composite.

Collect or resume the complete smoke stage after starting an ADA credential
server on port `9911`:

```bash
python collect_smoke.py \
  --stage smoke \
  --tasks-dir /tmp/tau3-calibration-smoke \
  --trials-dir /tmp/tau3-calibration-smoke-trials \
  --output /tmp/tau3-calibration-smoke-results/evaluator_replays.json \
  --harbor-root /path/to/harbor
```

The collector runs cases sequentially, reuses successful Harbor trials and
complete evaluator rows, and stops if it encounters an existing failed trial.
This makes an interrupted collection resumable without silently deleting or
overwriting failure evidence.

After the smoke-stage decision gate passes, collect the 80-case main stage with
the same resumable collector:

```bash
python collect_smoke.py \
  --stage main \
  --tasks-dir /tmp/tau3-calibration-main \
  --trials-dir /tmp/tau3-calibration-main-trials \
  --output /tmp/tau3-calibration-main-results/evaluator_replays.json \
  --harbor-root /path/to/harbor
```

Compare every calibration design supported by the completed observations:

```bash
python compare_configurations.py \
  --stage smoke \
  --input /tmp/tau3-calibration-smoke-results/evaluator_replays.json \
  --output-dir /tmp/tau3-calibration-smoke-analysis
```

The comparison uses only fully balanced cases. It repeatedly subsamples cases,
agent runs, and judge replays, fits the production `inverse_sqrt_step`
calibrator, and reports bootstrap definition rates, uncertainty widths, weight
drift, and composite-score drift. Before 12 cases are complete, the output is
marked as a partial diagnostic and does not make a minimum-size recommendation.

For the main stage, run the checkpoint monitor alongside the collector:

```bash
python monitor_checkpoints.py \
  --stage main \
  --input /tmp/tau3-calibration-main-results/evaluator_replays.json \
  --output-dir /tmp/tau3-calibration-main-results/checkpoints
```

The collector and monitor share a deterministic round-robin task order across
the four domains. The monitor writes each 12, 20, 40, and 80-case report once
the corresponding balanced case set is complete.

## Analysis plan

The main 80-case, 3-run, 3-replay collection is the maximum design. Smaller
designs are simulated by repeated subsampling at:

- cases: `12`, `20`, `40`, and `80`;
- agent runs: `2` and `3`; and
- judge replays: `2` and `3`.

For each design point, the analysis will report:

- the fraction of fits that produce learned rather than fallback weights;
- bootstrap interval width for the composite score;
- bootstrap interval width and drift for evaluator weights;
- calibrated-score drift relative to the maximum design;
- held-out score stability relative to equal weighting; and
- association between the learned composite and native Tau3 reward.

The thresholds in `experiment_config.json` are research hypotheses, not product
defaults. Milestone 2 should end with a provisional readiness rule and an
explicit inconclusive state, not a claim that every evaluation suite becomes
calibrated after a universal number of cases.

## Runtime status

The frozen tasks can be executed locally through Finch using the adapter above.
The oracle smoke gate was verified on October 19, 2026 with Finch `v1.19.0` and
the pinned Harbor source. `tau3-airline-2` completed with native reward `1.0`,
including successful Tau2 DB, action, and communication checks. Model-backed
collection completed on October 21, 2026.

The main stage produced all 2,160 expected observations across 80 cases, 3
agent runs, 3 judge replays, and 3 evaluators. The canonical dataset and
checkpoint reports are stored under `results/main/`. See `MAIN_RESULTS.md` for
the findings and provisional Milestone 2 decision. The follow-up shrinkage
curve is in `results/main/SHRINKAGE_COMPARISON.md`, and the resulting P0 scoring
states are defined in `CALIBRATION_STATUS_POLICY.md`.
