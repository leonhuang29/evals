"""Generate calibration analyses when balanced collection checkpoints complete."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from compare_configurations import (
    CONFIG_PATH,
    _complete_cases,
    _load_json,
    _render_markdown,
    _step_sizes,
    compare,
)
from task_selection import ordered_task_ids

BASE_DIR = Path(__file__).resolve().parent
MANIFEST_PATH = BASE_DIR / "task_manifest.json"


def _checkpoint_rows(
    rows: list[dict[str, Any]],
    *,
    checkpoint_cases: list[str],
    complete_cases: set[str],
) -> list[dict[str, Any]] | None:
    if not set(checkpoint_cases).issubset(complete_cases):
        return None
    selected = set(checkpoint_cases)
    return [row for row in rows if str(row["case"]) in selected]


def _write_checkpoint(
    *,
    rows: list[dict[str, Any]],
    config: dict[str, Any],
    stage: str,
    output_dir: Path,
    case_count: int,
    bootstrap_replicates: int,
    subsamples: int,
) -> None:
    checkpoint_dir = output_dir / f"{case_count:03d}-cases"
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    results = compare(
        rows,
        config,
        stage=stage,
        bootstrap_replicates=bootstrap_replicates,
        subsamples=subsamples,
    )
    (checkpoint_dir / "configuration_comparison.json").write_text(
        json.dumps(results, indent=2) + "\n",
        encoding="utf-8",
    )
    (checkpoint_dir / "CONFIGURATION_COMPARISON.md").write_text(
        _render_markdown(results),
        encoding="utf-8",
    )
    print(  # noqa: T201
        f"wrote {case_count}-case checkpoint analysis to {checkpoint_dir}"
    )


def monitor(args: argparse.Namespace) -> None:
    config = _load_json(CONFIG_PATH)
    manifest = _load_json(MANIFEST_PATH)
    stage = str(args.stage)
    task_ids = ordered_task_ids(
        manifest,
        stage=stage,
        domain_order=[str(domain) for domain in config["sampling"]["domains"]],
    )
    checkpoints = [int(value) for value in config["analysis"]["case_counts"] if int(value) <= len(task_ids)]
    evaluator_names = tuple(sorted(_step_sizes(config)))
    run_count = int(config["collection"][stage]["agent_runs"])
    replay_count = int(config["collection"][stage]["judge_replays"])
    last_complete_count: int | None = None

    while True:
        if args.input.exists():
            try:
                rows = _load_json(args.input)
            except ValueError:
                rows = []
            complete, _, _ = _complete_cases(
                rows,
                evaluator_names=evaluator_names,
                run_count=run_count,
                replay_count=replay_count,
            )
            complete_cases = set(complete)
            if len(complete_cases) != last_complete_count:
                print(  # noqa: T201
                    f"checkpoint monitor: {len(complete_cases)}/{len(task_ids)} complete cases"
                )
                last_complete_count = len(complete_cases)

            for case_count in checkpoints:
                checkpoint_dir = args.output_dir / f"{case_count:03d}-cases"
                result_path = checkpoint_dir / "configuration_comparison.json"
                if result_path.exists():
                    continue
                selected_rows = _checkpoint_rows(
                    rows,
                    checkpoint_cases=task_ids[:case_count],
                    complete_cases=complete_cases,
                )
                if selected_rows is not None:
                    _write_checkpoint(
                        rows=selected_rows,
                        config=config,
                        stage=stage,
                        output_dir=args.output_dir,
                        case_count=case_count,
                        bootstrap_replicates=args.bootstrap_replicates,
                        subsamples=args.subsamples,
                    )

            if all(
                (args.output_dir / f"{case_count:03d}-cases" / "configuration_comparison.json").exists()
                for case_count in checkpoints
            ):
                print("all checkpoint analyses complete")  # noqa: T201
                return

        if args.once:
            return
        time.sleep(args.poll_seconds)


def parse_args() -> argparse.Namespace:
    config = _load_json(CONFIG_PATH)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--stage",
        choices=tuple(config["collection"]),
        default="main",
    )
    parser.add_argument("--poll-seconds", type=float, default=30.0)
    parser.add_argument(
        "--bootstrap-replicates",
        type=int,
        default=int(config["analysis"]["bootstrap_replicates"]),
    )
    parser.add_argument(
        "--subsamples",
        type=int,
        default=int(config["analysis"]["subsamples_per_design"]),
    )
    parser.add_argument("--once", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    arguments = parse_args()
    if arguments.poll_seconds <= 0:
        raise ValueError("--poll-seconds must be greater than zero")
    if arguments.bootstrap_replicates < 2:
        raise ValueError("--bootstrap-replicates must be at least 2")
    if arguments.subsamples < 1:
        raise ValueError("--subsamples must be at least 1")
    arguments.input = arguments.input.expanduser().resolve()
    arguments.output_dir = arguments.output_dir.expanduser().resolve()
    monitor(arguments)
