"""Run the Milestone 1 scoring estimator on the dataset-v2 pilot."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

BASE_DIR = Path(__file__).resolve().parent
TABLE_PATH = BASE_DIR / "tidy_evaluations.json"
REGISTRY_PATH = BASE_DIR / "evaluator_registry.json"
ANALYSIS_DIR = BASE_DIR / "analysis"
RESULTS_PATH = ANALYSIS_DIR / "scoring_results.json"
BOOTSTRAP_PATH = ANALYSIS_DIR / "bootstrap_distributions.json"
RESULTS_NOTE_PATH = ANALYSIS_DIR / "RESULTS.md"
SHARED_ANALYSIS_DIR = BASE_DIR.parents[1] / "milestone-1" / "run-level-dataset-v1"
SHARED_ANALYSIS_PATH = SHARED_ANALYSIS_DIR / "scoring_analysis.py"
BOOTSTRAP_REPLICATES = 2_000
BOOTSTRAP_SEED = 20_260_930


def load_shared_analysis() -> ModuleType:
    sys.path.insert(0, str(SHARED_ANALYSIS_DIR))
    spec = importlib.util.spec_from_file_location("milestone_1_scoring_analysis", SHARED_ANALYSIS_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load shared scoring analysis from {SHARED_ANALYSIS_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    module.BOOTSTRAP_REPLICATES = BOOTSTRAP_REPLICATES
    module.BOOTSTRAP_SEED = BOOTSTRAP_SEED
    return module


def validate_registry(registry: dict[str, Any], evaluator_names: list[str]) -> None:
    registered = set(registry["evaluators"])
    observed = set(evaluator_names)
    if registered != observed:
        raise ValueError(
            f"registry evaluators do not match the tidy table: "
            f"missing={sorted(observed - registered)}, extra={sorted(registered - observed)}"
        )
    for name, metadata in registry["evaluators"].items():
        step = metadata["scale"]["declared_step"]["value"]
        if not isinstance(step, (int, float)) or isinstance(step, bool) or step <= 0:
            raise ValueError(f"{name} has invalid declared step {step!r}")


def fmt(value: float | None, digits: int = 4) -> str:
    return "undefined" if value is None else f"{value:.{digits}f}"


def interval(summary: dict[str, Any]) -> str:
    lower = summary["lower_2_5"]
    upper = summary["upper_97_5"]
    if lower is None or upper is None:
        return "undefined"
    return f"[{lower:.4f}, {upper:.4f}]"


def render_results(results: dict[str, Any]) -> str:
    lines = [
        "# Dataset v2 Pilot Scoring Results",
        "",
        f"**Dataset:** `{results['dataset_id']}`  ",
        f"**Bootstrap:** {results['bootstrap']['replicates']:,} hierarchical replicates  ",
        "**Status:** Pilot validation; not production weights",
        "",
        "## Evaluator statistics",
        "",
        "| Evaluator | Mean | Case var | Run var | Judge var | Design r | At 1.0 | Moving runs | Avg replay range |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name, result in results["evaluators"].items():
        point = result["point_estimate"]
        counts = point["counts"]
        lines.append(
            f"| `{name}` | {point['scores']['suite_mean']:.4f} | "
            f"{point['variance_components']['case']:.6f} | "
            f"{point['variance_components']['agent']:.6f} | "
            f"{point['variance_components']['judge']:.6f} | "
            f"{point['reliability']['current_design']:.4f} | "
            f"{100 * point['scores']['fraction_at_scale_maximum']:.1f}% | "
            f"{counts['moving_runs']}/{counts['cases'] * counts['runs_per_case']} | "
            f"{point['replay_movement']['average_range']:.4f} |"
        )

    recommended = results["weighting_results"]["primary"]["inverse_sqrt_step"]
    raw_weights = recommended["point_estimate"]["weights"]
    stabilized_weights = recommended["bootstrap_mean_estimate"]["weights"]
    lines.extend(
        [
            "",
            "## Reliability / sqrt(step) weights",
            "",
            "| Evaluator | Raw point weight | Bootstrap-mean weight | 95% bootstrap interval |",
            "|---|---:|---:|---:|",
        ]
    )
    for name in results["evaluator_sets"]["primary"]:
        bootstrap = recommended["bootstrap_intervals"]["weights"][name]
        lines.append(
            f"| `{name}` | {fmt(None if raw_weights is None else raw_weights[name])} | "
            f"{fmt(None if stabilized_weights is None else stabilized_weights[name])} | "
            f"{interval(bootstrap)} |"
        )

    undefined = recommended["bootstrap_intervals"]["composite_suite_mean"]["undefined_replicates"]
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "- All 10 agent patches pass their case-specific behavioral hidden test.",
            (
                "- `senior-review-strict` is the only evaluator with positive corrected "
                "between-case variance in the point estimate."
            ),
            (
                "- The raw reliability-based weight is therefore a boundary estimate, not evidence "
                "that other evaluators are universally worthless."
            ),
            (
                "- `FaithfulnessEvaluator` is fully saturated at 1.0 and contributes no measurable "
                "discrimination in this pilot."
            ),
            (
                "- `ConcisenessEvaluator` remains the noisiest in absolute score units because its "
                "disagreements are 0.5 jumps."
            ),
            f"- {undefined} of {results['bootstrap']['replicates']:,} reliability-based bootstrap replicates "
            "have no measurable case signal and are excluded from the bootstrap-mean vector.",
            "- Five outer cases are enough to exercise the pipeline, but not enough to finalize evaluator weights.",
            "",
            "## Decision",
            "",
            "The expanded-data pipeline is sound: generation, trace capture, hidden-test verification,",
            "judge replay, tidy-table construction, variance decomposition, and hierarchical bootstrap",
            "all completed reproducibly. The pilot supports continuing with the remaining selected cases.",
            "Its weights are sensitivity evidence only and should not replace the v1 provisional vector.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    analysis = load_shared_analysis()
    dataset, evaluator_names, table = analysis.load_dataset(TABLE_PATH)
    registry = json.loads(REGISTRY_PATH.read_text())
    validate_registry(registry, evaluator_names)
    sets = analysis.evaluator_sets(registry)

    statistics_by_evaluator = analysis.compute_all_evaluator_statistics(dataset, evaluator_names)
    weighting_results = analysis.compute_weighting_results(statistics_by_evaluator, registry, sets)
    distributions = analysis.run_bootstrap(dataset, evaluator_names, registry, sets)
    bootstrap_summary = analysis.summarize_bootstrap(distributions, evaluator_names, sets)
    results = analysis.build_results(
        table,
        registry,
        statistics_by_evaluator,
        sets,
        weighting_results,
        bootstrap_summary,
    )
    results["analysis_version"] = 1
    results["scoring_note"] = "../../milestone-1/run-level-dataset-v1/SCORING_NOTE.md"
    results["validation_context"] = {
        "kind": "dataset_v2_pilot",
        "purpose": "Validate generation and scoring on five new cases before expanding the full dataset.",
        "replace_v1_provisional_weights": False,
    }
    results["milestone_decision"] = {
        "expanded_pipeline_sound_enough_to_continue": True,
        "pilot_weights_ready_to_finalize": False,
        "recommendation": "Generate the remaining selected cases under the same frozen configuration.",
    }

    ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)
    RESULTS_PATH.write_text(json.dumps(results, indent=2, ensure_ascii=True) + "\n")
    BOOTSTRAP_PATH.write_text(json.dumps(distributions, separators=(",", ":")) + "\n")
    RESULTS_NOTE_PATH.write_text(render_results(results) + "\n")
    print(f"Wrote {RESULTS_PATH.relative_to(BASE_DIR)}")
    print(f"Wrote {BOOTSTRAP_PATH.relative_to(BASE_DIR)}")
    print(f"Wrote {RESULTS_NOTE_PATH.relative_to(BASE_DIR)}")


if __name__ == "__main__":
    main()
