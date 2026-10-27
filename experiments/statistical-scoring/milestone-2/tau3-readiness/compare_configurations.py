"""Compare calibration designs using the completed Tau3 observations."""

from __future__ import annotations

import argparse
import itertools
import json
import math
import random
import statistics
import time
from pathlib import Path
from typing import Any

from strands_evals.experimental.calibrator._calibration import (
    _CalibrationDataset,
    _fit_dataset,
    _weighted_score,
)

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "experiment_config.json"
WEIGHTING_METHOD = "inverse_sqrt_step"


def _load_json(path: Path) -> Any:
    last_error: json.JSONDecodeError | None = None
    for _ in range(5):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            last_error = error
            time.sleep(0.1)
    raise ValueError(f"could not read a complete JSON snapshot from {path}") from last_error


def _mean(values: list[float]) -> float:
    return statistics.fmean(values)


def _percentile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] + fraction * (ordered[upper] - ordered[lower])


def _summary(values: list[float]) -> dict[str, float]:
    return {
        "mean": _mean(values),
        "lower_2_5": _percentile(values, 0.025),
        "median": _percentile(values, 0.5),
        "upper_97_5": _percentile(values, 0.975),
    }


def _optional_summary(values: list[float | None]) -> dict[str, float | int | None]:
    defined = [value for value in values if value is not None]
    if not defined:
        return {
            "defined": 0,
            "defined_fraction": 0.0,
            "mean": None,
            "lower_2_5": None,
            "median": None,
            "upper_97_5": None,
        }
    return {
        "defined": len(defined),
        "defined_fraction": len(defined) / len(values),
        **_summary(defined),
    }


def _step_sizes(config: dict[str, Any]) -> dict[str, float]:
    return {str(evaluator["name"]): float(evaluator["declared_step_size"]) for evaluator in config["evaluators"]}


def _complete_cases(
    rows: list[dict[str, Any]],
    *,
    evaluator_names: tuple[str, ...],
    run_count: int,
    replay_count: int,
) -> tuple[
    list[str],
    dict[tuple[str, int, int, str], float],
    dict[tuple[str, int], float],
]:
    index: dict[tuple[str, int, int, str], float] = {}
    native_rewards: dict[tuple[str, int], float] = {}
    for row in rows:
        case_name = str(row["case"])
        agent_run = int(row["agent_run"])
        key = (
            case_name,
            agent_run,
            int(row["judge_replay"]),
            str(row["evaluator"]),
        )
        if key in index:
            raise ValueError(f"duplicate observation: {key}")
        index[key] = float(row["score"])
        reward_key = (case_name, agent_run)
        reward = float(row["native_reward"])
        if reward_key in native_rewards and native_rewards[reward_key] != reward:
            raise ValueError(f"inconsistent native reward for case-run: {reward_key}")
        native_rewards[reward_key] = reward

    cases = sorted({key[0] for key in index})
    complete: list[str] = []
    for case_name in cases:
        expected = {
            (case_name, agent_run, replay, evaluator)
            for agent_run in range(run_count)
            for replay in range(replay_count)
            for evaluator in evaluator_names
        }
        observed = {key for key in index if key[0] == case_name}
        if observed == expected:
            complete.append(case_name)
    return complete, index, native_rewards


def _build_dataset(
    index: dict[tuple[str, int, int, str], float],
    *,
    case_names: list[str],
    run_ids: list[int],
    replay_ids: list[int],
    evaluator_names: tuple[str, ...],
) -> _CalibrationDataset:
    parsed: list[list[dict[str, dict[str, float]]]] = []
    for run_id in run_ids:
        run_reports: list[dict[str, dict[str, float]]] = []
        for replay_id in replay_ids:
            report_scores: dict[str, dict[str, float]] = {}
            for evaluator_name in evaluator_names:
                report_scores[evaluator_name] = {
                    case_name: index[(case_name, run_id, replay_id, evaluator_name)] for case_name in case_names
                }
            run_reports.append(report_scores)
        parsed.append(run_reports)

    return _CalibrationDataset(
        parsed=parsed,
        evaluator_names=evaluator_names,
        case_names=tuple(case_names),
        case_signatures=tuple((case_name, case_name) for case_name in case_names),
        run_count=len(run_ids),
        replay_count=len(replay_ids),
        calibration_context=None,
    )


def _interval_width(summary: dict[str, float | int | None]) -> float | None:
    lower = summary["lower_2_5"]
    upper = summary["upper_97_5"]
    if lower is None or upper is None:
        return None
    return float(upper) - float(lower)


