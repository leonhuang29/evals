"""Statistical scoring analysis for the frozen run-level evaluator dataset."""

from __future__ import annotations

import json
import math
import random
import statistics
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from validate_dataset import validate as validate_dataset
from validate_evaluator_registry import validate as validate_evaluator_registry

ROOT = Path(__file__).resolve().parent
TABLE_PATH = ROOT / "derived" / "tidy_evaluations.json"
REGISTRY_PATH = ROOT / "evaluator_registry.json"
RESULTS_PATH = ROOT / "derived" / "scoring_results.json"
BOOTSTRAP_PATH = ROOT / "derived" / "bootstrap_distributions.json"
RESULTS_NOTE_PATH = ROOT / "RESULTS.md"

BOOTSTRAP_REPLICATES = 2_000
BOOTSTRAP_SEED = 20_260_929
EPSILON = 1e-15
WEIGHTING_SCHEMES = (
    "equal",
    "reliability",
    "inverse_step",
    "inverse_sqrt_step",
)


@dataclass(frozen=True)
class RunScores:
    run_id: str
    replays: tuple[dict[str, float], ...]


@dataclass(frozen=True)
class CaseScores:
    case_id: str
    runs: tuple[RunScores, ...]


Dataset = tuple[CaseScores, ...]


def sample_variance(values: Iterable[float]) -> float:
    values_list = list(values)
    if len(values_list) < 2:
        return 0.0
    return statistics.variance(values_list)


def mean(values: Iterable[float]) -> float:
    return statistics.fmean(values)


def percentile(values: Iterable[float | None], probability: float) -> float | None:
    defined = sorted(value for value in values if value is not None and math.isfinite(value))
    if not defined:
        return None
    if len(defined) == 1:
        return defined[0]

    position = (len(defined) - 1) * probability
    lower_index = math.floor(position)
    upper_index = math.ceil(position)
    if lower_index == upper_index:
        return defined[lower_index]
    fraction = position - lower_index
    return defined[lower_index] + fraction * (defined[upper_index] - defined[lower_index])


def interval_summary(values: list[float | None]) -> dict[str, int | float | None]:
    defined_values = [value for value in values if value is not None and math.isfinite(value)]
    defined_count = len(defined_values)
    return {
        "mean": mean(defined_values) if defined_values else None,
        "lower_2_5": percentile(values, 0.025),
        "median": percentile(values, 0.5),
        "upper_97_5": percentile(values, 0.975),
        "defined_replicates": defined_count,
        "undefined_replicates": len(values) - defined_count,
    }


def load_dataset(table_path: Path = TABLE_PATH) -> tuple[Dataset, list[str], dict[str, Any]]:
    table = json.loads(table_path.read_text())
    evaluator_names = list(table["dimensions"]["evaluator_names"])
    rows = table["rows"]

    replay_vectors: dict[tuple[str, str, int], dict[str, float]] = {}
    case_runs: dict[str, set[str]] = {}
    run_replays: dict[tuple[str, str], set[int]] = {}

    for row in rows:
        case_id = row["case_id"]
        run_id = row["run_id"]
        replay_id = row["replay_id"]
        evaluator_name = row["evaluator_name"]
        key = (case_id, run_id, replay_id)
        replay_vectors.setdefault(key, {})[evaluator_name] = float(row["score"])
        case_runs.setdefault(case_id, set()).add(run_id)
        run_replays.setdefault((case_id, run_id), set()).add(replay_id)

    expected_evaluators = set(evaluator_names)
    for key, scores in replay_vectors.items():
        if set(scores) != expected_evaluators:
            raise ValueError(f"{key} does not contain every evaluator")

    cases: list[CaseScores] = []
    for case_id in sorted(case_runs):
        runs: list[RunScores] = []
        for run_id in sorted(case_runs[case_id]):
            replays = tuple(
                replay_vectors[(case_id, run_id, replay_id)] for replay_id in sorted(run_replays[(case_id, run_id)])
            )
            runs.append(RunScores(run_id=run_id, replays=replays))
        cases.append(CaseScores(case_id=case_id, runs=tuple(runs)))

    dataset = tuple(cases)
    validate_balanced_dataset(dataset, evaluator_names)
    return dataset, evaluator_names, table


