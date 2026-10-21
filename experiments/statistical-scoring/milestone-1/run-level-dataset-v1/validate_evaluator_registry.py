"""Validate evaluator registry metadata against the tidy evaluation table."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
REGISTRY_PATH = ROOT / "evaluator_registry.json"
TABLE_PATH = ROOT / "derived" / "tidy_evaluations.json"
MANIFEST_PATH = ROOT / "dataset_manifest.json"
VALID_COMPOSITE_STATUSES = {"included", "provisional", "excluded"}
REQUIRED_EVALUATOR_FIELDS = {"implementation", "evaluation", "axis", "scale", "composite", "notes"}


def close_to_allowed_score(score: float, allowed_scores: list[float]) -> bool:
    return any(abs(score - allowed) < 1e-12 for allowed in allowed_scores)


def strict_reported_scores(scale: dict[str, Any]) -> set[float]:
    denominator = scale["raw_total_maximum"]
    decimals = scale["reported_rounding_decimals"]
    return {round(total / denominator, decimals) for total in range(denominator + 1)}


def validate() -> list[str]:
    errors: list[str] = []
    registry = json.loads(REGISTRY_PATH.read_text())
    table = json.loads(TABLE_PATH.read_text())
    manifest = json.loads(MANIFEST_PATH.read_text())
    evaluators = registry["evaluators"]
    rows = table["rows"]

    table_evaluator_names = {row["evaluator_name"] for row in rows}
    registry_evaluator_names = set(evaluators)
    manifest_evaluator_names = set(manifest["evaluators"])
    if registry_evaluator_names != table_evaluator_names:
        errors.append("registry evaluator names do not match the tidy table")
    if registry_evaluator_names != manifest_evaluator_names:
        errors.append("registry evaluator names do not match the dataset manifest")
    if registry["dataset_id"] != table["dataset_id"]:
        errors.append("registry dataset_id does not match the tidy table")

    scores_by_evaluator: dict[str, list[float]] = {name: [] for name in evaluators}
    for row in rows:
        scores_by_evaluator.setdefault(row["evaluator_name"], []).append(float(row["score"]))

    for name, metadata in evaluators.items():
        missing_fields = REQUIRED_EVALUATOR_FIELDS - metadata.keys()
        if missing_fields:
            errors.append(f"{name} is missing fields: {sorted(missing_fields)}")
            continue

        evaluation = metadata["evaluation"]
        scale = metadata["scale"]
        composite = metadata["composite"]

        if evaluation["analysis_unit"] != "run":
            errors.append(f"{name} must use run as its analysis unit")
        if evaluation["scores_per_unit"] != 1:
            errors.append(f"{name} must emit one score per run")
        if scale["minimum"] != 0.0 or scale["maximum"] != 1.0:
            errors.append(f"{name} must use the normalized 0 to 1 scale")
        if not scale["higher_is_better"]:
            errors.append(f"{name} must declare higher_is_better")
        if scale["declared_step"]["value"] <= 0:
            errors.append(f"{name} has a non-positive declared step")
        if composite["status"] not in VALID_COMPOSITE_STATUSES:
            errors.append(f"{name} has an invalid composite status")

        observed_scores = scores_by_evaluator.get(name, [])
        allowed_scores = scale["allowed_scores"]
        if allowed_scores is not None:
            for score in observed_scores:
                if not close_to_allowed_score(score, allowed_scores):
                    errors.append(f"{name} observed score {score} is outside its declared categorical scale")
        elif name == "senior-review-strict":
            reported_scores = strict_reported_scores(scale)
            for score in observed_scores:
                if not close_to_allowed_score(score, list(reported_scores)):
                    errors.append(f"{name} observed score {score} is inconsistent with its rounded 1/24 scale")

    strict_registry_hash = evaluators["senior-review-strict"]["implementation"]["rubric_sha256"]
    strict_manifest_hash = manifest["rubrics"]["senior-review-strict"]["sha256"]
    if strict_registry_hash != strict_manifest_hash:
        errors.append("senior-review-strict rubric hash does not match the dataset manifest")

    return errors


def main() -> None:
    errors = validate()
    if errors:
        print("Evaluator registry validation failed:")
        for error in errors:
            print(f"- {error}")
        raise SystemExit(1)

    registry = json.loads(REGISTRY_PATH.read_text())
    statuses: dict[str, int] = {status: 0 for status in VALID_COMPOSITE_STATUSES}
    for evaluator in registry["evaluators"].values():
        statuses[evaluator["composite"]["status"]] += 1
    print(
        "Evaluator registry validation passed: "
        f"{len(registry['evaluators'])} evaluators "
        f"({statuses['included']} included, "
        f"{statuses['provisional']} provisional, "
        f"{statuses['excluded']} excluded)."
    )


if __name__ == "__main__":
    main()
