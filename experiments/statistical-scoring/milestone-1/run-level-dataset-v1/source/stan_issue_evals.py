"""Judge the frozen Stan issue sessions N times and measure evaluator score movement.

The task function runs no agent: it loads the recorded run manifest (`issue_runs/`) and mapped
`Session` (`issue_sessions/`) produced by `stan_issue_runner.py` and hands them to the
evaluators, so re-running the experiment N times isolates judge variance on fixed inputs.

Evaluators:
- HelpfulnessEvaluator          (trace-based, 7-level — flaky at level boundaries)
- fix-quality-ladder            (custom OutputEvaluator: partial-credit ladder against the
                                 mentor reference in expected_output — flaky between rungs)
- fix-craft-weighted            (custom OutputEvaluator: three weighted criteria the judge
                                 must combine itself — flaky in the aggregation)

(ToolSelectionAccuracyEvaluator is temporarily dropped: it fires one judge call per tool call,
which dominated runtime on the large sessions. The stored Sessions still support it, so it can
be added back to the list at any time.)

Outputs `issue_flakiness_report.json` (one row per trial x case x evaluator) and prints per
(case, evaluator) score spreads plus which sessions scored 1.0.

Usage: python stan_issue_evals.py [trials]   (default 3)
"""

import asyncio
import json
import os
import statistics
import sys
from collections import defaultdict
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
SESSIONS_DIR = BASE_DIR / "issue_sessions"
RUNS_DIR = BASE_DIR / "issue_runs"
REPORT_PATH = BASE_DIR / "issue_flakiness_report.json"
TRIALS = int(sys.argv[1]) if len(sys.argv) > 1 else 3
MAX_WORKERS = 5
MAX_DIFF_CHARS = 40_000  # keep the judge prompt bounded on huge diffs

os.environ["AWS_REGION"] = "us-west-2"

from strands_evals import Case, Experiment
from strands_evals.evaluators import (
    HelpfulnessEvaluator,
    OutputEvaluator,
)
from strands_evals.types.trace import Session

from issue_cases import TASKS

LADDER_RUBRIC = """
You are grading a coding agent's resolution of a real GitHub issue in the strands-agents/harness-sdk
repository. <Input> is the task the agent was given. <Output> is the agent's final summary followed by
the git diff of its working tree. <ExpectedOutput> is the maintainers' reference verdict: the known
root cause and acceptance criteria.

Score with this ladder. Pick exactly one rung; do not interpolate:
- 1.0: the agent identifies the same root cause / satisfies the acceptance criteria in the reference,
  the change is correct, AND it added a regression test that would fail before the change and reported
  running it.
- 0.75: correct root cause and a correct change, but the test is missing, weak, or there is no evidence
  it was run.
- 0.5: right component or file, but the mechanism differs from the reference, or the change satisfies
  the acceptance criteria only partially.
- 0.25: the analysis or change addresses a symptom rather than the cause, or the implementation is
  substantially incomplete.
- 0.0: wrong root cause, no meaningful change, or the summary misrepresents what the diff actually does.

Judge only from <Output> against <ExpectedOutput>; do not reward confident prose without a matching diff.
"""

WEIGHTED_RUBRIC = """
You are grading a coding agent's work on a real GitHub issue in the strands-agents/harness-sdk
repository. <Input> is the task, <Output> is the agent's final summary followed by the git diff of its
working tree, <ExpectedOutput> is the maintainers' reference verdict.

Score three criteria independently from 0.0 to 1.0, then output their weighted sum as the final score:
- Correctness (weight 0.5): does the change actually resolve the reported behavior, per the reference?
- Minimality (weight 0.25): is the diff scoped to the problem — no drive-by refactoring, no unrelated
  formatting churn, no speculative abstractions?
- Verification (weight 0.25): did the agent verify its work — added a regression test, ran the tests or
  the repro, and reported the result?

Partial-credit judgment calls on each criterion are yours to make.
"""


