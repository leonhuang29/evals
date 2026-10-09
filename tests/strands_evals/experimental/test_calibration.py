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


def test_fit_retains_variance_and_reliability_diagnostics() -> None:
    calibrator = Calibrator(step_sizes={"stable": 0.25, "noisy": 0.25})

    calibrator.fit(_calibration_reports())

    assert calibrator.variance_components["stable"] == pytest.approx(
        {
            "judge": 0.0,
            "agent": 0.0,
            "case": 0.5,
        }
    )
    assert calibrator.variance_components["noisy"] == pytest.approx(
        {
            "judge": 0.5,
            "agent": 0.0,
            "case": 0.0,
        }
    )
    assert calibrator.reliabilities == pytest.approx({"stable": 1.0, "noisy": 0.0})


def test_fit_computes_all_candidate_weight_vectors() -> None:
    reports = [
        [
            _report(
                {
                    "fine": {"case-a": 0.0, "case-b": 1.0},
                    "coarse": {"case-a": 0.0, "case-b": 1.0},
                }
            )
        ]
        * 2,
    ] * 2
    calibrator = Calibrator(step_sizes={"fine": 0.25, "coarse": 1.0})

    calibrator.fit(reports)

    assert calibrator.candidate_weights["equal"] == pytest.approx({"fine": 0.5, "coarse": 0.5})
    assert calibrator.candidate_weights["reliability"] == pytest.approx({"fine": 0.5, "coarse": 0.5})
    assert calibrator.candidate_weights["inverse_step"] == pytest.approx({"fine": 0.8, "coarse": 0.2})
    assert calibrator.candidate_weights["inverse_sqrt_step"] == pytest.approx({"fine": 2 / 3, "coarse": 1 / 3})


def test_calibrator_can_select_candidate_weighting_method() -> None:
    reports = [
        [
            _report(
                {
                    "fine": {"case-a": 0.0, "case-b": 1.0},
                    "coarse": {"case-a": 0.0, "case-b": 1.0},
                }
            )
        ]
        * 2,
    ] * 2
    calibrator = Calibrator(
        step_sizes={"fine": 0.25, "coarse": 1.0},
        weighting_method="inverse_step",
    )

    calibrator.fit(reports)

    assert calibrator.weighting_method == "inverse_step"
    assert calibrator.weights == pytest.approx({"fine": 0.8, "coarse": 0.2})


def test_score_candidates_compares_composite_sensitivity() -> None:
    reports = [
        [
            _report(
                {
                    "fine": {"case-a": 0.0, "case-b": 1.0},
                    "coarse": {"case-a": 0.0, "case-b": 1.0},
                }
            )
        ]
        * 2,
    ] * 2
    calibrator = Calibrator(step_sizes={"fine": 0.25, "coarse": 1.0})
    calibrator.fit(reports)

    scores = calibrator.score_candidates(
        _report(
            {
                "fine": {"case-a": 1.0, "case-b": 1.0},
                "coarse": {"case-a": 0.0, "case-b": 0.0},
            }
        )
    )

    assert scores == pytest.approx(
        {
            "equal": 0.5,
            "reliability": 0.5,
            "inverse_step": 0.8,
            "inverse_sqrt_step": 2 / 3,
        }
    )


