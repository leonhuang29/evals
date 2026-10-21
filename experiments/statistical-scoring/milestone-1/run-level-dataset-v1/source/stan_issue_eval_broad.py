"""Evaluator study on the frozen Stan issue sessions: which judges carry signal, plus a harsh custom rubric.

Runs over the 20 stored sessions with no agent re-run, to make two points for the merge-gate study:

1. Not every evaluator is useful. An earlier sweep over the full off-the-shelf set found four judges
   returned 1.0 on every session across every trial (Correctness, GoalSuccessRate,
   InstructionFollowing, ResponseRelevance): saturated, zero signal, dropped here. What remains:
   - Conciseness: moves a lot, but it scores summary verbosity, not fix quality. It is the worked
     example for the aggregation problem — a real evaluator a user might add that a coding gate
     should down-weight because it measures the wrong axis.
   - Coherence, Faithfulness: near-saturated (mostly 1.0, a couple of dips). Kept as the "barely
     any signal" middle of the spectrum.
   (Also structurally skipped, never in the sweep: Tool*/Skill* trajectory judges, Multimodal*,
   Interactions (multi-agent), and the safety judges Harmfulness/Stereotyping/Refusal.)

2. A rubric can be written to produce useful deviation. The custom OutputEvaluator
   "senior-review-strict" forces the judge to make several independent borderline calls on an
   integer scale and to withhold top marks, which pulls scores off the 1.0 ceiling into the
   mid-band where judge noise across trials actually moves the score. It is the discriminating
   instrument; the coarser rubrics in stan_issue_evals.py are the stable baseline / negative control.

Reuses `load_cases`/`replay_task` from stan_issue_evals (same manifests + Sessions, same reference
verdicts). Writes `issue_broad_report.json` and prints per-evaluator saturation + spread.

Usage: python stan_issue_eval_broad.py [trials]   (default 3)
"""

import asyncio
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

from strands_evals import Experiment
from strands_evals.evaluators import (
    CoherenceEvaluator,
    ConcisenessEvaluator,
    FaithfulnessEvaluator,
    OutputEvaluator,
)

# Reuse the exact case loading + replay (imports are side-effect safe; main() is __main__-guarded).
from stan_issue_evals import BASE_DIR, load_cases, replay_task

TRIALS = int(sys.argv[1]) if len(sys.argv) > 1 else 3
MAX_WORKERS = 5
REPORT_PATH = BASE_DIR / "issue_broad_report.json"

STRICT_RUBRIC = """
You are a demanding senior engineer reviewing a coding agent's resolution of a real GitHub issue in
strands-agents/harness-sdk before it can merge. <Input> is the task. <Output> is the agent's final
summary followed by the git diff of its working tree. <ExpectedOutput> is the maintainers' reference
verdict: the true root cause and acceptance criteria.

Score SIX criteria, each on an integer scale of 0, 1, 2, 3, or 4. Do not use half points.
Anchor every criterion the same way:
  4 = exemplary, nothing a senior reviewer would ask to change
  3 = solid, would merge with at most a minor nit
  2 = acceptable but with a real gap a reviewer would block on
  1 = present but seriously deficient
  0 = absent or wrong
Reserve 4 for genuinely exceptional work. Competent-but-ordinary work is a 2 or 3, not a 4. Judge only
from the diff and summary in <Output>; do not give credit for claims the diff does not back up.

Criteria:
1. Root cause: does the change fix the actual mechanism named in <ExpectedOutput>, not a symptom?
2. Correctness: is the change itself correct and complete against the acceptance criteria?
3. Minimality: is the diff scoped to the fix, with no unrelated refactoring, churn, or dead code?
4. Regression test: is there a test that would FAIL before this change and PASS after, with evidence
   it was actually run? A test that does not target the reported bug scores at most 1.
5. Blast radius: did the agent check other call sites / edge cases / backward compatibility that the
   change could break, and show it?
6. Summary honesty: does the written summary accurately describe what the diff does, without
   overclaiming (e.g. claiming a test was run when the diff shows none)?

Compute the final score as the sum of the six integer sub-scores divided by 24, rounded to two
decimals. In your reason, list the six sub-scores as s1..s6 before the final score.
"""


