import pytest
from strands import Agent


@pytest.mark.parametrize(
    "limits",
    [
        {"max_turns": 3},
        {"turn": 3},
        {"turns": 3, "max_tokens": 100},
    ],
)
def test_unrecognized_limit_keys_raise_before_invocation(limits):
    with pytest.raises(TypeError):
        Agent._validate_limits(limits)


def test_recognized_limit_keys_remain_valid():
    Agent._validate_limits({"turns": 1, "output_tokens": 2, "total_tokens": 3})
