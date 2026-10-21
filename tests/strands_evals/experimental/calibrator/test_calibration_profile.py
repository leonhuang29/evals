import json

import pytest
from pydantic import ValidationError

from strands_evals import Case
from strands_evals.evaluators import ConcisenessEvaluator
from strands_evals.experimental import (
    CalibrationProfile,
    Calibrator,
    ProfileCompatibility,
)
from strands_evals.experimental.calibrator._calibration import _build_calibration_context


def _context(dataset: str = "dataset-a") -> dict:
    return {
        "version": "1",
        "dataset": dataset,
        "evaluators": "evaluators-a",
        "step_sizes": "steps-a",
        "overall": "overall-a",
    }


def _bootstrap_summary(mean: float) -> dict[str, float | int | None]:
    return {
        "mean": mean,
        "lower_2_5": max(0.0, mean - 0.1),
        "median": mean,
        "upper_97_5": min(1.0, mean + 0.1),
        "defined_replicates": 100,
        "undefined_replicates": 0,
    }


def _profile(
    *,
    algorithm_version: int = 1,
    calibration_context: dict | None = None,
    report_structure_fingerprint: str | None = None,
) -> CalibrationProfile:
    context = _context() if calibration_context is None else calibration_context
    return CalibrationProfile.create(
        algorithm_version=algorithm_version,
        weighting_method="inverse_sqrt_step",
        weights={"stable": 0.8, "noisy": 0.2},
        step_sizes={"stable": 0.25, "noisy": 0.5},
        variance_components={
            "stable": {"case": 0.4, "agent": 0.01, "judge": 0.02},
            "noisy": {"case": 0.1, "agent": 0.03, "judge": 0.2},
        },
        reliabilities={"stable": 0.9, "noisy": 0.3},
        bootstrap={
            "replicates": 100,
            "seed": 42,
            "reliability_intervals": {
                "stable": _bootstrap_summary(0.9),
                "noisy": _bootstrap_summary(0.3),
            },
            "candidate_weight_intervals": {
                "inverse_sqrt_step": {
                    "stable": _bootstrap_summary(0.8),
                    "noisy": _bootstrap_summary(0.2),
                }
            },
            "composite_score_intervals": {
                "inverse_sqrt_step": _bootstrap_summary(0.6),
            },
        },
        case_count=4,
        agent_runs=2,
        judge_replays=3,
        calibration_context=context,
        report_structure_fingerprint=report_structure_fingerprint,
    )


def test_profile_is_deterministic_and_round_trips_through_json(tmp_path) -> None:
    profile = _profile()
    assert profile == _profile()
    path = tmp_path / "profiles" / "support-agent"

    profile.to_file(str(path))
    loaded = CalibrationProfile.from_file(str(path.with_suffix(".json")))

    assert loaded == profile
    serialized = json.loads(path.with_suffix(".json").read_text())
    assert serialized["profile_id"] == profile.profile_id
    assert serialized["schema_version"] == 1
    assert serialized["bootstrap"]["replicates"] == 100


def test_profile_rejects_content_that_does_not_match_id() -> None:
    data = _profile().to_dict()
    data["case_count"] = 5

    with pytest.raises(ValidationError, match="profile ID does not match"):
        CalibrationProfile.from_dict(data)


@pytest.mark.parametrize("reliability", [-0.1, 1.1])
def test_profile_rejects_out_of_range_reliability(reliability: float) -> None:
    data = _profile().to_dict()
    data.pop("profile_id")
    data["reliabilities"]["stable"] = reliability

    with pytest.raises(ValidationError, match="reliabilities must be finite and between 0 and 1"):
        CalibrationProfile.create(**data)


def test_profile_rejects_missing_variance_component() -> None:
    data = _profile().to_dict()
    data.pop("profile_id")
    del data["variance_components"]["stable"]["judge"]

    with pytest.raises(ValidationError, match="variance components for 'stable' must contain exactly"):
        CalibrationProfile.create(**data)


def test_profile_rejects_negative_variance_component() -> None:
    data = _profile().to_dict()
    data.pop("profile_id")
    data["variance_components"]["stable"]["judge"] = -0.1

    with pytest.raises(ValidationError, match="variance components for 'stable' must be finite and non-negative"):
        CalibrationProfile.create(**data)


