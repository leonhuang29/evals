import pytest

from strands_evals.experimental.comparison import (
    PairedTrialScore,
    aggregate_trial_pairs,
    pair_report_trials,
    pair_reports,
    summarize_pairs,
)
from strands_evals.types.evaluation import NOT_APPLICABLE, EvaluationOutput
from strands_evals.types.evaluation_report import EvaluationReport


def _report(rows: list[dict]) -> EvaluationReport:
    return EvaluationReport(
        overall_score=sum(row["score"] for row in rows) / len(rows) if rows else 0.0,
        scores=[row["score"] for row in rows],
        cases=[row["case"] for row in rows],
        test_passes=[True] * len(rows),
        detailed_results=[row.get("details", []) for row in rows],
    )


def _row(
    *,
    name: str | None,
    evaluator: str = "helpfulness",
    score: float,
    input_value: object = "question",
    session_id: str = "session",
    actual_output: str = "output",
    details: list[EvaluationOutput] | None = None,
) -> dict:
    return {
        "score": score,
        "case": {
            "name": name,
            "input": input_value,
            "actual_output": actual_output,
            "session_id": session_id,
            "evaluator": evaluator,
        },
        "details": details or [],
    }


def test_pairs_rows_by_case_and_evaluator_regardless_of_order():
    baseline = _report(
        [
            _row(name="case-b", evaluator="correctness", score=0.4),
            _row(name="case-a", evaluator="helpfulness", score=0.3),
            _row(name="case-a", evaluator="correctness", score=0.6),
        ]
    )
    candidate = _report(
        [
            _row(
                name="case-a",
                evaluator="correctness",
                score=0.9,
                session_id="new-session",
                actual_output="new output",
            ),
            _row(name="case-b", evaluator="correctness", score=0.2),
            _row(name="case-a", evaluator="helpfulness", score=0.5),
        ]
    )

    paired = pair_reports(baseline, candidate)

    assert [(pair.evaluator, pair.case_id) for pair in paired] == [
        ("correctness", "case-a"),
        ("correctness", "case-b"),
        ("helpfulness", "case-a"),
    ]
    assert [pair.delta for pair in paired] == pytest.approx([0.3, -0.2, 0.2])


def test_unnamed_cases_are_paired_by_input():
    baseline = _report([_row(name=None, score=0.25, input_value={"prompt": "hello"}, session_id="baseline")])
    candidate = _report([_row(name=None, score=0.75, input_value={"prompt": "hello"}, session_id="candidate")])

    paired = pair_reports(baseline, candidate)

    assert len(paired) == 1
    assert paired[0].case_id.startswith("input:")
    assert paired[0].delta == 0.5


def test_omits_rows_that_are_not_applicable_in_both_reports():
    not_applicable = [EvaluationOutput(score=0.0, test_pass=True, label=NOT_APPLICABLE, reason="nothing to judge")]
    baseline = _report([_row(name="unused", score=0.0, details=not_applicable)])
    candidate = _report([_row(name="unused", score=0.0, details=not_applicable)])

    assert pair_reports(baseline, candidate) == []


def test_rejects_applicability_mismatch():
    not_applicable = [EvaluationOutput(score=0.0, test_pass=True, label=NOT_APPLICABLE)]
    baseline = _report([_row(name="case", score=0.0, details=not_applicable)])
    candidate = _report([_row(name="case", score=1.0)])

    with pytest.raises(ValueError, match="applicability differs"):
        pair_reports(baseline, candidate)


def test_rejects_same_named_case_with_different_inputs():
    baseline = _report([_row(name="case", score=0.0, input_value="first")])
    candidate = _report([_row(name="case", score=1.0, input_value="second")])

    with pytest.raises(ValueError, match="case inputs differ"):
        pair_reports(baseline, candidate)


def test_rejects_missing_case_evaluator_rows():
    baseline = _report([_row(name="case-a", score=0.0)])
    candidate = _report([_row(name="case-b", score=1.0)])

    with pytest.raises(ValueError, match="same case/evaluator rows"):
        pair_reports(baseline, candidate)


def test_rejects_duplicate_case_evaluator_rows():
    baseline = _report([_row(name="case", score=0.0), _row(name="case", score=1.0)])

    with pytest.raises(ValueError, match="duplicate case/evaluator row"):
        pair_reports(baseline, baseline)


def test_rejects_missing_evaluator_name():
    baseline = _report([_row(name="case", evaluator="", score=0.0)])

    with pytest.raises(ValueError, match="non-empty evaluator name"):
        pair_reports(baseline, baseline)


def test_rejects_report_shape_mismatch():
    baseline = _report([_row(name="case", score=0.0)])
    baseline.scores = []

    with pytest.raises(ValueError, match="1 cases but 0 scores"):
        pair_reports(baseline, baseline)