def _correlation(first: list[float], second: list[float]) -> float | None:
    if len(first) != len(second) or len(first) < 2:
        return None
    first_mean = _mean(first)
    second_mean = _mean(second)
    first_deviations = [value - first_mean for value in first]
    second_deviations = [value - second_mean for value in second]
    denominator = math.sqrt(sum(value**2 for value in first_deviations) * sum(value**2 for value in second_deviations))
    if denominator == 0:
        return None
    return (
        sum(
            first_value * second_value
            for first_value, second_value in zip(
                first_deviations,
                second_deviations,
                strict=True,
            )
        )
        / denominator
    )


def _held_out_association(
    *,
    index: dict[tuple[str, int, int, str], float],
    native_rewards: dict[tuple[str, int], float],
    case_names: list[str],
    run_ids: list[int],
    replay_ids: list[int],
    evaluator_names: tuple[str, ...],
    learned_weights: dict[str, float],
) -> dict[str, float | int | None]:
    equal_weight = 1.0 / len(evaluator_names)
    rewards: list[float] = []
    equal_scores: list[float] = []
    learned_scores: list[float] = []
    for case_name in case_names:
        for run_id in run_ids:
            evaluator_scores = {
                evaluator_name: _mean(
                    [index[(case_name, run_id, replay_id, evaluator_name)] for replay_id in replay_ids]
                )
                for evaluator_name in evaluator_names
            }
            rewards.append(native_rewards[(case_name, run_id)])
            equal_scores.append(sum(equal_weight * score for score in evaluator_scores.values()))
            learned_scores.append(
                sum(learned_weights[evaluator_name] * score for evaluator_name, score in evaluator_scores.items())
            )

    equal_correlation = _correlation(equal_scores, rewards)
    learned_correlation = _correlation(learned_scores, rewards)
    return {
        "run_count": len(rewards),
        "native_reward_mean": _mean(rewards),
        "equal_weight_correlation": equal_correlation,
        "learned_weight_correlation": learned_correlation,
        "correlation_delta": (
            None
            if equal_correlation is None or learned_correlation is None
            else learned_correlation - equal_correlation
        ),
    }


def _sample_design(
    *,
    index: dict[tuple[str, int, int, str], float],
    native_rewards: dict[tuple[str, int], float],
    all_cases: list[str],
    all_runs: list[int],
    all_replays: list[int],
    evaluator_names: tuple[str, ...],
    step_sizes: dict[str, float],
    case_count: int,
    run_count: int,
    replay_count: int,
    samples: int,
    bootstrap_replicates: int,
    seed: int,
    reference_weights: dict[str, float],
    reference_score: float,
    thresholds: dict[str, float],
) -> dict[str, Any]:
    rng = random.Random(seed)
    observations: list[dict[str, Any]] = []
    for sample_index in range(samples):
        cases = sorted(rng.sample(all_cases, case_count))
        runs = sorted(rng.sample(all_runs, run_count))
        replays = sorted(rng.sample(all_replays, replay_count))
        dataset = _build_dataset(
            index,
            case_names=cases,
            run_ids=runs,
            replay_ids=replays,
            evaluator_names=evaluator_names,
        )
        state = _fit_dataset(
            dataset,
            step_sizes,
            WEIGHTING_METHOD,
            bootstrap_replicates,
            seed + sample_index + 1,
        )
        score = _weighted_score(dataset.evaluator_scores(), state.weights)
        held_out = _held_out_association(
            index=index,
            native_rewards=native_rewards,
            case_names=cases,
            run_ids=runs,
            replay_ids=replays,
            evaluator_names=evaluator_names,
            learned_weights=state.weights,
        )
        bootstrap = state.bootstrap_result
        if bootstrap is None:
            raise RuntimeError("configuration comparison requires bootstrap output")

        weight_summaries = bootstrap.candidate_weight_intervals[WEIGHTING_METHOD]
        defined_fraction = min(
            float(summary["defined_replicates"]) / bootstrap_replicates for summary in weight_summaries.values()
        )
        weight_widths = [
            width for summary in weight_summaries.values() if (width := _interval_width(summary)) is not None
        ]
        maximum_weight_width = max(weight_widths) if weight_widths else 1.0
        composite_width = _interval_width(bootstrap.composite_score_intervals[WEIGHTING_METHOD])
        observations.append(
            {
                "status": state.status,
                "weights": state.weights,
                "score": score,
                "defined_fraction": defined_fraction,
                "maximum_weight_interval_width": maximum_weight_width,
                "composite_interval_width": (1.0 if composite_width is None else composite_width),
                "maximum_absolute_weight_drift": max(
                    abs(state.weights[name] - reference_weights[name]) for name in evaluator_names
                ),
                "composite_score_drift": abs(score - reference_score),
                "held_out": held_out,
            }
        )

    defined_fractions = [item["defined_fraction"] for item in observations]
    weight_widths = [item["maximum_weight_interval_width"] for item in observations]
    composite_widths = [item["composite_interval_width"] for item in observations]
    weight_drifts = [item["maximum_absolute_weight_drift"] for item in observations]
    score_drifts = [item["composite_score_drift"] for item in observations]
    held_out_deltas = [item["held_out"]["correlation_delta"] for item in observations]
    readiness_fraction = _mean(
        [
            float(
                item["defined_fraction"] >= thresholds["minimum_defined_bootstrap_fraction"]
                and item["maximum_weight_interval_width"] <= thresholds["maximum_weight_interval_width"]
                and item["composite_interval_width"] <= thresholds["maximum_composite_interval_width"]
                and item["held_out"]["correlation_delta"] is not None
                and item["held_out"]["correlation_delta"] >= thresholds["minimum_held_out_correlation_delta"]
            )
            for item in observations
        ]
    )
    return {
        "case_count": case_count,
        "agent_runs": run_count,
        "judge_replays": replay_count,
        "subsamples": samples,
        "calibrated_fraction": _mean([float(item["status"] == "calibrated") for item in observations]),
        "readiness_fraction": readiness_fraction,
        "defined_bootstrap_fraction": _summary(defined_fractions),
        "maximum_weight_interval_width": _summary(weight_widths),
        "composite_interval_width": _summary(composite_widths),
        "maximum_absolute_weight_drift": _summary(weight_drifts),
        "composite_score_drift": _summary(score_drifts),
        "held_out_equal_weight_correlation": _optional_summary(
            [item["held_out"]["equal_weight_correlation"] for item in observations]
        ),
        "held_out_learned_weight_correlation": _optional_summary(
            [item["held_out"]["learned_weight_correlation"] for item in observations]
        ),
        "held_out_correlation_delta": _optional_summary(held_out_deltas),
        "mean_weights": {name: _mean([item["weights"][name] for item in observations]) for name in evaluator_names},
    }