def validate_balanced_dataset(dataset: Dataset, evaluator_names: list[str]) -> tuple[int, int, int]:
    if not dataset:
        raise ValueError("dataset is empty")

    run_counts = {len(case.runs) for case in dataset}
    if len(run_counts) != 1:
        raise ValueError(f"dataset is not balanced across runs: {sorted(run_counts)}")
    run_count = run_counts.pop()
    if run_count < 2:
        raise ValueError("variance decomposition requires at least two runs per case")

    replay_counts = {len(run.replays) for case in dataset for run in case.runs}
    if len(replay_counts) != 1:
        raise ValueError(f"dataset is not balanced across replays: {sorted(replay_counts)}")
    replay_count = replay_counts.pop()
    if replay_count < 2:
        raise ValueError("variance decomposition requires at least two replays per run")

    expected_evaluators = set(evaluator_names)
    for case in dataset:
        for run in case.runs:
            for replay in run.replays:
                if set(replay) != expected_evaluators:
                    raise ValueError(f"{case.case_id}/{run.run_id} has an incomplete evaluator vector")

    return len(dataset), run_count, replay_count


def safe_reliability(signal: float, noise_terms: Iterable[float]) -> float:
    denominator = signal + sum(noise_terms)
    if denominator <= EPSILON:
        return 0.0
    return signal / denominator


def truncate_variance(value: float) -> float:
    if value <= EPSILON:
        return 0.0
    return value


def compute_evaluator_statistics(dataset: Dataset, evaluator_name: str) -> dict[str, Any]:
    case_count = len(dataset)
    run_count = len(dataset[0].runs)
    replay_count = len(dataset[0].runs[0].replays)

    raw_scores: list[float] = []
    replay_variances: list[float] = []
    replay_ranges: list[float] = []
    moving_runs = 0
    run_means_by_case: list[list[float]] = []
    run_medians_by_case: list[list[float]] = []

    for case in dataset:
        run_means: list[float] = []
        run_medians: list[float] = []
        for run in case.runs:
            replay_scores = [replay[evaluator_name] for replay in run.replays]
            raw_scores.extend(replay_scores)
            replay_variances.append(sample_variance(replay_scores))
            replay_range = max(replay_scores) - min(replay_scores)
            replay_ranges.append(replay_range)
            moving_runs += replay_range > EPSILON
            run_means.append(mean(replay_scores))
            run_medians.append(float(statistics.median(replay_scores)))
        run_means_by_case.append(run_means)
        run_medians_by_case.append(run_medians)

    judge_variance = mean(replay_variances)
    observed_run_variance = mean(sample_variance(run_means) for run_means in run_means_by_case)
    agent_variance_raw = observed_run_variance - judge_variance / replay_count
    agent_variance = truncate_variance(agent_variance_raw)

    case_means = [mean(run_means) for run_means in run_means_by_case]
    case_median_scores = [mean(run_medians) for run_medians in run_medians_by_case]
    observed_case_variance = sample_variance(case_means)
    case_variance_raw = (
        observed_case_variance - agent_variance_raw / run_count - judge_variance / (run_count * replay_count)
    )
    case_variance = truncate_variance(case_variance_raw)

    reliability_single = safe_reliability(
        case_variance,
        (agent_variance, judge_variance),
    )
    reliability_design = safe_reliability(
        case_variance,
        (
            agent_variance / run_count,
            judge_variance / (run_count * replay_count),
        ),
    )

    unique_scores = sorted(set(raw_scores))
    maximum_score = 1.0
    scores_at_maximum = sum(abs(score - maximum_score) <= EPSILON for score in raw_scores)

    return {
        "counts": {
            "cases": case_count,
            "runs_per_case": run_count,
            "replays_per_run": replay_count,
            "raw_scores": len(raw_scores),
            "moving_runs": moving_runs,
        },
        "scores": {
            "suite_mean": mean(case_means),
            "suite_replay_median": mean(case_median_scores),
            "raw_mean": mean(raw_scores),
            "raw_sample_variance": sample_variance(raw_scores),
            "observed_minimum": min(raw_scores),
            "observed_maximum": max(raw_scores),
            "unique_values": unique_scores,
            "unique_value_count": len(unique_scores),
            "fraction_at_scale_maximum": scores_at_maximum / len(raw_scores),
        },
        "replay_movement": {
            "moving_run_fraction": moving_runs / (case_count * run_count),
            "average_range": mean(replay_ranges),
            "maximum_range": max(replay_ranges),
        },
        "variance_components": {
            "judge": judge_variance,
            "observed_run_means": observed_run_variance,
            "agent_raw": agent_variance_raw,
            "agent": agent_variance,
            "observed_case_means": observed_case_variance,
            "case_raw": case_variance_raw,
            "case": case_variance,
        },
        "reliability": {
            "single_measurement": reliability_single,
            "current_design": reliability_design,
        },
    }


