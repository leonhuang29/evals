"""Replay milestone evaluators over one fixed Tau3 Harbor trial."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
from typing import Any

from tau3_session import build_session

from strands_evals import Case, Experiment
from strands_evals.evaluators import (
    GoalSuccessRateEvaluator,
    HelpfulnessEvaluator,
    InstructionFollowingEvaluator,
)

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "experiment_config.json"
EVALUATOR_SCOPES = {
    "GoalSuccessRateEvaluator": "session",
    "InstructionFollowingEvaluator": "last_trace",
    "HelpfulnessEvaluator": "last_trace",
}


def _load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"expected a JSON object at {path}")
    return data


def _build_evaluators(model_id: str) -> list[Any]:
    return [
        GoalSuccessRateEvaluator(model=model_id),
        InstructionFollowingEvaluator(model=model_id),
        HelpfulnessEvaluator(model=model_id),
    ]


def _native_reward(trial_dir: Path) -> float:
    result = _load_json(trial_dir / "result.json")
    if result.get("exception_info") is not None:
        raise ValueError("cannot replay evaluators over a failed Harbor trial")
    verifier = result.get("verifier_result") or {}
    rewards = verifier.get("rewards") or {}
    return float(rewards["reward"])


def _case_name(trial_dir: Path) -> str:
    result = _load_json(trial_dir / "result.json")
    task_id = result.get("task_id") or {}
    task_path = task_id.get("path")
    if not task_path:
        raise ValueError(f"Harbor result does not identify its task: {trial_dir}")
    return Path(str(task_path)).name


async def replay(
    *,
    trial_dir: Path,
    output_path: Path,
    agent_run: int,
    replays: int,
) -> None:
    config = _load_json(CONFIG_PATH)
    model_id = str(config["models"]["judge"]["model_id"])
    session, final_response = build_session(trial_dir)
    native_reward = _native_reward(trial_dir)
    case_name = _case_name(trial_dir)
    case = Case[str, str](
        name=case_name,
        input=(trial_dir / "agent/instruction.txt").read_text(encoding="utf-8"),
        metadata={
            "agent_run": agent_run,
            "native_reward": native_reward,
            "trial_dir": str(trial_dir),
        },
    )
    experiment: Experiment[str, str] = Experiment(
        cases=[case],
        evaluators=_build_evaluators(model_id),
    )

    def fixed_output(_: Case[str, str]) -> dict[str, Any]:
        return {"output": final_response, "trajectory": session}

    rows: list[dict[str, Any]] = []
    if output_path.exists():
        existing = json.loads(output_path.read_text(encoding="utf-8"))
        if isinstance(existing, list):
            rows = [
                row
                for row in existing
                if not (row.get("case") == case_name and int(row.get("agent_run", -1)) == agent_run)
            ]

    for judge_replay in range(replays):
        report = await experiment.run_evaluations_async(fixed_output, max_workers=1)
        if len(report.cases) != len(EVALUATOR_SCOPES):
            raise RuntimeError(f"expected {len(EVALUATOR_SCOPES)} evaluator rows, received {len(report.cases)}")

        for index, case_row in enumerate(report.cases):
            evaluator_name = str(case_row["evaluator"])
            details = report.detailed_results[index]
            if not details:
                raise RuntimeError(f"{evaluator_name} failed: {report.reasons[index]}")
            rows.append(
                {
                    "experiment_id": config["experiment_id"],
                    "case": case_name,
                    "agent_run": agent_run,
                    "judge_replay": judge_replay,
                    "evaluator": evaluator_name,
                    "evaluation_scope": EVALUATOR_SCOPES[evaluator_name],
                    "score": report.scores[index],
                    "test_pass": report.test_passes[index],
                    "label": details[0].label,
                    "reason": report.reasons[index],
                    "native_reward": native_reward,
                    "trial_dir": str(trial_dir),
                }
            )

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")
        print(f"judge replay {judge_replay + 1}/{replays} complete")  # noqa: T201

    run_rows = [row for row in rows if row["case"] == case_name and int(row["agent_run"]) == agent_run]
    expected = replays * len(EVALUATOR_SCOPES)
    if len(run_rows) != expected:
        raise RuntimeError(f"expected {expected} rows for run {agent_run}, found {len(run_rows)}")
    print(f"saved {len(run_rows)} balanced rows to {output_path}")  # noqa: T201


def parse_args() -> argparse.Namespace:
    config = _load_json(CONFIG_PATH)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trial-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--agent-run", type=int, required=True)
    parser.add_argument(
        "--replays",
        type=int,
        default=int(config["collection"]["smoke"]["judge_replays"]),
    )
    parser.add_argument("--aws-profile")
    return parser.parse_args()


if __name__ == "__main__":
    arguments = parse_args()
    if arguments.aws_profile:
        os.environ["AWS_PROFILE"] = arguments.aws_profile
    os.environ.setdefault("AWS_REGION", "us-west-2")
    os.environ.setdefault("AWS_DEFAULT_REGION", os.environ["AWS_REGION"])
    asyncio.run(
        replay(
            trial_dir=arguments.trial_dir.expanduser().resolve(),
            output_path=arguments.output.expanduser().resolve(),
            agent_run=arguments.agent_run,
            replays=arguments.replays,
        )
    )
