"""Tests for Tau3 calibration configuration comparison helpers."""

from compare_configurations import _correlation, _held_out_association


def test_correlation_returns_none_for_constant_values() -> None:
    assert _correlation([1.0, 1.0], [0.0, 1.0]) is None


def test_held_out_association_compares_equal_and_learned_weights() -> None:
    evaluator_names = ("a", "b")
    index = {
        ("case-0", 0, 0, "a"): 0.0,
        ("case-0", 0, 0, "b"): 1.0,
        ("case-1", 0, 0, "a"): 1.0,
        ("case-1", 0, 0, "b"): 1.0,
        ("case-2", 0, 0, "a"): 0.0,
        ("case-2", 0, 0, "b"): 0.0,
    }

    result = _held_out_association(
        index=index,
        native_rewards={
            ("case-0", 0): 0.0,
            ("case-1", 0): 1.0,
            ("case-2", 0): 0.0,
        },
        case_names=["case-0", "case-1", "case-2"],
        run_ids=[0],
        replay_ids=[0],
        evaluator_names=evaluator_names,
        learned_weights={"a": 1.0, "b": 0.0},
    )

    assert result["learned_weight_correlation"] == 1.0
    assert result["correlation_delta"] is not None
    assert result["correlation_delta"] > 0.0
