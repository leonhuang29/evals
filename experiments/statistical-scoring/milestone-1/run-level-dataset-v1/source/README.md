# Stan issue sessions and evaluator variance study

This folder is a starter kit for the judge-variance study behind the statistical merge gate. It contains a fixed set of recorded agent sessions and the scripts that score them repeatedly, so you can measure how much an evaluator's score moves across trials when the input is held constant. The agent that produced the sessions is Stan solving real GitHub issues from the `strands-agents/harness-sdk` repository.

The core idea is a two-stage split. One script runs the agent once per task and freezes the result to disk. A separate script loads those frozen results and runs the evaluators over them many times. Because the frozen input never changes, any change in score between trials comes from the judge, not from the agent. That is the signal the study is about.

## Files

### Inputs (the frozen task definitions)

- `issue_cases.py` is the task registry and the single source of truth. It lists each task with its name, its kind (bug or feature), the path to its prompt file, and a reference verdict written by a maintainer. Every other script imports `TASKS` and `TASKS_BY_NAME` from here. Nothing runs without it.
- `issue_tasks/` holds the 10 frozen task prompts, one Markdown file per issue. These are the exact prompts given to the agent. The scorers read them back at runtime as the evaluator input, so they must stay in sync with the paths listed in `issue_cases.py`.
- `harness_sdk_commit.txt` pins the `harness-sdk` repository to one commit. Every run uses this commit so results stay comparable over time. You only need it if you regenerate the sessions.

### Stage 1: generate the sessions

- `stan_issue_runner.py` runs Stan on each task and freezes the output. It clones and pins the repository, prepares one throwaway git worktree per run, launches the agent in that worktree, and records what happened. It runs each task twice by default and runs several tasks at once. You only run this if you want to regenerate the sessions. The rest of the study works off the sessions already in this folder.

### Stage 1 outputs (the frozen artifacts)

- `issue_sessions/` holds the 20 recorded sessions, one JSON file per run. Each file is the mapped `Session`, which is the trace of what the agent did. The trace-based evaluators read these.
- `issue_runs/` holds the 20 run manifests, one JSON file per run. Each manifest has the agent's final summary, timing, any error, and the git diff of the working tree after the run. The output-based evaluators read the summary and the diff from here.

The naming convention is `<task-name>-t<trial>`. For example, `4245-http-timeout-t0` is the first trial of the http-timeout task.

### Stage 2: score the sessions repeatedly

- `stan_issue_evals.py` is the first scorer. It loads every frozen session, hands it to a set of evaluators, and repeats the whole pass N times. It runs `HelpfulnessEvaluator`, a partial-credit ladder rubric, and a weighted-criteria rubric. It writes `issue_flakiness_report.json` and prints which sessions scored 1.0 on every trial versus only some trials.
- `stan_issue_eval_broad.py` is the second scorer and the more developed one. It reuses the case loading and replay logic from `stan_issue_evals.py`. It runs a smaller, curated set of evaluators and a deliberately strict custom rubric. It writes `issue_broad_report.json` and prints a per-evaluator saturation summary plus per-session score and deviation tables.

### Stage 2 outputs (the results)

- `issue_flakiness_report.json` is the output of the first scorer. It has one row per trial, session, and evaluator.
- `issue_broad_report.json` is the output of the second scorer, in the same row format.

## How to run

### Score the sessions

The scorers are the part you will iterate on. To score the frozen sessions three times:

```
python stan_issue_eval_broad.py 3
```

The argument is the number of trials and defaults to 3. Run `stan_issue_evals.py` the same way. Neither scorer runs the agent. They only read the files under `issue_sessions/` and `issue_runs/`.

### Regenerate the sessions

You only need this if you want to record the sessions fresh. This stage runs the agent, so it needs `strands_stan` and Bedrock access as described under Setup. To rebuild every session:

```
python stan_issue_runner.py
```