def test_pairs_and_aggregates_reports_across_trials():
    baseline_reports = [
        _report(
            [
                _row(name="case-b", evaluator="correctness", score=0.3),
                _row(name="case-a", evaluator="correctness", score=0.1),
            ]
        ),
        _report(
            [
                _row(name="case-a", evaluator="correctness", score=0.5),
                _row(name="case-b", evaluator="correctness", score=0.7),
            ]
        ),
    ]
    candidate_reports = [
        _report(
            [
                _row(name="case-a", evaluator="correctness", score=0.3),
                _row(name="case-b", evaluator="correctness", score=0.4),
            ]
        ),
        _report(
            [
                _row(name="case-b", evaluator="correctness", score=0.9),
                _row(name="case-a", evaluator="correctness", score=0.6),
            ]
        ),
    ]

    trial_pairs = pair_report_trials(baseline_reports, candidate_reports)
    aggregated = aggregate_trial_pairs(trial_pairs)
    summary = summarize_pairs(aggregated, bootstrap_samples=100)[0]

    assert [(pair.case_id, pair.trial_index) for pair in trial_pairs] == [
        ("case-a", 0),
        ("case-a", 1),
        ("case-b", 0),
        ("case-b", 1),
    ]
    assert [pair.delta for pair in trial_pairs] == pytest.approx([0.2, 0.1, 0.1, 0.2])
    assert [pair.case_id for pair in aggregated] == ["case-a", "case-b"]
    assert [pair.baseline_score for pair in aggregated] == pytest.approx([0.3, 0.5])
    assert [pair.candidate_score for pair in aggregated] == pytest.approx([0.45, 0.65])
    assert [pair.trial_count for pair in aggregated] == [2, 2]
    assert summary.case_count == 2
    assert summary.trial_count == 2
    assert summary.mean_delta == pytest.approx(0.15)


@pytest.mark.parametrize(
    ("baseline_reports", "candidate_reports", "message"),
    [
        ([], [], "at least one trial"),
        (
            [_report([_row(name="case", score=0.0)])],
            [
                _report([_row(name="case", score=0.0)]),
                _report([_row(name="case", score=0.0)]),
            ],
            "same number of trials",
        ),
    ],
)
def test_rejects_invalid_trial_report_counts(
    baseline_reports: list[EvaluationReport],
    candidate_reports: list[EvaluationReport],
    message: str,
):
    with pytest.raises(ValueError, match=message):
        pair_report_trials(baseline_reports, candidate_reports)


def test_rejects_case_input_changes_across_trials():
    baseline_reports = [
        _report([_row(name="case", score=0.1, input_value="first")]),
        _report([_row(name="case", score=0.2, input_value="second")]),
    ]
    candidate_reports = [
        _report([_row(name="case", score=0.3, input_value="first")]),
        _report([_row(name="case", score=0.4, input_value="second")]),
    ]

    with pytest.raises(ValueError, match="same case/evaluator inputs"):
        pair_report_trials(baseline_reports, candidate_reports)


def test_rejects_applicability_changes_across_trials():
    not_applicable = [EvaluationOutput(score=0.0, test_pass=True, label=NOT_APPLICABLE)]
    baseline_reports = [
        _report([_row(name="case", score=0.0, details=not_applicable)]),
        _report([_row(name="case", score=0.2)]),
    ]
    candidate_reports = [
        _report([_row(name="case", score=0.0, details=not_applicable)]),
        _report([_row(name="case", score=0.3)]),
    ]

    with pytest.raises(ValueError, match="same applicable case/evaluator rows"):
        pair_report_trials(baseline_reports, candidate_reports)


def test_rejects_incomplete_or_duplicate_trial_pairs():
    first = PairedTrialScore(
        case_id="case-a",
        evaluator="correctness",
        baseline_score=0.1,
        candidate_score=0.2,
        delta=0.1,
        trial_index=0,
    )
    second = PairedTrialScore(
        case_id="case-b",
        evaluator="correctness",
        baseline_score=0.3,
        candidate_score=0.4,
        delta=0.1,
        trial_index=1,
    )

    with pytest.raises(ValueError, match="duplicate trial/case/evaluator row"):
        aggregate_trial_pairs([first, first])
    with pytest.raises(ValueError, match="does not contain every trial"):
        aggregate_trial_pairs([first, second])


def test_removes_explicitly_corrupted_trials_before_aggregation():
    pairs = [
        PairedTrialScore(
            case_id="case",
            evaluator="correctness",
            baseline_score=baseline,
            candidate_score=candidate,
            delta=candidate - baseline,
            trial_index=trial_index,
        )
        for trial_index, baseline, candidate in [
            (0, 0.1, 0.2),
            (1, 0.9, 0.0),
            (2, 0.3, 0.6),
        ]
    ]

    aggregated = aggregate_trial_pairs(pairs, corrupted_trial_indices={1})

    assert len(aggregated) == 1
    assert aggregated[0].baseline_score == pytest.approx(0.2)
    assert aggregated[0].candidate_score == pytest.approx(0.4)
    assert aggregated[0].delta == pytest.approx(0.2)
    assert aggregated[0].trial_count == 2


def test_rejects_unknown_or_all_corrupted_trials():
    pair = PairedTrialScore(
        case_id="case",
        evaluator="correctness",
        baseline_score=0.1,
        candidate_score=0.2,
        delta=0.1,
        trial_index=0,
    )

    with pytest.raises(ValueError, match="unknown trials"):
        aggregate_trial_pairs([pair], corrupted_trial_indices={1})
    with pytest.raises(ValueError, match="no usable trials"):
        aggregate_trial_pairs([pair], corrupted_trial_indices={0})
