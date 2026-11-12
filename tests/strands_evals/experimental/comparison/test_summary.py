import pytest

from strands_evals.experimental.comparison import PairedScore, summarize_pairs


def _pair(*, case_id: str, evaluator: str, baseline: float, candidate: float) -> PairedScore:
    return PairedScore(
        case_id=case_id,
        evaluator=evaluator,
        baseline_score=baseline,
        candidate_score=candidate,
        delta=candidate - baseline,
    )


def test_summarizes_case_deltas_by_evaluator():
    summaries = summarize_pairs(
        [
            _pair(case_id="case-b", evaluator="correctness", baseline=0.2, candidate=0.4),
            _pair(case_id="case-a", evaluator="helpfulness", baseline=0.8, candidate=0.7),
            _pair(case_id="case-a", evaluator="correctness", baseline=0.1, candidate=0.3),
        ],
        bootstrap_samples=100,
    )

    assert [summary.evaluator for summary in summaries] == ["correctness", "helpfulness"]
    assert summaries[0].case_count == 2
    assert summaries[0].mean_delta == pytest.approx(0.2)
    assert summaries[0].confidence_lower == pytest.approx(0.2)
    assert summaries[0].confidence_upper == pytest.approx(0.2)
    assert summaries[0].wilcoxon_p_value == pytest.approx(0.5)
    assert summaries[0].adjusted_p_value == pytest.approx(0.5)
    assert summaries[1].case_count == 1
    assert summaries[1].mean_delta == pytest.approx(-0.1)
    assert summaries[1].confidence_lower is None
    assert summaries[1].confidence_upper is None
    assert summaries[1].wilcoxon_p_value is None
    assert summaries[1].adjusted_p_value is None


def test_bootstrap_interval_reflects_case_variation():
    summary = summarize_pairs(
        [
            _pair(case_id="case-a", evaluator="correctness", baseline=0.1, candidate=0.2),
            _pair(case_id="case-b", evaluator="correctness", baseline=0.2, candidate=0.5),
            _pair(case_id="case-c", evaluator="correctness", baseline=0.8, candidate=0.4),
        ],
        bootstrap_samples=500,
        seed=7,
    )[0]

    assert summary.confidence_lower is not None
    assert summary.confidence_upper is not None
    assert summary.confidence_lower < summary.mean_delta < summary.confidence_upper


def test_bootstrap_interval_is_deterministic_regardless_of_input_order():
    pairs = [
        _pair(case_id="case-a", evaluator="correctness", baseline=0.1, candidate=0.2),
        _pair(case_id="case-b", evaluator="correctness", baseline=0.2, candidate=0.5),
        _pair(case_id="case-c", evaluator="correctness", baseline=0.8, candidate=0.4),
    ]

    forward = summarize_pairs(pairs, bootstrap_samples=200, seed=7)
    reverse = summarize_pairs(list(reversed(pairs)), bootstrap_samples=200, seed=7)

    assert forward == reverse


def test_returns_empty_list_when_there_are_no_pairs():
    assert summarize_pairs([]) == []


def test_adjusts_wilcoxon_p_values_across_evaluators():
    pairs = [
        _pair(case_id=f"case-{index}", evaluator="consistent", baseline=0.1, candidate=candidate)
        for index, candidate in enumerate([0.2, 0.3, 0.4, 0.5])
    ]
    pairs.extend(
        _pair(case_id=f"case-{index}", evaluator="mixed", baseline=0.5, candidate=candidate)
        for index, candidate in enumerate([0.6, 0.7, 0.2, 0.9])
    )

    summaries = summarize_pairs(pairs, bootstrap_samples=100)

    assert [summary.wilcoxon_p_value for summary in summaries] == pytest.approx([0.125, 0.625])
    assert [summary.adjusted_p_value for summary in summaries] == pytest.approx([0.25, 0.625])


def test_all_zero_deltas_have_p_value_one():
    summary = summarize_pairs(
        [
            _pair(case_id="case-a", evaluator="correctness", baseline=0.2, candidate=0.2),
            _pair(case_id="case-b", evaluator="correctness", baseline=0.4, candidate=0.4),
        ],
        bootstrap_samples=100,
    )[0]

    assert summary.wilcoxon_p_value == 1.0
    assert summary.adjusted_p_value == 1.0


def test_rejects_duplicate_case_evaluator_rows():
    pair = _pair(case_id="case", evaluator="correctness", baseline=0.1, candidate=0.2)

    with pytest.raises(ValueError, match="duplicate case/evaluator row"):
        summarize_pairs([pair, pair])


@pytest.mark.parametrize("confidence_level", [0.0, 1.0])
def test_rejects_invalid_confidence_level(confidence_level: float):
    with pytest.raises(ValueError, match="confidence_level"):
        summarize_pairs([], confidence_level=confidence_level)


def test_rejects_invalid_bootstrap_sample_count():
    with pytest.raises(ValueError, match="bootstrap_samples"):
        summarize_pairs([], bootstrap_samples=0)