def compare(
    rows: list[dict[str, Any]],
    config: dict[str, Any],
    *,
    stage: str,
    bootstrap_replicates: int,
    subsamples: int,
) -> dict[str, Any]:
    if stage not in config["collection"]:
        raise ValueError(f"unknown collection stage: {stage}")
    step_sizes = _step_sizes(config)
    evaluator_names = tuple(sorted(step_sizes))
    maximum_runs = int(config["collection"][stage]["agent_runs"])
    maximum_replays = int(config["collection"][stage]["judge_replays"])
    complete_cases, index, native_rewards = _complete_cases(
        rows,
        evaluator_names=evaluator_names,
        run_count=maximum_runs,
        replay_count=maximum_replays,
    )
    if len(complete_cases) < 2:
        raise ValueError("configuration comparison requires at least two complete cases")

    reference_dataset = _build_dataset(
        index,
        case_names=complete_cases,
        run_ids=list(range(maximum_runs)),
        replay_ids=list(range(maximum_replays)),
        evaluator_names=evaluator_names,
    )
    reference_state = _fit_dataset(
        reference_dataset,
        step_sizes,
        WEIGHTING_METHOD,
        0,
        int(config["analysis"]["seed"]),
    )
    reference_score = _weighted_score(
        reference_dataset.evaluator_scores(),
        reference_state.weights,
    )
    reference_held_out = _held_out_association(
        index=index,
        native_rewards=native_rewards,
        case_names=complete_cases,
        run_ids=list(range(maximum_runs)),
        replay_ids=list(range(maximum_replays)),
        evaluator_names=evaluator_names,
        learned_weights=reference_state.weights,
    )

    configured_case_counts = [
        int(value) for value in config["analysis"]["case_counts"] if int(value) <= len(complete_cases)
    ]
    case_counts = sorted(set(configured_case_counts or [len(complete_cases)]))
    if len(complete_cases) not in case_counts:
        case_counts.append(len(complete_cases))
    run_counts = [int(value) for value in config["analysis"]["agent_run_counts"] if int(value) <= maximum_runs]
    replay_counts = [int(value) for value in config["analysis"]["judge_replay_counts"] if int(value) <= maximum_replays]
    thresholds = {name: float(value) for name, value in config["candidate_readiness_thresholds"].items()}

    comparisons: list[dict[str, Any]] = []
    base_seed = int(config["analysis"]["seed"])
    designs = itertools.product(case_counts, run_counts, replay_counts)
    for design_index, (case_count, run_count, replay_count) in enumerate(designs):
        sample_count = (
            1
            if (case_count == len(complete_cases) and run_count == maximum_runs and replay_count == maximum_replays)
            else subsamples
        )
        comparisons.append(
            _sample_design(
                index=index,
                native_rewards=native_rewards,
                all_cases=complete_cases,
                all_runs=list(range(maximum_runs)),
                all_replays=list(range(maximum_replays)),
                evaluator_names=evaluator_names,
                step_sizes=step_sizes,
                case_count=case_count,
                run_count=run_count,
                replay_count=replay_count,
                samples=sample_count,
                bootstrap_replicates=bootstrap_replicates,
                seed=base_seed + 10_000 * design_index,
                reference_weights=reference_state.weights,
                reference_score=reference_score,
                thresholds=thresholds,
            )
        )

    ready = [
        result
        for result in comparisons
        if result["readiness_fraction"] >= thresholds["minimum_defined_bootstrap_fraction"]
    ]
    return {
        "experiment_id": config["experiment_id"],
        "stage": stage,
        "status": ("planned_grid_available" if configured_case_counts else "partial_collection_diagnostic"),
        "complete_case_count": len(complete_cases),
        "complete_cases": complete_cases,
        "available_design": {
            "agent_runs": maximum_runs,
            "judge_replays": maximum_replays,
        },
        "weighting_method": WEIGHTING_METHOD,
        "bootstrap_replicates": bootstrap_replicates,
        "requested_subsamples": subsamples,
        "thresholds": thresholds,
        "reference": {
            "case_count": len(complete_cases),
            "agent_runs": maximum_runs,
            "judge_replays": maximum_replays,
            "weights": reference_state.weights,
            "score": reference_score,
            "reliabilities": reference_state.reliabilities,
            "variance_components": reference_state.variance_components,
            "held_out": reference_held_out,
        },
        "comparisons": comparisons,
        "provisional_smallest_ready_design": (
            None
            if not ready
            else min(
                ready,
                key=lambda item: (
                    item["case_count"],
                    item["agent_runs"],
                    item["judge_replays"],
                ),
            )
        ),
    }