def test_fit_computes_reproducible_hierarchical_bootstrap_intervals() -> None:
    reports = [
        [
            _report(
                {
                    "fine": {"case-a": 0.0, "case-b": 1.0},
                    "coarse": {"case-a": 0.0, "case-b": 1.0},
                }
            )
        ]
        * 2,
    ] * 2
    first = Calibrator(step_sizes={"fine": 0.25, "coarse": 1.0})
    second = Calibrator(step_sizes={"fine": 0.25, "coarse": 1.0})

    first.fit(reports, bootstrap_replicates=200, bootstrap_seed=17)
    second.fit(reports, bootstrap_replicates=200, bootstrap_seed=17)

    assert first.bootstrap_replicates == 200
    assert first.bootstrap_seed == 17
    assert first.reliability_intervals == second.reliability_intervals
    assert first.candidate_weight_intervals == second.candidate_weight_intervals
    assert first.composite_score_intervals == second.composite_score_intervals

    fine_reliability = first.reliability_intervals["fine"]
    assert fine_reliability["defined_replicates"] == 200
    assert fine_reliability["undefined_replicates"] == 0
    assert fine_reliability["lower_2_5"] == pytest.approx(0.0)
    assert fine_reliability["upper_97_5"] == pytest.approx(1.0)

    equal_fine = first.candidate_weight_intervals["equal"]["fine"]
    assert equal_fine["mean"] == pytest.approx(0.5)
    assert equal_fine["defined_replicates"] == 200
    assert equal_fine["undefined_replicates"] == 0

    learned_fine = first.candidate_weight_intervals["inverse_sqrt_step"]["fine"]
    assert learned_fine["mean"] == pytest.approx(2 / 3)
    assert 0 < learned_fine["defined_replicates"] < 200
    assert learned_fine["undefined_replicates"] == 200 - learned_fine["defined_replicates"]

    learned_score = first.composite_score_intervals["inverse_sqrt_step"]
    assert learned_score["mean"] == pytest.approx(0.5)
    assert learned_score["defined_replicates"] == learned_fine["defined_replicates"]
    assert learned_score["undefined_replicates"] == learned_fine["undefined_replicates"]

    equal_score = first.composite_score_intervals["equal"]
    assert equal_score["defined_replicates"] == 200
    assert equal_score["lower_2_5"] == pytest.approx(0.0)
    assert equal_score["upper_97_5"] == pytest.approx(1.0)


def test_fit_without_bootstrap_clears_previous_intervals() -> None:
    calibrator = Calibrator(step_sizes={"stable": 0.25, "noisy": 0.25})
    reports = _calibration_reports()
    calibrator.fit(reports, bootstrap_replicates=20, bootstrap_seed=4)

    calibrator.fit(reports)

    assert calibrator.bootstrap_replicates == 0
    assert calibrator.bootstrap_seed is None
    assert calibrator.reliability_intervals == {}
    assert calibrator.candidate_weight_intervals == {}
    assert calibrator.composite_score_intervals == {}


@pytest.mark.parametrize("replicates", [-1, 1])
def test_fit_rejects_invalid_bootstrap_replicates(replicates: int) -> None:
    calibrator = Calibrator(step_sizes={"stable": 0.25, "noisy": 0.25})

    with pytest.raises(ValueError, match="bootstrap_replicates must be 0 or >= 2"):
        calibrator.fit(_calibration_reports(), bootstrap_replicates=replicates)


def test_fit_rejects_invalid_bootstrap_seed() -> None:
    calibrator = Calibrator(step_sizes={"stable": 0.25, "noisy": 0.25})

    with pytest.raises(ValueError, match="bootstrap_seed must be an integer"):
        calibrator.fit(
            _calibration_reports(),
            bootstrap_replicates=2,
            bootstrap_seed="invalid",  # type: ignore[arg-type]
        )


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

    calibrator.fit(reports, bootstrap_replicates=20, bootstrap_seed=3)

    assert calibrator.weights == {"first": 0.5, "second": 0.5}
    assert calibrator.is_fitted is False
    assert calibrator.candidate_weights == {
        "equal": {"first": 0.5, "second": 0.5},
        "reliability": None,
        "inverse_step": None,
        "inverse_sqrt_step": None,
    }
    assert calibrator.candidate_weight_intervals["inverse_sqrt_step"]["first"] == {
        "mean": None,
        "lower_2_5": None,
        "median": None,
        "upper_97_5": None,
        "defined_replicates": 0,
        "undefined_replicates": 20,
    }
    assert calibrator.composite_score_intervals["inverse_sqrt_step"] == {
        "mean": None,
        "lower_2_5": None,
        "median": None,
        "upper_97_5": None,
        "defined_replicates": 0,
        "undefined_replicates": 20,
    }


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
        bootstrap_replicates=20,
        bootstrap_seed=9,
    )

    assert task_calls == 4
    assert first.calls == 12
    assert second.calls == 12
    assert score == pytest.approx(0.5)
    assert calibrator.weights == {"first": 0.5, "second": 0.5}
    assert calibrator.is_fitted is True
    assert calibrator.bootstrap_replicates == 20
    assert calibrator.bootstrap_seed == 9


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


def test_calibrator_rejects_unknown_weighting_method() -> None:
    with pytest.raises(ValueError, match="unknown weighting method"):
        Calibrator(
            step_sizes={"quality": 0.5},
            weighting_method="unknown",  # type: ignore[arg-type]
        )