def compute_all_evaluator_statistics(dataset: Dataset, evaluator_names: list[str]) -> dict[str, dict[str, Any]]:
    return {evaluator_name: compute_evaluator_statistics(dataset, evaluator_name) for evaluator_name in evaluator_names}


def evaluator_sets(registry: dict[str, Any]) -> dict[str, list[str]]:
    evaluators = registry["evaluators"]
    primary = [
        name for name, metadata in evaluators.items() if metadata["composite"]["status"] in {"included", "provisional"}
    ]
    all_evaluators = list(evaluators)
    included = [name for name, metadata in evaluators.items() if metadata["composite"]["status"] == "included"]
    return {
        "primary": primary,
        "all": all_evaluators,
        "included_only": included,
    }


def compute_weights(
    statistics_by_evaluator: dict[str, dict[str, Any]],
    registry: dict[str, Any],
    evaluator_names: list[str],
    scheme: str,
) -> dict[str, float] | None:
    if not evaluator_names:
        return None
    if scheme == "equal":
        return {name: 1.0 / len(evaluator_names) for name in evaluator_names}

    unnormalized: dict[str, float] = {}
    for name in evaluator_names:
        reliability = statistics_by_evaluator[name]["reliability"]["current_design"]
        step = registry["evaluators"][name]["scale"]["declared_step"]["value"]
        if scheme == "reliability":
            value = reliability
        elif scheme == "inverse_step":
            value = reliability / step
        elif scheme == "inverse_sqrt_step":
            value = reliability / math.sqrt(step)
        else:
            raise ValueError(f"unknown weighting scheme: {scheme}")
        unnormalized[name] = value

    total = sum(unnormalized.values())
    if total <= EPSILON:
        return None
    return {name: value / total for name, value in unnormalized.items()}


def compute_composite(
    statistics_by_evaluator: dict[str, dict[str, Any]],
    weights: dict[str, float] | None,
    score_key: str,
) -> float | None:
    if weights is None:
        return None
    return sum(weight * statistics_by_evaluator[name]["scores"][score_key] for name, weight in weights.items())


def compute_weighting_results(
    statistics_by_evaluator: dict[str, dict[str, Any]],
    registry: dict[str, Any],
    sets: dict[str, list[str]],
) -> dict[str, dict[str, Any]]:
    results: dict[str, dict[str, Any]] = {}
    for set_name in ("primary", "all"):
        names = sets[set_name]
        results[set_name] = {}
        for scheme in WEIGHTING_SCHEMES:
            weights = compute_weights(statistics_by_evaluator, registry, names, scheme)
            results[set_name][scheme] = {
                "weights": weights,
                "composite_suite_mean": compute_composite(statistics_by_evaluator, weights, "suite_mean"),
                "composite_replay_median": compute_composite(
                    statistics_by_evaluator,
                    weights,
                    "suite_replay_median",
                ),
            }
    return results


