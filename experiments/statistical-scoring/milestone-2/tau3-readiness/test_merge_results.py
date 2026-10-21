"""Tests for merging disjoint calibration result shards."""

import pytest
from merge_results import merge


def _row(case: str, score: float) -> dict:
    return {
        "case": case,
        "agent_run": 0,
        "judge_replay": 0,
        "evaluator": "evaluator",
        "score": score,
    }


def test_merge_combines_disjoint_shards(tmp_path) -> None:
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    first.write_text('[{"case":"a","agent_run":0,"judge_replay":0,"evaluator":"evaluator","score":1.0}]')
    second.write_text('[{"case":"b","agent_run":0,"judge_replay":0,"evaluator":"evaluator","score":0.0}]')

    assert merge([first, second]) == [_row("a", 1.0), _row("b", 0.0)]


def test_merge_rejects_conflicting_duplicate_keys(tmp_path) -> None:
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    first.write_text('[{"case":"a","agent_run":0,"judge_replay":0,"evaluator":"evaluator","score":1.0}]')
    second.write_text('[{"case":"a","agent_run":0,"judge_replay":0,"evaluator":"evaluator","score":0.0}]')

    with pytest.raises(ValueError, match="conflicting observation"):
        merge([first, second])
