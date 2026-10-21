"""Validate the frozen run-level evaluator dataset."""

from __future__ import annotations

import ast
import hashlib
import json
import re
import runpy
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "source"
MANIFEST_PATH = ROOT / "dataset_manifest.json"
CHECKSUMS_PATH = ROOT / "checksums.sha256"
REPORT_PATH = SOURCE / "issue_broad_report.json"
CASE_PATTERN = re.compile(r"^(?P<task>.+)-t(?P<run_index>[0-9]+)$")
REQUIRED_ROW_FIELDS = {"trial", "case", "evaluator", "score", "test_pass", "reason"}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_checksums() -> dict[str, str]:
    checksums: dict[str, str] = {}
    for line in CHECKSUMS_PATH.read_text().splitlines():
        digest, relative_path = line.split(maxsplit=1)
        checksums[relative_path] = digest
    return checksums


def strict_rubric() -> str:
    tree = ast.parse((SOURCE / "stan_issue_eval_broad.py").read_text())
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if any(isinstance(target, ast.Name) and target.id == "STRICT_RUBRIC" for target in node.targets):
            value = ast.literal_eval(node.value)
            if not isinstance(value, str):
                raise ValueError("STRICT_RUBRIC is not a string")
            return value
    raise ValueError("STRICT_RUBRIC was not found")