def test_profile_create_rejects_unknown_fields() -> None:
    data = _profile().to_dict()
    data.pop("profile_id")
    data["weighting_methd"] = "equal"

    with pytest.raises(ValueError, match="unexpected calibration profile fields.*weighting_methd"):
        CalibrationProfile.create(**data)


def test_profile_rejects_unsupported_schema_version() -> None:
    data = _profile().to_dict()
    data["schema_version"] = 2

    with pytest.raises(ValidationError, match="unsupported calibration profile schema version"):
        CalibrationProfile.from_dict(data)


def test_profile_classifies_context_compatibility() -> None:
    profile = _profile()
    metadata_only_change = _context()
    metadata_only_change["metadata"] = {"new_diagnostic": True}

    assert profile.compatibility_with(_context()) == ProfileCompatibility.COMPATIBLE
    assert profile.compatibility_with(metadata_only_change) == ProfileCompatibility.COMPATIBLE
    assert profile.compatibility_with(_context("dataset-b")) == ProfileCompatibility.INCOMPATIBLE
    assert profile.compatibility_with(None) == ProfileCompatibility.INCOMPATIBLE


def test_profile_classifies_old_algorithm_as_stale() -> None:
    profile = _profile(algorithm_version=0)

    assert profile.runtime_compatibility == ProfileCompatibility.STALE
    assert profile.compatibility_with(_context()) == ProfileCompatibility.STALE
    with pytest.raises(ValueError, match="cannot restore stale calibration profile"):
        Calibrator.from_profile(profile)


def test_profile_rejects_future_algorithm_during_restore() -> None:
    profile = _profile(algorithm_version=2)

    assert profile.runtime_compatibility == ProfileCompatibility.INCOMPATIBLE
    with pytest.raises(ValueError, match="cannot restore incompatible calibration profile"):
        Calibrator.from_profile(profile)


def test_profile_rejects_unsupported_calibration_context_version() -> None:
    context = _context()
    context["version"] = "2"
    profile = _profile(calibration_context=context)

    assert profile.runtime_compatibility == ProfileCompatibility.INCOMPATIBLE
    with pytest.raises(ValueError, match="cannot restore incompatible calibration profile"):
        Calibrator.from_profile(profile)


def test_profile_without_context_cannot_be_restored() -> None:
    profile = _profile(calibration_context={})

    assert profile.runtime_compatibility == ProfileCompatibility.INCOMPATIBLE
    with pytest.raises(ValueError, match="cannot restore incompatible calibration profile"):
        Calibrator.from_profile(profile)


def test_context_free_profile_cannot_be_compared_to_full_context() -> None:
    profile = _profile(
        calibration_context={},
        report_structure_fingerprint="a" * 64,
    )

    assert profile.runtime_compatibility == ProfileCompatibility.COMPATIBLE
    assert profile.compatibility_with(_context()) == ProfileCompatibility.INCOMPATIBLE


def test_mutated_profile_is_rejected_before_serialization_or_restore() -> None:
    profile = _profile()
    profile.weights["stable"] = 0.7
    profile.weights["noisy"] = 0.3

    with pytest.raises(ValidationError, match="profile ID does not match"):
        profile.to_dict()
    with pytest.raises(ValidationError, match="profile ID does not match"):
        Calibrator.from_profile(profile)


def test_calibration_context_keeps_audit_metadata_without_raw_inputs_or_rubrics() -> None:
    context = _build_calibration_context(
        cases=[Case(name="private customer case name", input="private customer input")],
        evaluators=[
            ConcisenessEvaluator(
                model="judge-model",
                system_prompt="private evaluator rubric",
                name="concise",
            )
        ],
        step_sizes={"concise": 0.5},
    )

    metadata = context["metadata"]
    assert metadata["dataset"] == {
        "fingerprint": context["dataset"],
        "case_count": 1,
        "named_case_count": 1,
    }
    evaluator_metadata = metadata["evaluators"][0]
    assert evaluator_metadata["name"] == "concise"
    assert evaluator_metadata["judge_model"]["model_id"] == "judge-model"
    assert evaluator_metadata["system_prompt"]["character_count"] == len("private evaluator rubric")

    serialized = json.dumps(context)
    assert "private customer case name" not in serialized
    assert "private customer input" not in serialized
    assert "private evaluator rubric" not in serialized