This clones `harness-sdk` if it is not already present, pins it to the commit in `harness_sdk_commit.txt`, and runs each task. It writes the mapped session into `issue_sessions/` and the run manifest into `issue_runs/`. If `harness_sdk_commit.txt` is absent, it pins to the current `HEAD` of the clone and writes that commit into the file.

To regenerate a single task, pass any substring of its name:

```
python stan_issue_runner.py 4245
```

The runner is resumable. A run whose session file already exists is skipped, so you can stop and restart it safely. To force a run to happen again, delete its matching files under `issue_sessions/` and `issue_runs/` first.

Three environment variables tune the run:

- `STAN_ISSUE_CONCURRENCY` sets how many runs happen at once. The default is 3.
- `STAN_ISSUE_TIMEOUT_S` sets the per-run timeout in seconds. The default is 2400.
- `STAN_ISSUE_MODEL` overrides the agent's model. This is useful for a cheap smoke test before a full run.

The number of trials per task is the `TRIALS` constant near the top of `stan_issue_runner.py` and defaults to 2. Change it there to record more trials per task.

## Setup

There are two different dependency situations, and it matters which one you are in.

To replay and score the sessions, which is the main work, you need `strands-evals` and AWS credentials with Bedrock access. The evaluators are themselves language models, and they call Bedrock in region `us-west-2`. This is all the scorers need.

To regenerate the sessions from scratch, you additionally need `strands_stan`, which is a local package and is not on PyPI. Only `stan_issue_runner.py` uses it. You do not need it for the study itself.

The versions used to produce these files were `strands-agents` 1.55.1 and a matching `strands-evals`.

## The 20 sessions and their tiers

The sessions fall into three groups by how the evaluators score them. You need both ends of the range to study a gate, because a good gate must flag the weak sessions and must leave the strong ones alone.

- Ceiling sessions score at or near 1.0 on every evaluator and barely move. These are `4245-http-timeout`, `2951-get-plugin-api`, and `4379-nested-required-dropped`. Treat them as the "must not flag" control.
- Boundary sessions sit just below the top and flip across trials. These are `4004-text-dropped-tooluse`, `4337-async-callable-hooks`, `4394-bedrock-read-timeout`, `3338-overflow-recursion`, and `4262-loop-guard-plugin`. This is where judge noise lives.
- Stable-below sessions hold a consistent partial score. These are `3577-delete-memory-tool` and `4341-sliding-window-truncation`.

A caveat about the current set. Every session was produced by one strong model solving the task reasonably well, so all the scores cluster near the top. This squashes the score range and limits how much deviation any evaluator can show. The way to widen the range is to create degraded versions of a session on purpose, for example by removing the regression test or introducing a subtle bug, or to generate sessions with a weaker model. That gives you a labeled spread of good and bad outputs to measure the evaluators against.

## What we found about the evaluators

The point of the broad scorer was to learn which evaluators are worth putting in a gate. The results split cleanly.

- `ConcisenessEvaluator` moves a great deal, with scores from 0.5 to 1.0. It measures how short the agent's summary is. That is the wrong axis for a coding gate. It is kept as a worked example of a problem, which is described below.

- The custom `senior-review-strict` rubric in `stan_issue_eval_broad.py` is the one that works. It asks the judge to score six criteria on an integer scale and to hold back top marks. This pulls scores off the 1.0 ceiling into the 0.83 to 1.0 band, which is where trial-to-trial judge noise actually shows up. It is the discriminating instrument. The coarser ladder and weighted rubrics in `stan_issue_evals.py` are the stable baseline for comparison.

There is one lesson that the numbers make on their own. If you average the four evaluators with equal weight, the ranking is driven almost entirely by `Conciseness`, because it is the noisiest one and it happens to be off-axis. A session can look flaky or look stable purely because of how `Conciseness` scored its summary length. So the sessions must not be ranked by an equal-weight average across evaluators. They should be ranked by the on-axis instrument, or by a weighted combination that discounts the noisy and irrelevant evaluators. Designing that weighted combination is the heart of the statistics work.