def _format_number(value: float | None) -> str:
    return "undefined" if value is None or not math.isfinite(value) else f"{value:.4f}"


def _render_markdown(results: dict[str, Any]) -> str:
    lines = [
        "# Tau3 Calibration Configuration Comparison",
        "",
        f"**Complete cases:** {results['complete_case_count']}  ",
        f"**Collection stage:** `{results['stage']}`  ",
        f"**Status:** `{results['status']}`  ",
        f"**Weighting method:** `{results['weighting_method']}`",
        "",
        "| Cases | Runs | Replays | Ready fits | Defined bootstrap | "
        "Max weight CI width | Composite CI width | Max weight drift | Score drift | "
        "Held-out delta |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for result in results["comparisons"]:
        lines.append(
            f"| {result['case_count']} | {result['agent_runs']} | "
            f"{result['judge_replays']} | "
            f"{100 * result['readiness_fraction']:.1f}% | "
            f"{100 * result['defined_bootstrap_fraction']['mean']:.1f}% | "
            f"{_format_number(result['maximum_weight_interval_width']['mean'])} | "
            f"{_format_number(result['composite_interval_width']['mean'])} | "
            f"{_format_number(result['maximum_absolute_weight_drift']['mean'])} | "
            f"{_format_number(result['composite_score_drift']['mean'])} |"
            f" {_format_number(result['held_out_correlation_delta']['mean'])} |"
        )

    lines.extend(["", "## Interpretation", ""])
    if results["status"] == "partial_collection_diagnostic":
        lines.append(
            "The planned case-count grid is not available yet. These rows only "
            "compare replay counts on the cases collected so far and must not be "
            "treated as a minimum-size recommendation."
        )
    elif results["provisional_smallest_ready_design"] is None:
        lines.append("No observed configuration satisfies the candidate readiness thresholds.")
    else:
        design = results["provisional_smallest_ready_design"]
        lines.append(
            "The smallest observed design satisfying the candidate thresholds is "
            f"{design['case_count']} cases, {design['agent_runs']} runs, and "
            f"{design['judge_replays']} replays. This remains experiment-specific."
        )
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    config = _load_json(CONFIG_PATH)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--stage",
        choices=tuple(config["collection"]),
        default="smoke",
    )
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
    return parser.parse_args()


if __name__ == "__main__":
    arguments = parse_args()
    if arguments.bootstrap_replicates < 2:
        raise ValueError("--bootstrap-replicates must be at least 2")
    if arguments.subsamples < 1:
        raise ValueError("--subsamples must be at least 1")
    input_path = arguments.input.expanduser().resolve()
    output_dir = arguments.output_dir.expanduser().resolve()
    configuration = _load_json(CONFIG_PATH)
    comparison = compare(
        _load_json(input_path),
        configuration,
        stage=arguments.stage,
        bootstrap_replicates=arguments.bootstrap_replicates,
        subsamples=arguments.subsamples,
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "configuration_comparison.json"
    markdown_path = output_dir / "CONFIGURATION_COMPARISON.md"
    json_path.write_text(json.dumps(comparison, indent=2) + "\n", encoding="utf-8")
    markdown_path.write_text(_render_markdown(comparison), encoding="utf-8")
    print(f"wrote {json_path}")  # noqa: T201
    print(f"wrote {markdown_path}")  # noqa: T201
