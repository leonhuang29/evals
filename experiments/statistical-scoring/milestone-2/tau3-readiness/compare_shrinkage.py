"""Compare equal-to-learned weight shrinkage on completed Tau3 observations."""

from __future__ import annotations

import argparse
import json
import math
import random
import statistics
from pathlib import Path
from typing import Any

from compare_configurations import (
    CONFIG_PATH,
    WEIGHTING_METHOD,
    _build_dataset,
    _complete_cases,
    _format_number,
    _held_out_association,
    _load_json,
    _optional_summary,
    _step_sizes,
    _summary,
)

from strands_evals.experimental.calibrator._calibration import (
    _fit_dataset,
    _weighted_score,
)

DEFAULT_LEARNED_FRACTIONS = (0.0, 0.25, 0.5, 0.75, 1.0)


def _blend_weights(
    learned_weights: dict[str, float],
    learned_fraction: float,
) -> dict[str, float]:
    if not learned_weights:
        raise ValueError("learned_weights must contain at least one evaluator")
    if not math.isfinite(learned_fraction) or not 0.0 <= learned_fraction <= 1.0:
        raise ValueError("learned_fraction must be between 0 and 1")

    equal_weight = 1.0 / len(learned_weights)
    return {
        name: (1.0 - learned_fraction) * equal_weight + learned_fraction * weight
        for name, weight in learned_weights.items()
    }


def _validate_learned_fractions(values: list[float]) -> list[float]:
    fractions = sorted(set(values))
    if not fractions:
        raise ValueError("at least one learned fraction is required")
    for value in fractions:
        if not math.isfinite(value) or not 0.0 <= value <= 1.0:
            raise ValueError("learned fractions must be between 0 and 1")
    if fractions[0] != 0.0 or fractions[-1] != 1.0:
        raise ValueError("learned fractions must include 0 and 1")
    return fractions


def compare_shrinkage(
    rows: list[dict[str, Any]],
    config: dict[str, Any],
    *,
    stage: str,
    run_count: int,
    replay_count: int,
    subsamples: int,
    learned_fractions: list[float],
) -> dict[str, Any]:
    if stage not in config["collection"]:
        raise ValueError(f"unknown collection stage: {stage}")
    if subsamples < 1:
        raise ValueError("subsamples must be at least 1")

    fractions = _validate_learned_fractions(learned_fractions)
    step_sizes = _step_sizes(config)
    evaluator_names = tuple(sorted(step_sizes))
    maximum_runs = int(config["collection"][stage]["agent_runs"])
    maximum_replays = int(config["collection"][stage]["judge_replays"])
    if not 2 <= run_count <= maximum_runs:
        raise ValueError(f"run_count must be between 2 and {maximum_runs}")
    if not 2 <= replay_count <= maximum_replays:
        raise ValueError(f"replay_count must be between 2 and {maximum_replays}")

    complete_cases, index, native_rewards = _complete_cases(
        rows,
        evaluator_names=evaluator_names,
        run_count=maximum_runs,
        replay_count=maximum_replays,
    )
    if len(complete_cases) < 2:
        raise ValueError("shrinkage comparison requires at least two complete cases")

    case_counts = sorted(
        {int(value) for value in config["analysis"]["case_counts"] if 2 <= int(value) <= len(complete_cases)}
    )
    if len(complete_cases) not in case_counts:
        case_counts.append(len(complete_cases))

    rng = random.Random(int(config["analysis"]["seed"]) + 90_000)
    comparisons: list[dict[str, Any]] = []
    all_runs = list(range(maximum_runs))
    all_replays = list(range(maximum_replays))
    minimum_delta = float(config["candidate_readiness_thresholds"]["minimum_held_out_correlation_delta"])

    for case_count in case_counts:
        observations = {fraction: [] for fraction in fractions}
        for _ in range(subsamples):
            cases = (
                list(complete_cases)
                if case_count == len(complete_cases)
                else sorted(rng.sample(complete_cases, case_count))
            )
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
                0,
                int(config["analysis"]["seed"]),
            )
            evaluator_scores = dataset.evaluator_scores()

            for fraction in fractions:
                weights = _blend_weights(state.weights, fraction)
                held_out = _held_out_association(
                    index=index,
                    native_rewards=native_rewards,
                    case_names=cases,
                    run_ids=runs,
                    replay_ids=replays,
                    evaluator_names=evaluator_names,
                    learned_weights=weights,
                )
                observations[fraction].append(
                    {
                        "weights": weights,
                        "score": _weighted_score(evaluator_scores, weights),
                        "held_out_correlation": held_out["learned_weight_correlation"],
                        "held_out_delta": held_out["correlation_delta"],
                    }
                )

        fraction_results: list[dict[str, Any]] = []
        for fraction in fractions:
            samples = observations[fraction]
            scores = [float(sample["score"]) for sample in samples]
            deltas = [sample["held_out_delta"] for sample in samples]
            fraction_results.append(
                {
                    "learned_fraction": fraction,
                    "subsamples": len(samples),
                    "mean_weights": {
                        name: statistics.fmean(float(sample["weights"][name]) for sample in samples)
                        for name in evaluator_names
                    },
                    "composite_score": _summary(scores),
                    "composite_score_standard_deviation": statistics.pstdev(scores),
                    "held_out_correlation": _optional_summary([sample["held_out_correlation"] for sample in samples]),
                    "held_out_delta_from_equal": _optional_summary(deltas),
                    "beats_equal_fraction": statistics.fmean(
                        float(delta is not None and delta > 0.0) for delta in deltas
                    ),
                    "within_guardrail_fraction": statistics.fmean(
                        float(delta is not None and delta >= minimum_delta) for delta in deltas
                    ),
                }
            )

        comparisons.append(
            {
                "case_count": case_count,
                "agent_runs": run_count,
                "judge_replays": replay_count,
                "fractions": fraction_results,
            }
        )

    final_fractions = comparisons[-1]["fractions"]
    defined_final = [result for result in final_fractions if result["held_out_correlation"]["mean"] is not None]
    best_held_out = max(
        defined_final,
        key=lambda result: float(result["held_out_correlation"]["mean"]),
    )
    guardrailed = [result for result in final_fractions if result["within_guardrail_fraction"] >= 0.95]
    return {
        "experiment_id": config["experiment_id"],
        "stage": stage,
        "weighting_method": WEIGHTING_METHOD,
        "complete_case_count": len(complete_cases),
        "agent_runs": run_count,
        "judge_replays": replay_count,
        "subsamples_per_case_count": subsamples,
        "learned_fractions": fractions,
        "minimum_held_out_correlation_delta": minimum_delta,
        "comparisons": comparisons,
        "final_design": {
            "case_count": comparisons[-1]["case_count"],
            "best_held_out_learned_fraction": best_held_out["learned_fraction"],
            "largest_guardrailed_learned_fraction": (
                None if not guardrailed else max(float(result["learned_fraction"]) for result in guardrailed)
            ),
        },
    }