def load_cases() -> list[Case[str, str]]:
    cases: list[Case[str, str]] = []
    for task in TASKS:
        prompt = (BASE_DIR / task["prompt_file"]).read_text()
        for manifest_path in sorted(RUNS_DIR.glob(f"{task['name']}-t*.json")):
            run_id = manifest_path.stem
            if not (SESSIONS_DIR / f"{run_id}.json").exists():
                print(f"[warn] {run_id}: manifest without session, skipping")
                continue
            cases.append(Case(name=run_id, input=prompt, expected_output=task["reference"]))
    if not cases:
        raise SystemExit(f"no recorded runs found in {RUNS_DIR}; run stan_issue_runner.py first")
    return cases


def replay_task(case: Case) -> dict:
    manifest = json.loads((RUNS_DIR / f"{case.name}.json").read_text())
    session = Session.model_validate_json((SESSIONS_DIR / f"{case.name}.json").read_text())
    diff = manifest.get("diff", "")
    if len(diff) > MAX_DIFF_CHARS:
        diff = diff[:MAX_DIFF_CHARS] + f"\n... [diff truncated at {MAX_DIFF_CHARS} chars]"
    output = manifest.get("output") or f"[run crashed: {manifest.get('error', 'unknown error')}]"
    output += "\n\n=== GIT DIFF (working tree after the run) ===\n" + (diff or "[empty diff]")
    return {"output": output, "trajectory": session}


evaluators = [
    HelpfulnessEvaluator(),
    OutputEvaluator(name="fix-quality-ladder", rubric=LADDER_RUBRIC),
    OutputEvaluator(name="fix-craft-weighted", rubric=WEIGHTED_RUBRIC),
]


async def main() -> None:
    experiment: Experiment[str, str] = Experiment(cases=load_cases(), evaluators=evaluators)

    rows: list[dict] = []
    for trial in range(TRIALS):
        report = await experiment.run_evaluations_async(replay_task, max_workers=MAX_WORKERS)
        for i, case_row in enumerate(report.cases):
            rows.append(
                {
                    "trial": trial,
                    "case": case_row.get("name"),
                    "evaluator": case_row.get("evaluator"),
                    "score": report.scores[i],
                    "test_pass": report.test_passes[i],
                    "reason": report.reasons[i],
                }
            )
        # Persist and print after every trial so partial results are visible mid-run.
        REPORT_PATH.write_text(json.dumps(rows, indent=2))
        print(f"trial {trial} done ({len(report.cases)} rows, report updated)")
        for row in rows:
            if row["trial"] == trial and row["score"] < 1.0:
                print(f"  <1.0: {row['case']}  {row['evaluator']}  {row['score']:.2f}")

    print(f"saved: {REPORT_PATH}\n")

    # Per (case, evaluator) spread across trials.
    scores: dict[tuple[str, str], list[float]] = defaultdict(list)
    for row in rows:
        scores[(row["case"], row["evaluator"])].append(float(row["score"]))

    print(f"{'case':<34} {'evaluator':<28} {'scores':<24} mean   stdev")
    for (case_name, evaluator_name), values in sorted(scores.items()):
        spread = statistics.stdev(values) if len(values) > 1 else 0.0
        score_str = " ".join(f"{v:.2f}" for v in values)
        print(f"{case_name:<34} {evaluator_name:<28} {score_str:<24} {statistics.mean(values):.3f}  {spread:.3f}")

    print("\n=== sessions scoring 1.0 ===")
    for evaluator in evaluators:
        eval_name = evaluator.get_name()
        always = [c for (c, e), v in sorted(scores.items()) if e == eval_name and all(s == 1.0 for s in v)]
        sometimes = [
            c for (c, e), v in sorted(scores.items())
            if e == eval_name and any(s == 1.0 for s in v) and not all(s == 1.0 for s in v)
        ]
        print(f"{eval_name}:")
        print(f"  1.0 on every trial: {always or '—'}")
        print(f"  1.0 on some trials (boundary cases): {sometimes or '—'}")


if __name__ == "__main__":
    asyncio.run(main())