def bootstrap_dataset(dataset: Dataset, rng: random.Random) -> Dataset:
    sampled_cases: list[CaseScores] = []
    for case_slot in range(len(dataset)):
        source_case = rng.choice(dataset)
        sampled_runs: list[RunScores] = []
        for run_slot in range(len(source_case.runs)):
            source_run = rng.choice(source_case.runs)
            sampled_replays = tuple(dict(rng.choice(source_run.replays)) for _ in range(len(source_run.replays)))
            sampled_runs.append(
                RunScores(
                    run_id=f"{source_run.run_id}#bootstrap-run-{run_slot}",
                    replays=sampled_replays,
                )
            )
        sampled_cases.append(
            CaseScores(
                case_id=f"{source_case.case_id}#bootstrap-case-{case_slot}",
                runs=tuple(sampled_runs),
            )
        )
    return tuple(sampled_cases)


def initialize_bootstrap_distributions(
    evaluator_names: list[str],
    sets: dict[str, list[str]],
) -> dict[str, Any]:
    evaluator_metrics = (
        "suite_mean",
        "suite_replay_median",
        "judge_variance",
        "agent_variance_raw",
        "agent_variance",
        "case_variance_raw",
        "case_variance",
        "reliability_single",
        "reliability_design",
    )
    distributions: dict[str, Any] = {
        "metadata": {
            "replicates": BOOTSTRAP_REPLICATES,
            "seed": BOOTSTRAP_SEED,
            "method": "hierarchical case-run-replay bootstrap with evaluator vectors resampled together",
        },
        "evaluators": {name: {metric: [] for metric in evaluator_metrics} for name in evaluator_names},
        "weighting": {},
    }

    for set_name in ("primary", "all"):
        distributions["weighting"][set_name] = {}
        for scheme in WEIGHTING_SCHEMES:
            distributions["weighting"][set_name][scheme] = {
                "weights": {name: [] for name in sets[set_name]},
                "composite_suite_mean": [],
                "composite_replay_median": [],
            }
    return distributions


def append_evaluator_bootstrap_metrics(
    distributions: dict[str, Any],
    statistics_by_evaluator: dict[str, dict[str, Any]],
) -> None:
    for name, stats in statistics_by_evaluator.items():
        target = distributions["evaluators"][name]
        target["suite_mean"].append(stats["scores"]["suite_mean"])
        target["suite_replay_median"].append(stats["scores"]["suite_replay_median"])
        target["judge_variance"].append(stats["variance_components"]["judge"])
        target["agent_variance_raw"].append(stats["variance_components"]["agent_raw"])
        target["agent_variance"].append(stats["variance_components"]["agent"])
        target["case_variance_raw"].append(stats["variance_components"]["case_raw"])
        target["case_variance"].append(stats["variance_components"]["case"])
        target["reliability_single"].append(stats["reliability"]["single_measurement"])
        target["reliability_design"].append(stats["reliability"]["current_design"])


def append_weighting_bootstrap_metrics(
    distributions: dict[str, Any],
    weighting_results: dict[str, dict[str, Any]],
    sets: dict[str, list[str]],
) -> None:
    for set_name in ("primary", "all"):
        for scheme in WEIGHTING_SCHEMES:
            result = weighting_results[set_name][scheme]
            target = distributions["weighting"][set_name][scheme]
            weights = result["weights"]
            for name in sets[set_name]:
                target["weights"][name].append(None if weights is None else weights[name])
            target["composite_suite_mean"].append(result["composite_suite_mean"])
            target["composite_replay_median"].append(result["composite_replay_median"])


def run_bootstrap(
    dataset: Dataset,
    evaluator_names: list[str],
    registry: dict[str, Any],
    sets: dict[str, list[str]],
) -> dict[str, Any]:
    rng = random.Random(BOOTSTRAP_SEED)
    distributions = initialize_bootstrap_distributions(evaluator_names, sets)

    for replicate in range(BOOTSTRAP_REPLICATES):
        sampled_dataset = bootstrap_dataset(dataset, rng)
        stats = compute_all_evaluator_statistics(sampled_dataset, evaluator_names)
        weights = compute_weighting_results(stats, registry, sets)
        append_evaluator_bootstrap_metrics(distributions, stats)
        append_weighting_bootstrap_metrics(distributions, weights, sets)
        if (replicate + 1) % 500 == 0:
            print(f"bootstrap {replicate + 1}/{BOOTSTRAP_REPLICATES}")

    return distributions


