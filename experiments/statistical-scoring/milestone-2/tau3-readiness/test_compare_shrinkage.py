"""Tests for Tau3 equal-to-learned shrinkage helpers."""

import pytest
from compare_shrinkage import _blend_weights, _validate_learned_fractions


def test_blend_weights_preserves_equal_and_learned_endpoints() -> None:
    learned = {"stable": 0.8, "noisy": 0.2}

    assert _blend_weights(learned, 0.0) == pytest.approx({"stable": 0.5, "noisy": 0.5})
    assert _blend_weights(learned, 0.5) == pytest.approx({"stable": 0.65, "noisy": 0.35})
    assert _blend_weights(learned, 1.0) == pytest.approx(learned)


@pytest.mark.parametrize("value", [-0.1, 1.1, float("inf")])
def test_blend_weights_rejects_invalid_fraction(value: float) -> None:
    with pytest.raises(ValueError, match="between 0 and 1"):
        _blend_weights({"stable": 1.0}, value)


def test_validate_learned_fractions_requires_both_endpoints() -> None:
    with pytest.raises(ValueError, match="must include 0 and 1"):
        _validate_learned_fractions([0.25, 0.5, 0.75])
