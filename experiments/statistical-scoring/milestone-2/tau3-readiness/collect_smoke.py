"""Collect a resumable Tau3 calibration dataset."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any

from replay_evaluators import EVALUATOR_SCOPES, replay
from task_selection import ordered_task_ids

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "experiment_config.json"
MANIFEST_PATH = BASE_DIR / "task_manifest.json"
MAX_TRIAL_NAME_LENGTH = 80


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _task_ids(stage: str) -> list[str]:
    manifest = _load_json(MANIFEST_PATH)
    config = _load_json(CONFIG_PATH)
    return ordered_task_ids(
        manifest,
        stage=stage,
        domain_order=[str(domain) for domain in config["sampling"]["domains"]],
    )


def _trial_succeeded(trial_dir: Path) -> bool:
    result_path = trial_dir / "result.json"
    if not result_path.exists():
        return False
    result = _load_json(result_path)
    return result.get("exception_info") is None and result.get("verifier_result") is not None


def _replay_complete(
    output_path: Path,
    *,
    case_name: str,
    agent_run: int,
    replays: int,
) -> bool:
    if not output_path.exists():
        return False
    rows = _load_json(output_path)
    matching = [row for row in rows if row.get("case") == case_name and int(row.get("agent_run", -1)) == agent_run]
    expected = replays * len(EVALUATOR_SCOPES)
    keys = {(int(row["judge_replay"]), str(row["evaluator"])) for row in matching}
    return len(matching) == expected and len(keys) == expected


def _trial_name(task_id: str, agent_run: int, stage: str = "smoke") -> str:
    candidate = f"{task_id}-run-{agent_run}"
    if len(candidate) <= MAX_TRIAL_NAME_LENGTH:
        return candidate
    digest = hashlib.sha256(task_id.encode("utf-8")).hexdigest()[:12]
    return f"tau3-{stage}-{digest}-run-{agent_run}"


def _run_trial(
    *,
    task_id: str,
    agent_run: int,
    stage: str,
    task_dir: Path,
    trials_dir: Path,
    harbor_root: Path,
    model_id: str,
    credential_upstream_url: str,
    container_credential_url: str,
) -> Path:
    trial_name = _trial_name(task_id, agent_run, stage)
    legacy_trial_name = f"{task_id}-run-{agent_run}"
    for existing_name in dict.fromkeys((trial_name, legacy_trial_name)):
        existing_dir = trials_dir / existing_name
        if _trial_succeeded(existing_dir):
            print(f"reusing successful Harbor trial {existing_name}")  # noqa: T201
            return existing_dir

    trial_dir = trials_dir / trial_name
    if trial_dir.exists():
        raise RuntimeError(f"trial directory exists but is incomplete or failed: {trial_dir}")

    environment = os.environ.copy()
    environment.pop("AWS_PROFILE", None)
    environment.pop("AWS_PROFILE_NAME", None)
    environment.pop("OPENAI_API_KEY", None)
    environment.pop("OPENAI_BASE_URL", None)
    environment.pop("OPENAI_API_BASE", None)
    environment.update(
        {
            "ADA_CREDENTIALS_URL": credential_upstream_url,
            "AWS_CONTAINER_CREDENTIALS_FULL_URI": container_credential_url,
            "AWS_DEFAULT_REGION": "us-west-2",
            "AWS_REGION": "us-west-2",
            "PYTHONPATH": os.pathsep.join(value for value in (str(BASE_DIR), environment.get("PYTHONPATH")) if value),
            "UV_CACHE_DIR": "/private/tmp/uv-cache",
        }
    )
    factory_path = harbor_root / "examples/agents/strands"
    command = [
        "uv",
        "run",
        "--project",
        str(harbor_root),
        "harbor",
        "trial",
        "start",
        "--path",
        str(task_dir),
        "--trial-name",
        trial_name,
        "--trials-dir",
        str(trials_dir),
        "--agent",
        "strands",
        "--model",
        f"bedrock/{model_id}",
        "--agent-kwarg",
        f"factory_path={factory_path}",
        "--agent-env",
        f"AWS_CONTAINER_CREDENTIALS_FULL_URI={container_credential_url}",
        "--agent-env",
        "AWS_REGION=us-west-2",
        "--agent-env",
        "AWS_DEFAULT_REGION=us-west-2",
        "--env",
        "finch_environment:FinchEnvironment",
    ]
    print(f"starting Harbor trial {trial_name}")  # noqa: T201
    subprocess.run(command, check=True, env=environment)
    if not _trial_succeeded(trial_dir):
        raise RuntimeError(f"Harbor trial did not produce a valid result: {trial_dir}")
    return trial_dir


def collect(args: argparse.Namespace) -> None:
    config = _load_json(CONFIG_PATH)
    stage = str(args.stage)
    model_id = str(config["models"]["agent"]["model_id"])
    agent_runs = int(config["collection"][stage]["agent_runs"])
    judge_replays = int(config["collection"][stage]["judge_replays"])
    all_task_ids = _task_ids(stage)
    if args.shard_count < 1:
        raise ValueError("--shard-count must be at least 1")
    if not 0 <= args.shard_index < args.shard_count:
        raise ValueError("--shard-index must be between 0 and shard-count - 1")
    task_ids = all_task_ids[args.shard_index :: args.shard_count]
    print(  # noqa: T201
        f"collecting shard {args.shard_index + 1}/{args.shard_count}: {len(task_ids)} of {len(all_task_ids)} tasks"
    )
    os.environ.pop("AWS_PROFILE", None)
    os.environ.pop("AWS_PROFILE_NAME", None)
    os.environ["AWS_CONTAINER_CREDENTIALS_FULL_URI"] = args.host_credential_url
    os.environ["AWS_DEFAULT_REGION"] = "us-west-2"
    os.environ["AWS_REGION"] = "us-west-2"

    missing = [task_id for task_id in task_ids if not (args.tasks_dir / task_id).is_dir()]
    if missing:
        raise ValueError(f"prepared {stage} tasks are missing: {missing}")

    args.trials_dir.mkdir(parents=True, exist_ok=True)
    for task_index, task_id in enumerate(task_ids, start=1):
        for agent_run in range(agent_runs):
            print(  # noqa: T201
                f"[{task_index}/{len(task_ids)}] case={task_id}, agent_run={agent_run}"
            )
            trial_dir = _run_trial(
                task_id=task_id,
                agent_run=agent_run,
                stage=stage,
                task_dir=args.tasks_dir / task_id,
                trials_dir=args.trials_dir,
                harbor_root=args.harbor_root,
                model_id=model_id,
                credential_upstream_url=args.credential_upstream_url,
                container_credential_url=args.container_credential_url,
            )
            if _replay_complete(
                args.output,
                case_name=task_id,
                agent_run=agent_run,
                replays=judge_replays,
            ):
                print(  # noqa: T201
                    f"reusing complete evaluator rows for {task_id}-run-{agent_run}"
                )
                continue
            asyncio.run(
                replay(
                    trial_dir=trial_dir,
                    output_path=args.output,
                    agent_run=agent_run,
                    replays=judge_replays,
                )
            )

    expected = len(task_ids) * agent_runs * judge_replays * len(EVALUATOR_SCOPES)
    rows = _load_json(args.output)
    if len(rows) != expected:
        raise RuntimeError(f"expected {expected} {stage} rows, found {len(rows)}")
    print(f"{stage} collection complete: {expected} rows at {args.output}")  # noqa: T201


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=("smoke", "main"), default="smoke")
    parser.add_argument("--shard-count", type=int, default=1)
    parser.add_argument("--shard-index", type=int, default=0)
    parser.add_argument("--tasks-dir", type=Path, required=True)
    parser.add_argument("--trials-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--harbor-root", type=Path, required=True)
    parser.add_argument(
        "--credential-upstream-url",
        default="http://host.docker.internal:9911",
        help="Host ADA server URL used by the Finch credential sidecar",
    )
    parser.add_argument(
        "--container-credential-url",
        default="http://169.254.170.23/",
        help="Allowlisted credential sidecar URL used by workload containers",
    )
    parser.add_argument(
        "--host-credential-url",
        default="http://127.0.0.1:9911",
        help="ADA credential server URL used by host-side evaluator replays",
    )
    return parser.parse_args()


if __name__ == "__main__":
    arguments = parse_args()
    arguments.tasks_dir = arguments.tasks_dir.expanduser().resolve()
    arguments.trials_dir = arguments.trials_dir.expanduser().resolve()
    arguments.output = arguments.output.expanduser().resolve()
    arguments.harbor_root = arguments.harbor_root.expanduser().resolve()
    collect(arguments)