def summarize_bootstrap(
    distributions: dict[str, Any],
    evaluator_names: list[str],
    sets: dict[str, list[str]],
) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "evaluators": {},
        "weighting": {},
    }
    for name in evaluator_names:
        summary["evaluators"][name] = {
            metric: interval_summary(values) for metric, values in distributions["evaluators"][name].items()
        }

    for set_name in ("primary", "all"):
        summary["weighting"][set_name] = {}
        for scheme in WEIGHTING_SCHEMES:
            source = distributions["weighting"][set_name][scheme]
            summary["weighting"][set_name][scheme] = {
                "weights": {name: interval_summary(source["weights"][name]) for name in sets[set_name]},
                "composite_suite_mean": interval_summary(source["composite_suite_mean"]),
                "composite_replay_median": interval_summary(source["composite_replay_median"]),
            }
    return summary


def build_results(
    table: dict[str, Any],
    registry: dict[str, Any],
    statistics_by_evaluator: dict[str, dict[str, Any]],
    sets: dict[str, list[str]],
    weighting_results: dict[str, dict[str, Any]],
    bootstrap_summary: dict[str, Any],
) -> dict[str, Any]:
    evaluator_results: dict[str, Any] = {}
    for name, stats in statistics_by_evaluator.items():
        registry_entry = registry["evaluators"][name]
        evaluator_results[name] = {
            "registry": {
                "declared_step": registry_entry["scale"]["declared_step"],
                "axis": registry_entry["axis"],
                "composite": registry_entry["composite"],
            },
            "point_estimate": stats,
            "bootstrap_intervals": bootstrap_summary["evaluators"][name],
        }

    strict_name = sets["included_only"][0] if len(sets["included_only"]) == 1 else None
    anchor = None
    if strict_name is not None:
        anchor = {
            "evaluator": strict_name,
            "suite_mean": statistics_by_evaluator[strict_name]["scores"]["suite_mean"],
            "suite_replay_median": statistics_by_evaluator[strict_name]["scores"]["suite_replay_median"],
            "bootstrap_suite_mean": bootstrap_summary["evaluators"][strict_name]["suite_mean"],
            "bootstrap_replay_median": bootstrap_summary["evaluators"][strict_name]["suite_replay_median"],
        }

    combined_weighting: dict[str, Any] = {}
    for set_name in ("primary", "all"):
        combined_weighting[set_name] = {}
        for scheme in WEIGHTING_SCHEMES:
            bootstrap_intervals = bootstrap_summary["weighting"][set_name][scheme]
            bootstrap_mean_weights = {name: bootstrap_intervals["weights"][name]["mean"] for name in sets[set_name]}
            if any(weight is None for weight in bootstrap_mean_weights.values()):
                stabilized_weights = None
            else:
                stabilized_weights = {name: float(weight) for name, weight in bootstrap_mean_weights.items()}
            combined_weighting[set_name][scheme] = {
                "point_estimate": weighting_results[set_name][scheme],
                "bootstrap_mean_estimate": {
                    "method": "mean of defined hierarchical-bootstrap weight vectors",
                    "weights": stabilized_weights,
                    "composite_suite_mean": compute_composite(
                        statistics_by_evaluator,
                        stabilized_weights,
                        "suite_mean",
                    ),
                    "composite_replay_median": compute_composite(
                        statistics_by_evaluator,
                        stabilized_weights,
                        "suite_replay_median",
                    ),
                },
                "bootstrap_intervals": bootstrap_intervals,
            }

    recommended = combined_weighting["primary"]["inverse_sqrt_step"]
    recommended_weights = recommended["bootstrap_mean_estimate"]["weights"]
    recommended_undefined = recommended["bootstrap_intervals"]["composite_suite_mean"]["undefined_replicates"]
    strict_weight = None
    if strict_name is not None and recommended_weights is not None:
        strict_weight = recommended_weights[strict_name]
    return {
        "analysis_version": 2,
        "dataset_id": table["dataset_id"],
        "scoring_note": "SCORING_NOTE.md",
        "design": {
            "cases": table["dimensions"]["case_count"],
            "runs": table["dimensions"]["run_count"],
            "runs_per_case": table["dimensions"]["run_count"] // table["dimensions"]["case_count"],
            "replays_per_run": table["dimensions"]["replay_count"],
            "evaluators": table["dimensions"]["evaluator_count"],
            "score_rows": table["dimensions"]["row_count"],
        },
        "bootstrap": {
            "replicates": BOOTSTRAP_REPLICATES,
            "seed": BOOTSTRAP_SEED,
            "interval": "percentile 95%",
            "resampling": "case, then run within case, then replay within run; evaluator vectors kept together",
        },
        "evaluator_sets": sets,
        "evaluators": evaluator_results,
        "weighting_results": combined_weighting,
        "provisional_weighting": {
            "evaluator_set": "primary",
            "scheme": "inverse_sqrt_step",
            "estimate": "bootstrap_mean",
            "weights": recommended_weights,
            "composite_suite_mean": recommended["bootstrap_mean_estimate"]["composite_suite_mean"],
            "composite_replay_median": recommended["bootstrap_mean_estimate"]["composite_replay_median"],
        },
        "included_only_anchor": anchor,
        "milestone_decision": {
            "basic_pipeline_sound_enough_to_continue": True,
            "provisional_weighting_selected": True,
            "weighting_rule_ready_to_finalize": False,
            "recommendation": (
                "Carry the bootstrap-mean inverse-sqrt-step weights forward as the provisional "
                "Milestone 1 result, then validate them on additional datasets."
            ),
            "evidence": [
                "All source, registry, estimator, and output validations pass.",
                (
                    "The raw plug-in estimate is boundary-sensitive because two evaluators have no "
                    "detectable corrected case signal in this sample."
                ),
                (
                    "Averaging jointly normalized bootstrap weight vectors preserves uncertainty "
                    "instead of treating boundary estimates as certain zeros."
                ),
                (
                    f"The stabilized senior-review-strict weight is {100 * strict_weight:.1f}%."
                    if strict_weight is not None
                    else "The stabilized weight vector could not be computed."
                ),
                "Bootstrap weight intervals span most or all of the zero-to-one range.",
                (
                    f"{recommended_undefined} of {BOOTSTRAP_REPLICATES} reliability-based bootstrap "
                    "replicates are undefined and excluded from the bootstrap mean."
                ),
            ],
        },
    }