def validate() -> list[str]:
    errors: list[str] = []
    manifest = json.loads(MANIFEST_PATH.read_text())
    dimensions = manifest["dimensions"]

    expected_checksums = load_checksums()
    actual_source_files = {
        path.relative_to(ROOT).as_posix()
        for path in SOURCE.rglob("*")
        if path.is_file()
    }
    if actual_source_files != set(expected_checksums):
        errors.append("source file set does not match checksums.sha256")

    for relative_path, expected_digest in expected_checksums.items():
        path = ROOT / relative_path
        if not path.is_file():
            errors.append(f"missing frozen file: {relative_path}")
        elif sha256(path) != expected_digest:
            errors.append(f"checksum mismatch: {relative_path}")

    rows = json.loads(REPORT_PATH.read_text())
    if not isinstance(rows, list):
        errors.append("canonical report must contain a JSON list")
        return errors
    if len(rows) != dimensions["score_rows"]:
        errors.append(f"expected {dimensions['score_rows']} rows, found {len(rows)}")

    expected_evaluators = set(manifest["evaluators"])
    expected_replays = set(range(dimensions["replays_per_run"]))
    cells: set[tuple[str, int, str]] = set()
    cases: set[str] = set()
    evaluators: set[str] = set()
    task_runs: dict[str, set[int]] = defaultdict(set)
    replay_groups: dict[tuple[str, str], set[int]] = defaultdict(set)

    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            errors.append(f"row {index} is not an object")
            continue
        missing = REQUIRED_ROW_FIELDS - row.keys()
        if missing:
            errors.append(f"row {index} is missing fields: {sorted(missing)}")
            continue

        case = row["case"]
        evaluator = row["evaluator"]
        replay = row["trial"]
        score = row["score"]

        if not isinstance(case, str):
            errors.append(f"row {index} has a non-string case")
            continue
        match = CASE_PATTERN.fullmatch(case)
        if match is None:
            errors.append(f"row {index} has an invalid case identifier: {case}")
            continue
        if not isinstance(evaluator, str):
            errors.append(f"row {index} has a non-string evaluator")
            continue
        if not isinstance(replay, int) or isinstance(replay, bool):
            errors.append(f"row {index} has a non-integer replay")
            continue
        if not isinstance(score, (int, float)) or isinstance(score, bool) or not 0.0 <= float(score) <= 1.0:
            errors.append(f"row {index} has an invalid score: {score!r}")
        if not isinstance(row["test_pass"], bool):
            errors.append(f"row {index} has a non-boolean test_pass")
        if not isinstance(row["reason"], str):
            errors.append(f"row {index} has a non-string reason")

        cell = (case, replay, evaluator)
        if cell in cells:
            errors.append(f"duplicate score cell: {cell}")
        cells.add(cell)

        task = match.group("task")
        run_index = int(match.group("run_index"))
        cases.add(case)
        evaluators.add(evaluator)
        task_runs[task].add(run_index)
        replay_groups[(case, evaluator)].add(replay)

    if len(cases) != dimensions["runs"]:
        errors.append(f"expected {dimensions['runs']} runs, found {len(cases)}")
    if len(task_runs) != dimensions["tasks"]:
        errors.append(f"expected {dimensions['tasks']} tasks, found {len(task_runs)}")
    if evaluators != expected_evaluators:
        errors.append(f"unexpected evaluator set: {sorted(evaluators)}")

    expected_run_indexes = set(range(dimensions["runs_per_task"]))
    for task, run_indexes in sorted(task_runs.items()):
        if run_indexes != expected_run_indexes:
            errors.append(f"{task} has run indexes {sorted(run_indexes)}, expected {sorted(expected_run_indexes)}")
    for group, replays in sorted(replay_groups.items()):
        if replays != expected_replays:
            errors.append(f"{group} has replays {sorted(replays)}, expected {sorted(expected_replays)}")

    expected_cell_count = dimensions["runs"] * dimensions["replays_per_run"] * dimensions["evaluators"]
    if len(cells) != expected_cell_count:
        errors.append(f"expected {expected_cell_count} unique score cells, found {len(cells)}")

    run_paths = sorted((SOURCE / "issue_runs").glob("*.json"))
    run_ids = {path.stem for path in run_paths}
    if len(run_paths) != dimensions["runs"]:
        errors.append(f"expected {dimensions['runs']} run manifests, found {len(run_paths)}")
    if run_ids != cases:
        errors.append("run manifest identifiers do not match report case identifiers")

    expected_commit = manifest["provenance"]["harness_sdk_commit"]
    for path in run_paths:
        run = json.loads(path.read_text())
        if not run.get("output"):
            errors.append(f"run has empty output: {path.name}")
        if not run.get("diff"):
            errors.append(f"run has empty diff: {path.name}")
        if run.get("harness_sdk_commit") != expected_commit:
            errors.append(f"run has unexpected harness commit: {path.name}")

    task_registry = runpy.run_path(str(SOURCE / "issue_cases.py"))["TASKS"]
    task_names = {task["name"] for task in task_registry}
    if task_names != set(task_runs):
        errors.append("task registry names do not match report task identifiers")
    for task in task_registry:
        prompt_path = SOURCE / task["prompt_file"]
        if not prompt_path.is_file():
            errors.append(f"missing task prompt: {task['prompt_file']}")

    commit = (SOURCE / "harness_sdk_commit.txt").read_text().strip()
    if commit != expected_commit:
        errors.append("harness_sdk_commit.txt does not match the manifest")

    rubric = strict_rubric()
    rubric_metadata = manifest["rubrics"]["senior-review-strict"]
    if hashlib.sha256(rubric.encode()).hexdigest() != rubric_metadata["sha256"]:
        errors.append("senior-review-strict rubric hash does not match the manifest")
    if len(rubric.encode()) != rubric_metadata["utf8_bytes"]:
        errors.append("senior-review-strict rubric size does not match the manifest")

    return errors


def main() -> None:
    errors = validate()
    if errors:
        print("Dataset validation failed:")
        for error in errors:
            print(f"- {error}")
        raise SystemExit(1)

    manifest = json.loads(MANIFEST_PATH.read_text())
    dimensions = manifest["dimensions"]
    print(
        "Dataset validation passed: "
        f"{dimensions['tasks']} tasks, "
        f"{dimensions['runs']} runs, "
        f"{dimensions['replays_per_run']} replays, "
        f"{dimensions['evaluators']} evaluators, "
        f"{dimensions['score_rows']} score rows."
    )


if __name__ == "__main__":
    main()
