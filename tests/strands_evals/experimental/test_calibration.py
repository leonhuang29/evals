import pytest

from strands_evals import Case, Experiment
from strands_evals.evaluators import Evaluator
from strands_evals.experimental import Calibrator
from strands_evals.types import EvaluationData, EvaluationOutput
from strands_evals.types.evaluation_report import EvaluationReport


def _report(scores: dict[str, dict[str, float]]) -> EvaluationReport:
    report_scores: list[float] = []
    cases: list[dict] = []
    passes: list[bool] = []
    for evaluator_name, case_scores in scores.items():
        for case_name, score in case_scores.items():
            report_scores.append(score)
            cases.append({"name": case_name, "evaluator": evaluator_name})
            passes.append(score >= 0.5)
    return EvaluationReport(
        overall_score=sum(report_scores) / len(report_scores),
        scores=report_scores,
        cases=cases,
        test_passes=passes,
    )


def _calibration_reports() -> list[list[EvaluationReport]]:
    reports: list[list[EvaluationReport]] = []
    for _ in range(2):
        run_reports = []
        for replay in range(2):
            run_reports.append(
                _report(
                    {
                        "stable": {"case-a": 0.0, "case-b": 1.0},
                        "noisy": {
                            "case-a": float(replay),
                            "case-b": float(replay),
                        },
                    }
                )
            )
        reports.append(run_reports)
    return reports


class _CountingEvaluator(Evaluator[str, str]):
    def __init__(self, name: str):
        super().__init__(name=name)
        self.calls = 0

    def evaluate(self, evaluation_case: EvaluationData[str, str]) -> list[EvaluationOutput]:
        self.calls += 1
        score = 1.0 if evaluation_case.input == "good" else 0.0
        return [EvaluationOutput(score=score, test_pass=score == 1.0)]


def test_calibrator_starts_with_equal_weights() -> None:
    calibrator = Calibrator(step_sizes={"stable": 0.25, "noisy": 0.25})

    assert calibrator.weights == {"stable": 0.5, "noisy": 0.5}
    assert calibrator.is_fitted is False
    assert calibrator.score(
        _report(
            {
                "stable": {"case-a": 0.0, "case-b": 1.0},
                "noisy": {"case-a": 1.0, "case-b": 1.0},
            }
        )
    ) == pytest.approx(0.75)


def test_fit_learns_reliability_weighted_vector() -> None:
    calibrator = Calibrator(step_sizes={"stable": 0.25, "noisy": 0.25})

    returned = calibrator.fit(_calibration_reports())

    assert returned is calibrator
    assert calibrator.is_fitted is True
    assert calibrator.weights["stable"] == pytest.approx(1.0)
    assert calibrator.weights["noisy"] == pytest.approx(0.0)


def test_score_uses_fitted_weights() -> None:
    calibrator = Calibrator(step_sizes={"stable": 0.25, "noisy": 0.25})
    calibrator.fit(_calibration_reports())

    score = calibrator.score(
        _report(
            {
                "stable": {"case-a": 0.0, "case-b": 1.0},
                "noisy": {"case-a": 1.0, "case-b": 1.0},
            }
        )
    )

    assert score == pytest.approx(0.5)


def test_fit_keeps_equal_weights_when_no_case_signal_exists() -> None:
    reports = [
        [
            _report({"first": {"case-a": 0.5, "case-b": 0.5}, "second": {"case-a": 0.5, "case-b": 0.5}}),
            _report({"first": {"case-a": 0.5, "case-b": 0.5}, "second": {"case-a": 0.5, "case-b": 0.5}}),
        ],
        [
            _report({"first": {"case-a": 0.5, "case-b": 0.5}, "second": {"case-a": 0.5, "case-b": 0.5}}),
            _report({"first": {"case-a": 0.5, "case-b": 0.5}, "second": {"case-a": 0.5, "case-b": 0.5}}),
        ],
    ]
    calibrator = Calibrator(step_sizes={"first": 0.5, "second": 0.5})

    calibrator.fit(reports)

    assert calibrator.weights == {"first": 0.5, "second": 0.5}
    assert calibrator.is_fitted is False


def test_run_evaluations_reuses_each_agent_output_for_judge_replays() -> None:
    first = _CountingEvaluator(name="first")
    second = _CountingEvaluator(name="second")
    experiment = Experiment(
        cases=[
            Case(name="good-case", input="good"),
            Case(name="bad-case", input="bad"),
        ],
        evaluators=[first, second],
    )
    task_calls = 0

    def task(case: Case[str, str]) -> str:
        nonlocal task_calls
        task_calls += 1
        return case.input

    calibrator = Calibrator(step_sizes={"first": 0.5, "second": 0.5})
    score = calibrator.run_evaluations(
        experiment,
        task,
        agent_runs=2,
        judge_replays=3,
    )

    assert task_calls == 4
    assert first.calls == 12
    assert second.calls == 12
    assert score == pytest.approx(0.5)
    assert calibrator.weights == {"first": 0.5, "second": 0.5}
    assert calibrator.is_fitted is True


@pytest.mark.asyncio
async def test_run_evaluations_async_accepts_async_task() -> None:
    evaluator = _CountingEvaluator(name="quality")
    experiment = Experiment(
        cases=[
            Case(name="good-case", input="good"),
            Case(name="bad-case", input="bad"),
        ],
        evaluators=[evaluator],
    )
    task_calls = 0

    async def task(case: Case[str, str]) -> str:
        nonlocal task_calls
        task_calls += 1
        return case.input

    calibrator = Calibrator(step_sizes={"quality": 0.5})
    score = await calibrator.run_evaluations_async(
        experiment,
        task,
        agent_runs=2,
        judge_replays=2,
        max_workers=2,
    )

    assert task_calls == 4
    assert evaluator.calls == 8
    assert score == pytest.approx(0.5)
    assert calibrator.weights == {"quality": 1.0}
    assert calibrator.is_fitted is True


def test_fit_rejects_mismatched_evaluator_names() -> None:
    calibrator = Calibrator(step_sizes={"expected": 0.5})
    reports = [
        [_report({"unexpected": {"case-a": 0.0, "case-b": 1.0}})] * 2,
        [_report({"unexpected": {"case-a": 0.0, "case-b": 1.0}})] * 2,
    ]

    with pytest.raises(ValueError, match="evaluator names do not match"):
        calibrator.fit(reports)
