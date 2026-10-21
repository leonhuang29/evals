"""Validate completed agent runs, judge replays, and the tidy pilot table."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "experiment_config.json"
PILOT_MANIFEST_PATH = BASE_DIR / "pilot_manifest.json"
RUNS_DIR = BASE_DIR / "runs"
SESSIONS_DIR = BASE_DIR / "sessions"
REPORT_PATH = BASE_DIR / "evaluation_report.json"
TIDY_PATH = BASE_DIR / "tidy_evaluations.json"
REGISTRY_PATH = BASE_DIR / "evaluator_registry.json"
SCORING_RESULTS_PATH = BASE_DIR / "analysis" / "scoring_results.json"
BOOTSTRAP_PATH = BASE_DIR / "analysis" / "bootstrap_distributions.json"


def load_json(path: Path) -> Any:
    return json.loads(path.read_text())


def validate() -> list[str]:
    errors: list[str] = []
    config = load_json(CONFIG_PATH)
    pilot = load_json(PILOT_MANIFEST_PATH)
    dimensions = config["expected_dimensions"]
    expected_evaluators = set(config["judge"]["evaluators"])
    expected_replays = set(range(config["judge"]["replays_per_run"]))

    expected_run_ids = {
        f"{case['name']}-t{trial}" for case in pilot["cases"] for trial in range(config["agent"]["runs_per_case"])
    }
    run_paths = sorted(RUNS_DIR.glob("*.json"))
    session_paths = sorted(SESSIONS_DIR.glob("*.json"))
    if {path.stem for path in run_paths} != expected_run_ids:
        errors.append("run manifest identifiers do not match the configured experiment")
    if {path.stem for path in session_paths} != expected_run_ids:
        errors.append("session identifiers do not match the configured experiment")

    for path in run_paths:
        run = load_json(path)
        if not run.get("output"):
            errors.append(f"{path.name}: missing agent output")
        if not run.get("diff"):
            errors.append(f"{path.name}: empty git diff")
        if not run.get("changed_files"):
            errors.append(f"{path.name}: no changed files")
        if run.get("finished_span_count", 0) <= 0:
            errors.append(f"{path.name}: no captured spans")
        if run.get("mapped_trace_count", 0) <= 0:
            errors.append(f"{path.name}: no mapped traces")
        if run.get("hidden_test", {}).get("status") != "passed":
            errors.append(f"{path.name}: behavioral hidden test did not pass")
        if not run.get("hidden_test", {}).get("test_sha256"):
            errors.append(f"{path.name}: hidden-test recheck provenance is missing")
        if "error" in run:
            errors.append(f"{path.name}: agent run error: {run['error']}")

    if not REPORT_PATH.is_file():
        errors.append("evaluation report is missing")
        return errors
    report = load_json(REPORT_PATH)
    if len(report) != dimensions["score_rows"]:
        errors.append(f"expected {dimensions['score_rows']} score rows, found {len(report)}")

    score_cells: set[tuple[str, int, str]] = set()
    grouped_replays: dict[tuple[str, str], set[int]] = defaultdict(set)
    for index, row in enumerate(report):
        run_id = row.get("case")
        replay = row.get("trial")
        evaluator = row.get("evaluator")
        score = row.get("score")
        if run_id not in expected_run_ids:
            errors.append(f"row {index}: unknown run id {run_id!r}")
        if evaluator not in expected_evaluators:
            errors.append(f"row {index}: unknown evaluator {evaluator!r}")
        if replay not in expected_replays:
            errors.append(f"row {index}: invalid replay {replay!r}")
        if not isinstance(score, (int, float)) or isinstance(score, bool) or not 0 <= score <= 1:
            errors.append(f"row {index}: invalid score {score!r}")
        cell = (run_id, replay, evaluator)
        if cell in score_cells:
            errors.append(f"duplicate score cell: {cell}")
        score_cells.add(cell)
        grouped_replays[(run_id, evaluator)].add(replay)

    for group, replays in grouped_replays.items():
        if replays != expected_replays:
            errors.append(f"{group}: replays {sorted(replays)} do not match {sorted(expected_replays)}")

    if not TIDY_PATH.is_file():
        errors.append("tidy table is missing")
        return errors
    tidy = load_json(TIDY_PATH)
    tidy_dimensions = tidy["dimensions"]
    expected_dimension_values = {
        "case_count": dimensions["cases"],
        "run_count": dimensions["runs"],
        "replay_count": dimensions["judge_replays"],
        "evaluator_count": dimensions["evaluators"],
        "row_count": dimensions["score_rows"],
    }
    for key, expected in expected_dimension_values.items():
        if tidy_dimensions.get(key) != expected:
            errors.append(f"tidy dimension {key} is {tidy_dimensions.get(key)}, expected {expected}")
    if len({row["observation_id"] for row in tidy["rows"]}) != len(tidy["rows"]):
        errors.append("tidy table has duplicate observation identifiers")

    if not REGISTRY_PATH.is_file():
        errors.append("evaluator registry is missing")
    else:
        registry = load_json(REGISTRY_PATH)
        if set(registry.get("evaluators", {})) != expected_evaluators:
            errors.append("evaluator registry does not match the configured evaluators")

    if not SCORING_RESULTS_PATH.is_file():
        errors.append("scoring results are missing")
    else:
        scoring = load_json(SCORING_RESULTS_PATH)
        if scoring.get("dataset_id") != config["experiment_id"]:
            errors.append("scoring results use the wrong dataset identifier")
        if scoring.get("design", {}).get("score_rows") != dimensions["score_rows"]:
            errors.append("scoring results use the wrong number of score rows")
        weights = scoring.get("provisional_weighting", {}).get("weights")
        if weights is None or abs(sum(weights.values()) - 1.0) > 1e-9:
            errors.append("bootstrap-mean pilot weights are missing or do not sum to one")
        if scoring.get("milestone_decision", {}).get("pilot_weights_ready_to_finalize") is not False:
            errors.append("pilot scoring results must not claim finalized weights")

    if not BOOTSTRAP_PATH.is_file():
        errors.append("bootstrap distributions are missing")
    else:
        bootstrap = load_json(BOOTSTRAP_PATH)
        if bootstrap.get("metadata", {}).get("replicates") != 2_000:
            errors.append("bootstrap distributions do not contain 2,000 replicates")

    return errors


if __name__ == "__main__":
    validation_errors = validate()
    if validation_errors:
        print("Experiment validation failed:")
        for validation_error in validation_errors:
            print(f"- {validation_error}")
        raise SystemExit(1)
    print(
        "Experiment validation passed: 5 cases, 10 runs, 3 replays, "
        "4 evaluators, 120 rows, 2,000 bootstrap replicates"
    )