def format_number(value: float | None, digits: int = 4) -> str:
    if value is None:
        return "undefined"
    return f"{value:.{digits}f}"


def format_interval(summary: dict[str, Any], digits: int = 4) -> str:
    lower = summary["lower_2_5"]
    upper = summary["upper_97_5"]
    if lower is None or upper is None:
        return "undefined"
    return f"[{lower:.{digits}f}, {upper:.{digits}f}]"


def markdown_table(headers: list[str], rows: list[list[str]]) -> list[str]:
    lines = [
        "| " + " | ".join(headers) + " |",
        "|" + "|".join("---" for _ in headers) + "|",
    ]
    lines.extend("| " + " | ".join(row) + " |" for row in rows)
    return lines


def render_results_markdown(results: dict[str, Any]) -> str:
    lines = [
        "# Milestone 1 Initial Scoring Results",
        "",
        f"**Dataset:** `{results['dataset_id']}`  ",
        f"**Bootstrap:** {results['bootstrap']['replicates']:,} hierarchical replicates  ",
        "**Status:** Exploratory",
        "",
        "## Evaluator statistics",
        "",
    ]

    evaluator_rows: list[list[str]] = []
    for name, result in results["evaluators"].items():
        point = result["point_estimate"]
        bootstrap = result["bootstrap_intervals"]
        evaluator_rows.append(
            [
                f"`{name}`",
                result["registry"]["composite"]["status"],
                format_number(point["scores"]["suite_mean"]),
                format_interval(bootstrap["suite_mean"]),
                format_number(point["variance_components"]["case"]),
                format_number(point["variance_components"]["agent"]),
                format_number(point["variance_components"]["judge"]),
                format_number(point["reliability"]["single_measurement"]),
                format_number(point["reliability"]["current_design"]),
                f"{100 * point['scores']['fraction_at_scale_maximum']:.1f}%",
                f"{point['counts']['moving_runs']}/{point['counts']['cases'] * point['counts']['runs_per_case']}",
            ]
        )

    lines.extend(
        markdown_table(
            [
                "Evaluator",
                "Status",
                "Mean score",
                "95% CI",
                "Case var",
                "Run var",
                "Judge var",
                "Single r",
                "Design r",
                "At 1.0",
                "Moving runs",
            ],
            evaluator_rows,
        )
    )

    evaluator_points = {name: result["point_estimate"] for name, result in results["evaluators"].items()}
    noisiest_name = max(
        evaluator_points,
        key=lambda name: evaluator_points[name]["variance_components"]["judge"],
    )
    included_names = results["evaluator_sets"]["included_only"]
    anchor_name = included_names[0] if len(included_names) == 1 else None
    zero_case_signal = [
        name
        for name in results["evaluator_sets"]["primary"]
        if evaluator_points[name]["variance_components"]["case"] == 0.0
    ]
    recommended = results["weighting_results"]["primary"]["inverse_sqrt_step"]
    recommended_point_weights = recommended["point_estimate"]["weights"]
    recommended_weights = recommended["bootstrap_mean_estimate"]["weights"]
    recommended_undefined = recommended["bootstrap_intervals"]["composite_suite_mean"]["undefined_replicates"]

    lines.extend(["", "## Key findings", ""])
    lines.append(
        f"- `{noisiest_name}` has the largest judge variance "
        f"({evaluator_points[noisiest_name]['variance_components']['judge']:.4f}); its off-axis "
        "relevance remains a separate validation question."
    )
    if zero_case_signal:
        names = ", ".join(f"`{name}`" for name in zero_case_signal)
        lines.append(f"- {names} have zero corrected case variance in the point estimate.")
    if anchor_name is not None and recommended_point_weights is not None:
        lines.append(
            f"- The raw reliability / sqrt(step) plug-in rule assigns `{anchor_name}` "
            f"{100 * recommended_point_weights[anchor_name]:.1f}% weight, demonstrating boundary sensitivity."
        )
    if anchor_name is not None and recommended_weights is not None:
        lines.append(
            f"- Averaging the defined bootstrap weight vectors gives `{anchor_name}` a stabilized "
            f"provisional weight of {100 * recommended_weights[anchor_name]:.1f}%."
        )
    lines.append(
        f"- {recommended_undefined} of {results['bootstrap']['replicates']:,} reliability-based bootstrap "
        "replicates have no measurable case signal and are omitted from the bootstrap mean."
    )
    lines.append(
        "- The stabilized weights are suitable as a provisional Milestone 1 result, "
        "not as finalized production weights."
    )

    lines.extend(["", "## Raw candidate weights", ""])
    primary_names = results["evaluator_sets"]["primary"]
    primary_rows: list[list[str]] = []
    for name in primary_names:
        row = [f"`{name}`"]
        for scheme in WEIGHTING_SCHEMES:
            weight = results["weighting_results"]["primary"][scheme]["point_estimate"]["weights"]
            row.append(format_number(None if weight is None else weight[name]))
        primary_rows.append(row)
    lines.extend(
        markdown_table(
            [
                "Evaluator",
                "Equal",
                "Reliability",
                "Reliability / step",
                "Reliability / sqrt(step)",
            ],
            primary_rows,
        )
    )

    lines.extend(
        [
            "",
            "## Provisional bootstrap-stabilized weights",
            "",
            "The provisional vector is the componentwise mean of the jointly normalized weight vectors",
            "from bootstrap replicates where the reliability-based weights are defined.",
            "",
        ]
    )
    stabilized_rows = [
        [
            f"`{name}`",
            format_number(None if recommended_point_weights is None else recommended_point_weights[name]),
            format_number(None if recommended_weights is None else recommended_weights[name]),
            format_interval(recommended["bootstrap_intervals"]["weights"][name]),
        ]
        for name in primary_names
    ]
    lines.extend(
        markdown_table(
            ["Evaluator", "Raw point weight", "Provisional weight", "95% bootstrap interval"],
            stabilized_rows,
        )
    )

    lines.extend(["", "## Composite sensitivity", ""])
    composite_rows: list[list[str]] = []
    for scheme in WEIGHTING_SCHEMES:
        result = results["weighting_results"]["primary"][scheme]
        point = result["point_estimate"]
        stabilized = result["bootstrap_mean_estimate"]
        intervals = result["bootstrap_intervals"]
        composite_rows.append(
            [
                scheme,
                format_number(point["composite_suite_mean"]),
                format_number(stabilized["composite_suite_mean"]),
                format_interval(intervals["composite_suite_mean"]),
                format_number(point["composite_replay_median"]),
                str(intervals["composite_suite_mean"]["undefined_replicates"]),
            ]
        )
    lines.extend(
        markdown_table(
            [
                "Weighting",
                "Raw composite",
                "Stabilized composite",
                "95% CI",
                "Raw median-replay composite",
                "Undefined bootstraps",
            ],
            composite_rows,
        )
    )

    lines.extend(
        [
            "",
            "## Interpretation guardrails",
            "",
            "- Reliability measures repeatable case discrimination, not evaluator validity.",
            "- Raw negative variance estimates are retained in `derived/scoring_results.json` before truncation.",
            "- The intervals are exploratory because the outer bootstrap contains only 10 cases.",
            "- All four evaluators remain in the Milestone 1 weighting experiment; semantic relevance is separate.",
            "- Bootstrap averaging stabilizes boundary estimates but is not a substitute for more data.",
            "- Cross-dataset validation is required before selecting a final weighting rule.",
            "",
            "## Milestone decision",
            "",
            "The basic scoring pipeline is sound enough to continue: the hierarchy is explicit, the",
            "variance components are reproducible, uncertainty is retained, and failure cases are visible.",
            "The bootstrap-mean reliability / sqrt(step) vector is the provisional Milestone 1 result.",
            "It is suitable for cross-dataset validation, but not yet for a production merge gate.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    dataset_errors = validate_dataset()
    if dataset_errors:
        raise ValueError(f"frozen dataset validation failed: {dataset_errors}")
    registry_errors = validate_evaluator_registry()
    if registry_errors:
        raise ValueError(f"evaluator registry validation failed: {registry_errors}")

    dataset, evaluator_names, table = load_dataset()
    registry = json.loads(REGISTRY_PATH.read_text())
    sets = evaluator_sets(registry)

    statistics_by_evaluator = compute_all_evaluator_statistics(dataset, evaluator_names)
    weighting_results = compute_weighting_results(statistics_by_evaluator, registry, sets)
    bootstrap_distributions = run_bootstrap(dataset, evaluator_names, registry, sets)
    bootstrap_summary = summarize_bootstrap(bootstrap_distributions, evaluator_names, sets)
    results = build_results(
        table,
        registry,
        statistics_by_evaluator,
        sets,
        weighting_results,
        bootstrap_summary,
    )

    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULTS_PATH.write_text(json.dumps(results, indent=2, ensure_ascii=True) + "\n")
    BOOTSTRAP_PATH.write_text(json.dumps(bootstrap_distributions, separators=(",", ":")) + "\n")
    RESULTS_NOTE_PATH.write_text(render_results_markdown(results) + "\n")
    print(f"Wrote {RESULTS_PATH.relative_to(ROOT)}")
    print(f"Wrote {BOOTSTRAP_PATH.relative_to(ROOT)}")
    print(f"Wrote {RESULTS_NOTE_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
