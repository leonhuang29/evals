"""Atomically merge disjoint Tau3 calibration result shards."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any


def _load_rows(path: Path) -> list[dict[str, Any]]:
    last_error: json.JSONDecodeError | None = None
    for _ in range(10):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            last_error = error
            time.sleep(0.1)
            continue
        if not isinstance(value, list):
            raise ValueError(f"expected a JSON list at {path}")
        return value
    raise ValueError(f"could not read a complete JSON snapshot from {path}") from last_error


def merge(inputs: list[Path]) -> list[dict[str, Any]]:
    """Merge shard rows and reject conflicting observation keys."""
    merged: dict[tuple[str, int, int, str], dict[str, Any]] = {}
    for path in inputs:
        if not path.exists():
            continue
        for row in _load_rows(path):
            key = (
                str(row["case"]),
                int(row["agent_run"]),
                int(row["judge_replay"]),
                str(row["evaluator"]),
            )
            existing = merged.get(key)
            if existing is not None and existing != row:
                raise ValueError(f"conflicting observation across shards: {key}")
            merged[key] = row
    return [
        merged[key]
        for key in sorted(
            merged,
            key=lambda value: (value[0], value[1], value[2], value[3]),
        )
    ]


def _write_atomic(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def run(args: argparse.Namespace) -> None:
    last_row_count: int | None = None
    while True:
        rows = merge(args.inputs)
        _write_atomic(args.output, rows)
        if len(rows) != last_row_count:
            print(f"merged shard checkpoint: {len(rows)} rows")  # noqa: T201
            last_row_count = len(rows)
        if args.once:
            return
        time.sleep(args.poll_seconds)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", type=Path, nargs="+", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--poll-seconds", type=float, default=10.0)
    parser.add_argument("--once", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    arguments = parse_args()
    if arguments.poll_seconds <= 0:
        raise ValueError("--poll-seconds must be greater than zero")
    arguments.inputs = [path.expanduser().resolve() for path in arguments.inputs]
    arguments.output = arguments.output.expanduser().resolve()
    run(arguments)