def _render_markdown(results: dict[str, Any]) -> str:
    lines = [
        "# Tau3 Equal-to-Learned Shrinkage Comparison",
        "",
        f"**Complete cases:** {results['complete_case_count']}  ",
        f"**Agent runs:** {results['agent_runs']}  ",
        f"**Judge replays:** {results['judge_replays']}  ",
        f"**Subsamples per case count:** {results['subsamples_per_case_count']}  ",
        f"**Learned weighting method:** `{results['weighting_method']}`",
        "",
        "`Learned fraction` is the confidence term in",
        "`applied = (1 - confidence) * equal + confidence * learned`.",
        "",
        "| Cases | Learned fraction | Score SD | Held-out correlation | "
        "Delta from equal | Beats equal | Within guardrail |",
        "|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for comparison in results["comparisons"]:
        for fraction in comparison["fractions"]:
            lines.append(
                f"| {comparison['case_count']} | "
                f"{fraction['learned_fraction']:.2f} | "
                f"{fraction['composite_score_standard_deviation']:.4f} | "
                f"{_format_number(fraction['held_out_correlation']['mean'])} | "
                f"{_format_number(fraction['held_out_delta_from_equal']['mean'])} | "
                f"{100 * fraction['beats_equal_fraction']:.1f}% | "
                f"{100 * fraction['within_guardrail_fraction']:.1f}% |"
            )

    final = results["final_design"]
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "For the complete design, the learned fraction with the strongest "
            "mean held-out correlation was "
            f"`{final['best_held_out_learned_fraction']:.2f}`. The largest "
            "learned fraction remaining within the provisional held-out "
            "guardrail for at least 95% of subsamples was "
            f"`{final['largest_guardrailed_learned_fraction']}`.",
            "",
            "These values characterize the Tau3 experiment only. Held-out reward "
            "is used to compare the tradeoff, so the selected fraction must not "
            "be shipped as a universal default.",
        ]
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
        default="main",
    )
    parser.add_argument("--agent-runs", type=int, default=3)
    parser.add_argument("--judge-replays", type=int, default=2)
    parser.add_argument(
        "--subsamples",
        type=int,
        default=int(config["analysis"]["subsamples_per_design"]),
    )
    parser.add_argument(
        "--learned-fractions",
        type=float,
        nargs="+",
        default=list(DEFAULT_LEARNED_FRACTIONS),
    )
    return parser.parse_args()


if __name__ == "__main__":
    arguments = parse_args()
    input_path = arguments.input.expanduser().resolve()
    output_dir = arguments.output_dir.expanduser().resolve()
    configuration = _load_json(CONFIG_PATH)
    comparison = compare_shrinkage(
        _load_json(input_path),
        configuration,
        stage=arguments.stage,
        run_count=arguments.agent_runs,
        replay_count=arguments.judge_replays,
        subsamples=arguments.subsamples,
        learned_fractions=arguments.learned_fractions,
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "shrinkage_comparison.json"
    markdown_path = output_dir / "SHRINKAGE_COMPARISON.md"
    json_path.write_text(json.dumps(comparison, indent=2) + "\n", encoding="utf-8")
    markdown_path.write_text(_render_markdown(comparison), encoding="utf-8")
    print(f"wrote {json_path}")  # noqa: T201
    print(f"wrote {markdown_path}")  # noqa: T201
