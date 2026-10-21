"""Validate Milestone 1 scoring result and bootstrap artifacts."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from scoring_analysis import BOOTSTRAP_REPLICATES, WEIGHTING_SCHEMES

ROOT = Path(__file__).resolve().parent
RESULTS_PATH = ROOT / "derived" / "scoring_results.json"
BOOTSTRAP_PATH = ROOT / "derived" / "bootstrap_distributions.json"
REGISTRY_PATH = ROOT / "evaluator_registry.json"
TOLERANCE = 1e-9


def is_finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def validate_weight_vector(weights: dict[str, float] | None, label: str, errors: list[str]) -> None:
    if weights is None:
        return
    if not all(is_finite_number(value) and value >= 0.0 for value in weights.values()):
        errors.append(f"{label} contains an invalid weight")
        return
    if abs(sum(weights.values()) - 1.0) > TOLERANCE:
        errors.append(f"{label} does not sum to one")


def validate_interval(summary: dict[str, Any], label: str, errors: list[str]) -> None:
    defined = summary["defined_replicates"]
    undefined = summary["undefined_replicates"]
    if defined + undefined != BOOTSTRAP_REPLICATES:
        errors.append(f"{label} replicate counts do not sum to {BOOTSTRAP_REPLICATES}")
    mean_value = summary["mean"]
    values = [summary["lower_2_5"], summary["median"], summary["upper_97_5"]]
    if defined == 0:
        if mean_value is not None or any(value is not None for value in values):
            errors.append(f"{label} has summary values despite having no defined replicates")
    elif not is_finite_number(mean_value):
        errors.append(f"{label} has a non-finite mean")
    elif not all(is_finite_number(value) for value in values):
        errors.append(f"{label} has a non-finite quantile")
    elif not values[0] <= values[1] <= values[2]:
        errors.append(f"{label} quantiles are not ordered")


def validate() -> list[str]:
    errors: list[str] = []
    results = json.loads(RESULTS_PATH.read_text())
    distributions = json.loads(BOOTSTRAP_PATH.read_text())
    registry = json.loads(REGISTRY_PATH.read_text())

    evaluator_names = set(registry["evaluators"])
    if set(results["evaluators"]) != evaluator_names:
        errors.append("result evaluator names do not match the registry")
    if set(distributions["evaluators"]) != evaluator_names:
        errors.append("bootstrap evaluator names do not match the registry")
    if distributions["metadata"]["replicates"] != BOOTSTRAP_REPLICATES:
        errors.append("bootstrap metadata has the wrong replicate count")

    for name, evaluator_result in results["evaluators"].items():
        point = evaluator_result["point_estimate"]
        for section in ("scores", "variance_components", "reliability"):
            for metric, value in point[section].items():
                if isinstance(value, list):
                    continue
                if not is_finite_number(value):
                    errors.append(f"{name}.{section}.{metric} is not finite")
        for metric, summary in evaluator_result["bootstrap_intervals"].items():
            validate_interval(summary, f"{name}.{metric}", errors)

        for metric, values in distributions["evaluators"][name].items():
            if len(values) != BOOTSTRAP_REPLICATES:
                errors.append(f"{name}.{metric} has {len(values)} bootstrap values")
            if not all(is_finite_number(value) for value in values):
                errors.append(f"{name}.{metric} contains a non-finite bootstrap value")

    for set_name in ("primary", "all"):
        evaluator_set = results["evaluator_sets"][set_name]
        for scheme in WEIGHTING_SCHEMES:
            result = results["weighting_results"][set_name][scheme]
            validate_weight_vector(
                result["point_estimate"]["weights"],
                f"{set_name}.{scheme}.point_weights",
                errors,
            )
            validate_weight_vector(
                result["bootstrap_mean_estimate"]["weights"],
                f"{set_name}.{scheme}.bootstrap_mean_weights",
                errors,
            )
            for metric in ("composite_suite_mean", "composite_replay_median"):
                value = result["bootstrap_mean_estimate"][metric]
                if value is not None and not is_finite_number(value):
                    errors.append(f"{set_name}.{scheme}.bootstrap_mean_estimate.{metric} is not finite")
            intervals = result["bootstrap_intervals"]
            validate_interval(
                intervals["composite_suite_mean"],
                f"{set_name}.{scheme}.composite_suite_mean",
                errors,
            )
            validate_interval(
                intervals["composite_replay_median"],
                f"{set_name}.{scheme}.composite_replay_median",
                errors,
            )
            for name in evaluator_set:
                validate_interval(
                    intervals["weights"][name],
                    f"{set_name}.{scheme}.weights.{name}",
                    errors,
                )
                defined_weights = [
                    value
                    for value in distributions["weighting"][set_name][scheme]["weights"][name]
                    if value is not None
                ]
                expected_mean = sum(defined_weights) / len(defined_weights) if defined_weights else None
                reported_mean = intervals["weights"][name]["mean"]
                if expected_mean is None:
                    if reported_mean is not None:
                        errors.append(f"{set_name}.{scheme}.weights.{name} has an unexpected mean")
                elif reported_mean is None or abs(reported_mean - expected_mean) > TOLERANCE:
                    errors.append(f"{set_name}.{scheme}.weights.{name} mean does not match distribution")

            distribution = distributions["weighting"][set_name][scheme]
            for metric in ("composite_suite_mean", "composite_replay_median"):
                if len(distribution[metric]) != BOOTSTRAP_REPLICATES:
                    errors.append(f"{set_name}.{scheme}.{metric} has the wrong length")

            for replicate in range(BOOTSTRAP_REPLICATES):
                values = {name: distribution["weights"][name][replicate] for name in evaluator_set}
                defined_values = [value for value in values.values() if value is not None]
                if not defined_values:
                    continue
                if len(defined_values) != len(values):
                    errors.append(f"{set_name}.{scheme} replicate {replicate} has partial weights")
                    break
                validate_weight_vector(
                    values,
                    f"{set_name}.{scheme}.bootstrap_weights[{replicate}]",
                    errors,
                )

    decision = results["milestone_decision"]
    if not decision["basic_pipeline_sound_enough_to_continue"]:
        errors.append("milestone decision unexpectedly rejects the basic pipeline")
    if decision["weighting_rule_ready_to_finalize"]:
        errors.append("milestone decision incorrectly finalizes the weighting rule")
    validate_weight_vector(
        results["provisional_weighting"]["weights"],
        "provisional_weighting.weights",
        errors,
    )

    return errors


def main() -> None:
    errors = validate()
    if errors:
        print("Scoring result validation failed:")
        for error in errors:
            print(f"- {error}")
        raise SystemExit(1)
    print(
        "Scoring result validation passed: "
        f"{BOOTSTRAP_REPLICATES} replicates, "
        "all point weights normalized, all interval counts complete."
    )


if __name__ == "__main__":
    main()
