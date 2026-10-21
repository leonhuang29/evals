"""Replay the fixed pilot runs through the four Milestone 1 evaluators."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any

from strands_evals import Case, Experiment
from strands_evals.evaluators import (
    CoherenceEvaluator,
    ConcisenessEvaluator,
    FaithfulnessEvaluator,
    OutputEvaluator,
)
from strands_evals.types.trace import Session

BASE_DIR = Path(__file__).resolve().parent
PILOT_MANIFEST_PATH = BASE_DIR / "pilot_manifest.json"
CONFIG_PATH = BASE_DIR / "experiment_config.json"
RUNS_DIR = BASE_DIR / "runs"
SESSIONS_DIR = BASE_DIR / "sessions"
REPORT_PATH = BASE_DIR / "evaluation_report.json"
MAX_DIFF_CHARS = 40_000


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def load_cases() -> list[Case[str, str]]:
    manifest = load_json(PILOT_MANIFEST_PATH)
    cases: list[Case[str, str]] = []
    for case in manifest["cases"]:
        prompt = (BASE_DIR / case["prompt_file"]).read_text()
        reference = (BASE_DIR / case["reference_file"]).read_text()
        for run_path in sorted(RUNS_DIR.glob(f"{case['name']}-t*.json")):
            run_id = run_path.stem
            if not (SESSIONS_DIR / f"{run_id}.json").is_file():
                raise RuntimeError(f"missing session for {run_id}")
            cases.append(Case(name=run_id, input=prompt, expected_output=reference))
    return cases


def replay_run(case: Case) -> dict[str, Any]:
    run_manifest = load_json(RUNS_DIR / f"{case.name}.json")
    session = Session.model_validate_json((SESSIONS_DIR / f"{case.name}.json").read_text())
    diff = run_manifest.get("diff", "")
    if len(diff) > MAX_DIFF_CHARS:
        diff = diff[:MAX_DIFF_CHARS] + f"\n... [diff truncated at {MAX_DIFF_CHARS} chars]"
    output = run_manifest.get("output") or f"[run crashed: {run_manifest.get('error', 'unknown error')}]"
    output += "\n\n=== GIT DIFF (working tree after the run) ===\n" + (diff or "[empty diff]")
    return {"output": output, "trajectory": session}


def build_evaluators() -> list[Any]:
    config = load_json(CONFIG_PATH)
    judge_model = config["judge"]["model_id"]
    strict_rubric = (BASE_DIR / config["judge"]["strict_rubric_file"]).read_text()
    return [
        ConcisenessEvaluator(model=judge_model),
        CoherenceEvaluator(model=judge_model),
        FaithfulnessEvaluator(model=judge_model),
        OutputEvaluator(
            name="senior-review-strict",
            rubric=strict_rubric,
            model=judge_model,
        ),
    ]


def completed_replays(rows: list[dict[str, Any]], expected_rows_per_replay: int) -> set[int]:
    counts: dict[int, int] = defaultdict(int)
    for row in rows:
        counts[int(row["trial"])] += 1
    return {replay for replay, count in counts.items() if count == expected_rows_per_replay}


async def evaluate(replays: int | None) -> None:
    config = load_json(CONFIG_PATH)
    judge_config = config["judge"]
    os.environ["AWS_REGION"] = judge_config["region"]
    cases = load_cases()
    evaluators = build_evaluators()
    expected_rows_per_replay = len(cases) * len(evaluators)
    replay_count = replays if replays is not None else judge_config["replays_per_run"]

    existing_rows: list[dict[str, Any]] = []
    if REPORT_PATH.exists():
        existing_rows = json.loads(REPORT_PATH.read_text())
    done = completed_replays(existing_rows, expected_rows_per_replay)
    rows = [row for row in existing_rows if int(row["trial"]) in done]

    experiment: Experiment[str, str] = Experiment(cases=cases, evaluators=evaluators)
    for replay in range(replay_count):
        if replay in done:
            print(f"[skip] replay {replay}")
            continue
        report = await experiment.run_evaluations_async(
            replay_run,
            max_workers=judge_config["max_workers"],
        )
        for index, case_row in enumerate(report.cases):
            rows.append(
                {
                    "trial": replay,
                    "case": case_row.get("name"),
                    "evaluator": case_row.get("evaluator"),
                    "score": report.scores[index],
                    "test_pass": report.test_passes[index],
                    "reason": report.reasons[index],
                }
            )
        REPORT_PATH.write_text(json.dumps(rows, indent=2) + "\n")
        print(f"[done] replay {replay}: {len(report.cases)} rows")

    by_evaluator: dict[str, list[float]] = defaultdict(list)
    moving: dict[tuple[str, str], list[float]] = defaultdict(list)
    for row in rows:
        score = float(row["score"])
        by_evaluator[row["evaluator"]].append(score)
        moving[(row["case"], row["evaluator"])].append(score)

    print(f"{'evaluator':<28} {'n':>3} {'min':>5} {'mean':>6} {'max':>5} moving")
    for evaluator_name in sorted(by_evaluator):
        scores = by_evaluator[evaluator_name]
        moving_runs = sum(
            1
            for (run_id, name), values in moving.items()
            if name == evaluator_name and len({round(value, 6) for value in values}) > 1
        )
        print(
            f"{evaluator_name:<28} {len(scores):>3} {min(scores):>5.2f} "
            f"{statistics.mean(scores):>6.3f} {max(scores):>5.2f} {moving_runs:>6}"
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--replays", type=int)
    return parser.parse_args()


if __name__ == "__main__":
    arguments = parse_args()
    asyncio.run(evaluate(arguments.replays))