evaluators = [
    ConcisenessEvaluator(),
    CoherenceEvaluator(),
    FaithfulnessEvaluator(),
    OutputEvaluator(name="senior-review-strict", rubric=STRICT_RUBRIC),
]


async def main() -> None:
    experiment = Experiment(cases=load_cases(), evaluators=evaluators)

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
        REPORT_PATH.write_text(json.dumps(rows, indent=2))
        below = sum(1 for r in rows if r["trial"] == trial and r["score"] < 1.0)
        print(f"trial {trial} done ({len(report.cases)} rows, {below} scores <1.0, report updated)")

    print(f"saved: {REPORT_PATH}\n")

    # Per-evaluator summary: is it saturated (all 1.0), and how much does it move?
    by_eval: dict[str, list[float]] = defaultdict(list)
    per_case: dict[tuple[str, str], list[float]] = defaultdict(list)
    for row in rows:
        by_eval[row["evaluator"]].append(float(row["score"]))
        per_case[(row["case"], row["evaluator"])].append(float(row["score"]))

    print(f"{'evaluator':<28} {'n':>3} {'min':>5} {'mean':>6} {'max':>5}  {'all 1.0?':<9} moving cases")
    for name in sorted(by_eval):
        vals = by_eval[name]
        moving = sum(
            1 for (c, e), vs in per_case.items()
            if e == name and len(set(round(v, 2) for v in vs)) > 1
        )
        saturated = "yes" if all(v == 1.0 for v in vals) else "no"
        print(
            f"{name:<28} {len(vals):>3} {min(vals):>5.2f} {statistics.mean(vals):>6.3f} "
            f"{max(vals):>5.2f}  {saturated:<9} {moving}"
        )

    # Detail for the strict custom evaluator: per-session spread across trials.
    print("\n=== senior-review-strict per session ===")
    print(f"{'case':<34} {'scores':<20} mean   stdev")
    strict = sorted((k, v) for k, v in per_case.items() if k[1] == "senior-review-strict")
    for (case_name, _), vals in strict:
        spread = statistics.stdev(vals) if len(vals) > 1 else 0.0
        print(f"{case_name:<34} {' '.join(f'{v:.2f}' for v in vals):<20} {statistics.mean(vals):.3f}  {spread:.3f}")

    # Average deviation per session: mean over evaluators of each evaluator's stdev across trials.
    eval_names = sorted(by_eval)
    dev_by_eval_case: dict[str, dict[str, float]] = defaultdict(dict)
    for (case_name, eval_name), vals in per_case.items():
        dev_by_eval_case[case_name][eval_name] = statistics.stdev(vals) if len(vals) > 1 else 0.0
    cases = sorted(dev_by_eval_case)

    print("\n=== average deviation per session (stdev across trials, averaged over the 4 evaluators) ===")
    header = "".join(f"{n[:14]:>15}" for n in eval_names)
    print(f"{'case':<34}{header}{'avg dev':>10}")
    ranked = []
    for case_name in cases:
        devs = [dev_by_eval_case[case_name].get(n, 0.0) for n in eval_names]
        avg_dev = statistics.mean(devs)
        ranked.append((avg_dev, case_name, devs))
        cells = "".join(f"{d:>15.3f}" for d in devs)
        print(f"{case_name:<34}{cells}{avg_dev:>10.3f}")

    print("\n=== sessions ranked by average deviation (most flaky first) ===")
    for avg_dev, case_name, _ in sorted(ranked, reverse=True):
        print(f"  {avg_dev:.3f}  {case_name}")


if __name__ == "__main__":
    asyncio.run(main())
