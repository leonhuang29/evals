"""Freeze a deterministic, domain-balanced Tau3 task manifest."""

import argparse
import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "experiment_config.json"
MANIFEST_PATH = BASE_DIR / "task_manifest.json"


def _load_module(path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location("tau3_readiness_harbor_adapter", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not import Harbor Tau3 adapter from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _git_commit(repository: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _load_config() -> dict[str, Any]:
    data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("experiment_config.json must contain an object")
    return data


def build_manifest(harbor_root: Path, tau2_root: Path) -> dict[str, Any]:
    """Build the manifest from pinned Harbor and tau2/tau3 checkouts."""
    config = _load_config()
    expected_harbor_commit = config["sources"]["harbor"]["commit"]
    expected_tau2_commit = config["sources"]["tau2_bench"]["commit"]
    actual_harbor_commit = _git_commit(harbor_root)
    actual_tau2_commit = _git_commit(tau2_root)
    if actual_harbor_commit != expected_harbor_commit:
        raise ValueError(
            f"Harbor checkout is at {actual_harbor_commit}, expected {expected_harbor_commit}"
        )
    if actual_tau2_commit != expected_tau2_commit:
        raise ValueError(
            f"tau2-bench checkout is at {actual_tau2_commit}, expected {expected_tau2_commit}"
        )

    adapter_path = harbor_root / "adapters" / "tau3-bench" / "src" / "tau3_bench" / "adapter.py"
    if not adapter_path.is_file():
        raise FileNotFoundError(f"missing Harbor Tau3 adapter: {adapter_path}")
    adapter_module = _load_module(adapter_path)
    adapter = adapter_module.Tau3BenchAdapter(
        output_dir=BASE_DIR / "_unused_generated_tasks",
        tau2_root=tau2_root,
        split_name=config["sources"]["tau2_bench"]["split"],
        domains=config["sampling"]["domains"],
    )
    tasks = adapter._load_tau_tasks()

    seed = config["sampling"]["seed"]
    main_count = config["sampling"]["main_cases_per_domain"]
    smoke_count = config["sampling"]["smoke_cases_per_domain"]
    selected: list[dict[str, Any]] = []
    for domain in config["sampling"]["domains"]:
        domain_tasks = [task for task in tasks if task.domain == domain]
        ranked = sorted(
            domain_tasks,
            key=lambda task: _sha256(f"{seed}:{task.local_task_id}"),
        )
        if len(ranked) < main_count:
            raise ValueError(
                f"domain {domain!r} has {len(ranked)} tasks, fewer than requested {main_count}"
            )
        for index, task in enumerate(ranked[:main_count]):
            selected.append(
                {
                    "domain": task.domain,
                    "source_task_id": task.source_id,
                    "harbor_task_id": task.local_task_id,
                    "source_sha256": _sha256(_canonical_json(task.task)),
                    "stages": ["smoke", "main"] if index < smoke_count else ["main"],
                }
            )

    return {
        "schema_version": 1,
        "experiment_id": config["experiment_id"],
        "sources": {
            "harbor_commit": actual_harbor_commit,
            "tau2_bench_commit": actual_tau2_commit,
        },
        "selection": {
            "method": config["sampling"]["method"],
            "seed": seed,
            "smoke_cases_per_domain": smoke_count,
            "main_cases_per_domain": main_count,
        },
        "tasks": selected,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--harbor-root", type=Path, required=True)
    parser.add_argument("--tau2-root", type=Path, required=True)
    args = parser.parse_args()

    manifest = build_manifest(
        args.harbor_root.expanduser().resolve(),
        args.tau2_root.expanduser().resolve(),
    )
    MANIFEST_PATH.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    smoke_count = sum("smoke" in task["stages"] for task in manifest["tasks"])
    print(f"Wrote {MANIFEST_PATH.name}: {smoke_count} smoke tasks, {len(manifest['tasks'])} main tasks")


if __name__ == "__main__":
    main()
