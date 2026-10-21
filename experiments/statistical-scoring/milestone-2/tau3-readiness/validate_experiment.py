"""Validate the frozen Tau3 calibration-readiness experiment contract."""

import argparse
import json
import math
from pathlib import Path
from typing import Any

from freeze_tasks import BASE_DIR, CONFIG_PATH, MANIFEST_PATH, build_manifest


def _load_object(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path.name} must contain an object")
    return data


def _validate_config(config: dict[str, Any]) -> None:
    if config.get("schema_version") != 1:
        raise ValueError("unsupported experiment config schema version")

    sampling = config["sampling"]
    domains = sampling["domains"]
    if len(domains) != len(set(domains)) or not domains:
        raise ValueError("sampling domains must be non-empty and unique")
    smoke_per_domain = sampling["smoke_cases_per_domain"]
    main_per_domain = sampling["main_cases_per_domain"]
    if not 0 < smoke_per_domain <= main_per_domain:
        raise ValueError("smoke case count must be positive and no larger than the main count")

    evaluators = config["evaluators"]
    evaluator_names = [evaluator["name"] for evaluator in evaluators]
    if len(evaluator_names) != len(set(evaluator_names)) or not evaluator_names:
        raise ValueError("evaluator names must be non-empty and unique")
    for evaluator in evaluators:
        step = evaluator["declared_step_size"]
        if (
            not isinstance(step, (int, float))
            or isinstance(step, bool)
            or not math.isfinite(step)
            or step <= 0
        ):
            raise ValueError(f"invalid step size for {evaluator['name']}: {step!r}")

    main_cases = len(domains) * main_per_domain
    collection = config["collection"]
    for stage in ("smoke", "main"):
        if collection[stage]["agent_runs"] < 2:
            raise ValueError(f"{stage} requires at least two agent runs")
        if collection[stage]["judge_replays"] < 2:
            raise ValueError(f"{stage} requires at least two judge replays")

    analysis = config["analysis"]
    if max(analysis["case_counts"]) > main_cases:
        raise ValueError("analysis case grid exceeds the main collection")
    if max(analysis["agent_run_counts"]) > collection["main"]["agent_runs"]:
        raise ValueError("analysis agent-run grid exceeds the main collection")
    if max(analysis["judge_replay_counts"]) > collection["main"]["judge_replays"]:
        raise ValueError("analysis replay grid exceeds the main collection")
    if analysis["bootstrap_replicates"] < 2:
        raise ValueError("analysis bootstrap requires at least two replicates")

    native_metric = config["native_metric"]
    if native_metric["included_in_learned_composite"]:
        raise ValueError("the native Tau3 reward must remain outside the learned composite")


def _validate_manifest(config: dict[str, Any], manifest: dict[str, Any]) -> None:
    if manifest.get("schema_version") != 1:
        raise ValueError("unsupported task manifest schema version")
    if manifest.get("experiment_id") != config["experiment_id"]:
        raise ValueError("task manifest belongs to a different experiment")

    tasks = manifest["tasks"]
    domains = config["sampling"]["domains"]
    smoke_per_domain = config["sampling"]["smoke_cases_per_domain"]
    main_per_domain = config["sampling"]["main_cases_per_domain"]
    expected_total = len(domains) * main_per_domain
    if len(tasks) != expected_total:
        raise ValueError(f"manifest contains {len(tasks)} tasks, expected {expected_total}")

    task_ids = [task["harbor_task_id"] for task in tasks]
    if len(task_ids) != len(set(task_ids)):
        raise ValueError("manifest contains duplicate Harbor task IDs")

    for domain in domains:
        domain_tasks = [task for task in tasks if task["domain"] == domain]
        smoke_tasks = [task for task in domain_tasks if "smoke" in task["stages"]]
        if len(domain_tasks) != main_per_domain:
            raise ValueError(
                f"domain {domain!r} has {len(domain_tasks)} main tasks, expected {main_per_domain}"
            )
        if len(smoke_tasks) != smoke_per_domain:
            raise ValueError(
                f"domain {domain!r} has {len(smoke_tasks)} smoke tasks, expected {smoke_per_domain}"
            )
        if any(task["stages"] not in (["main"], ["smoke", "main"]) for task in domain_tasks):
            raise ValueError(f"domain {domain!r} contains an invalid stage assignment")

    expected_sources = {
        "harbor_commit": config["sources"]["harbor"]["commit"],
        "tau2_bench_commit": config["sources"]["tau2_bench"]["commit"],
    }
    if manifest["sources"] != expected_sources:
        raise ValueError("manifest source commits do not match experiment_config.json")


def _score_rows(config: dict[str, Any], stage: str) -> int:
    domain_count = len(config["sampling"]["domains"])
    cases_per_domain = config["sampling"][f"{stage}_cases_per_domain"]
    evaluator_count = len(config["evaluators"])
    design = config["collection"][stage]
    return (
        domain_count
        * cases_per_domain
        * design["agent_runs"]
        * design["judge_replays"]
        * evaluator_count
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--harbor-root", type=Path)
    parser.add_argument("--tau2-root", type=Path)
    args = parser.parse_args()

    config = _load_object(CONFIG_PATH)
    manifest = _load_object(MANIFEST_PATH)
    _validate_config(config)
    _validate_manifest(config, manifest)

    if (args.harbor_root is None) != (args.tau2_root is None):
        raise ValueError("--harbor-root and --tau2-root must be provided together")
    if args.harbor_root is not None and args.tau2_root is not None:
        regenerated = build_manifest(
            args.harbor_root.expanduser().resolve(),
            args.tau2_root.expanduser().resolve(),
        )
        if regenerated != manifest:
            raise ValueError("task_manifest.json does not match the pinned source checkouts")

    print("Tau3 calibration-readiness contract: VALID")
    print(f"  experiment: {config['experiment_id']}")
    print(f"  smoke tasks: {sum('smoke' in task['stages'] for task in manifest['tasks'])}")
    print(f"  main tasks: {len(manifest['tasks'])}")
    print(f"  smoke evaluator rows: {_score_rows(config, 'smoke')}")
    print(f"  main evaluator rows: {_score_rows(config, 'main')}")
    print(f"  manifest: {MANIFEST_PATH.relative_to(BASE_DIR)}")


if __name__ == "__main__":
    main()
