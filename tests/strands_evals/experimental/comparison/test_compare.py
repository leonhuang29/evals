import pytest

from strands_evals.experimental.comparison import compare_paired
from strands_evals.types.evaluation_report import EvaluationReport


def _report(evaluator_deltas: dict[str, list[float]], *, trial_offset: float = 0.0) -> EvaluationReport:
    cases: list[dict] = []
    scores: list[float] = []
    for evaluator, deltas in evaluator_deltas.items():
        for index, delta in enumerate(deltas):
            baseline_score = 0.2 + index * 0.1 + trial_offset
            cases.append(
                {
                    "name": f"case-{index}",
                    "input": f"input-{index}",
                    "evaluator": evaluator,
                }
            )
            scores.append(baseline_score + delta)

    return EvaluationReport(
        overall_score=sum(scores) / len(scores),
        scores=scores,
        cases=cases,
        test_passes=[True] * len(scores),
        detailed_results=[[] for _ in scores],
    )


def test_compares_single_reports():
    baseline = _report({"correctness": [0.0] * 6})
    candidate = _report({"correctness": [0.1] * 6})

    result = compare_paired(baseline, candidate, bootstrap_samples=100)

    assert result.verdict == "improved"
    assert result.trial_count == 1
    assert result.corrupted_trial_indices == []
    assert len(result.pairs) == 6
    assert result.evaluator_summaries[0].verdict == "improved"


def test_reports_tradeoff_across_evaluators_and_trials():
    baseline = [
        _report({"correctness": [0.0] * 6, "helpfulness": [0.0] * 6}),
        _report({"correctness": [0.0] * 6, "helpfulness": [0.0] * 6}, trial_offset=0.02),
    ]
    candidate = [
        _report({"correctness": [0.1] * 6, "helpfulness": [-0.1] * 6}),
        _report({"correctness": [0.1] * 6, "helpfulness": [-0.1] * 6}, trial_offset=0.02),
    ]

    result = compare_paired(baseline, candidate, bootstrap_samples=100)

    assert result.verdict == "tradeoff"
    assert result.trial_count == 2
    assert {summary.evaluator: summary.verdict for summary in result.evaluator_summaries} == {
        "correctness": "improved",
        "helpfulness": "regressed",
    }


def test_excludes_corrupted_trials_from_public_result():
    baseline = [
        _report({"correctness": [0.0] * 6}),
        _report({"correctness": [0.0] * 6}, trial_offset=0.02),
    ]
    candidate = [
        _report({"correctness": [0.1] * 6}),
        _report({"correctness": [-0.2] * 6}, trial_offset=0.02),
    ]

    result = compare_paired(baseline, candidate, corrupted_trial_indices={1}, bootstrap_samples=100)

    assert result.verdict == "improved"
    assert result.trial_count == 1
    assert result.corrupted_trial_indices == [1]
    assert all(pair.trial_count == 1 for pair in result.pairs)


def test_rejects_unknown_or_all_corrupted_trials():
    baseline = _report({"correctness": [0.0] * 6})
    candidate = _report({"correctness": [0.1] * 6})

    with pytest.raises(ValueError, match="unknown trials"):
        compare_paired(baseline, candidate, corrupted_trial_indices={1})
    with pytest.raises(ValueError, match="no usable trials"):
        compare_paired(baseline, candidate, corrupted_trial_indices={0})
