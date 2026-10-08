"""Experimental reliability-weighted evaluation calibration."""

import asyncio
import math
from collections.abc import Callable

from typing_extensions import Any, Generic, Self

from ..case import Case
from ..experiment import Experiment
from ..types.evaluation import EvaluationData, InputT, OutputT
from ..types.evaluation_report import EvaluationReport

_EPSILON = 1e-15


class _InMemoryEvaluationDataStore:
    """Private task-output cache used to replay evaluators on fixed outputs."""

    def __init__(self) -> None:
        self._results: dict[str, EvaluationData] = {}

    def load(self, case_name: str) -> EvaluationData | None:
        result = self._results.get(case_name)
        return result.model_copy(deep=True) if result is not None else None

    def save(self, case_name: str, result: EvaluationData) -> None:
        self._results[case_name] = result.model_copy(deep=True)


class Calibrator(Generic[InputT, OutputT]):
    """Learn and apply reliability-weighted evaluator weights.

    The calibrator treats each `EvaluationReport` as one judge replay. Reports
    are grouped first by independent agent run and then by judge replay:

    ```python
    calibrator.fit(
        [
            [run_0_replay_0, run_0_replay_1],
            [run_1_replay_0, run_1_replay_1],
        ]
    )
    ```

    `run_evaluations` builds this hierarchy automatically. Within one agent
    run, the task output is cached after the first replay so later replays call
    only the evaluators.
    """

    def __init__(self, step_sizes: dict[str, float]) -> None:
        """Initialize a calibrator with declared evaluator score steps.

        Args:
            step_sizes: Mapping from evaluator instance name to its smallest
                meaningful score increment.

        Raises:
            ValueError: If no evaluators are provided or a step is not finite
                and greater than zero.
        """
        if not step_sizes:
            raise ValueError("step_sizes must contain at least one evaluator")
        invalid = {
            name: step
            for name, step in step_sizes.items()
            if not isinstance(step, (int, float)) or not math.isfinite(step) or step <= 0
        }
        if invalid:
            raise ValueError(f"step_sizes must be finite and greater than zero: {invalid}")

        self._step_sizes = {name: float(step) for name, step in step_sizes.items()}
        self._weights = self._equal_weights()
        self._is_fitted = False

    @property
    def weights(self) -> dict[str, float]:
        """Return a copy of the current evaluator weight vector."""
        return dict(self._weights)

    @property
    def is_fitted(self) -> bool:
        """Whether the current weights contain measurable calibration signal."""
        return self._is_fitted

    def run_evaluations(
        self,
        experiment: Experiment[InputT, OutputT],
        task: Callable[[Case[InputT, OutputT]], OutputT | dict[str, Any]],
        *,
        agent_runs: int,
        judge_replays: int,
        max_workers: int = 1,
    ) -> float:
        """Run repeated evaluations, fit weights, and return a suite score.

        Args:
            experiment: Existing experiment containing cases and evaluators.
            task: Task function evaluated by the experiment.
            agent_runs: Number of independent task executions per case.
            judge_replays: Number of evaluator passes over each fixed output.
            max_workers: Maximum parallel case workers used by the experiment.

        Returns:
            The weighted score across the collected cases, runs, and replays.

        Raises:
            ValueError: If `task` is async or repetition counts are invalid.
        """
        if asyncio.iscoroutinefunction(task):
            raise ValueError("Async task is not supported. Please use run_evaluations_async instead.")
        return asyncio.run(
            self.run_evaluations_async(
                experiment,
                task,
                agent_runs=agent_runs,
                judge_replays=judge_replays,
                max_workers=max_workers,
            )
        )

    async def run_evaluations_async(
        self,
        experiment: Experiment[InputT, OutputT],
        task: Callable,
        *,
        agent_runs: int,
        judge_replays: int,
        max_workers: int = 10,
    ) -> float:
        """Asynchronously collect repeated reports, fit weights, and score them.

        Args:
            experiment: Existing experiment containing cases and evaluators.
            task: Synchronous or asynchronous task function.
            agent_runs: Number of independent task executions per case.
            judge_replays: Number of evaluator passes over each fixed output.
            max_workers: Maximum parallel case workers used by the experiment.

        Returns:
            The weighted score across the collected cases, runs, and replays.
        """
        self._validate_repetition_counts(agent_runs, judge_replays)
        if max_workers < 1:
            raise ValueError(f"max_workers must be >= 1, got {max_workers}")
        self._validate_evaluator_names({evaluator.get_name() for evaluator in experiment.evaluators})

        reports_by_run: list[list[EvaluationReport]] = []
        for _ in range(agent_runs):
            task_store = _InMemoryEvaluationDataStore()
            replay_reports: list[EvaluationReport] = []
            for _ in range(judge_replays):
                report = await experiment.run_evaluations_async(
                    task,
                    max_workers=max_workers,
                    evaluation_data_store=task_store,
                )
                replay_reports.append(report)
            reports_by_run.append(replay_reports)

        self.fit(reports_by_run)
        parsed, evaluator_names, case_names = self._parse_reports(reports_by_run)
        return self._score_parsed_reports(parsed, evaluator_names, case_names)

    def fit(self, reports_by_run: list[list[EvaluationReport]]) -> Self:
        """Learn evaluator weights from repeated evaluation reports.

        The outer list represents independent agent runs. Each inner list
        contains repeated judge evaluations of that run's fixed outputs.

        Args:
            reports_by_run: Reports grouped by agent run and judge replay.

        Returns:
            This calibrator with its weight vector updated.

        Raises:
            ValueError: If the report hierarchy is incomplete, unbalanced, or
                incompatible with the configured evaluator names.
        """
        parsed, evaluator_names, case_names = self._parse_reports(reports_by_run)
        run_count = len(parsed)
        replay_count = len(parsed[0])
        self._validate_repetition_counts(run_count, replay_count)
        if len(case_names) < 2:
            raise ValueError("calibration requires at least two cases")

        self._weights = self._equal_weights()
        self._is_fitted = False

        unnormalized: dict[str, float] = {}
        for evaluator_name in evaluator_names:
            reliability = self._estimate_reliability(
                parsed,
                evaluator_name,
                case_names,
                run_count,
                replay_count,
            )
            unnormalized[evaluator_name] = reliability / math.sqrt(self._step_sizes[evaluator_name])

        total = sum(unnormalized.values())
        if total <= _EPSILON:
            return self

        self._weights = {name: value / total for name, value in unnormalized.items()}
        self._is_fitted = True
        return self

    def score(self, report: EvaluationReport) -> float:
        """Apply the current weights to one ordinary evaluation report.

        Equal weights are used until `fit` learns a measurable weight vector.

        Args:
            report: Flattened report containing one row per case and evaluator.

        Returns:
            Weighted mean of the evaluator-level suite scores.
        """
        scores = self._extract_report_scores(report)
        evaluator_names = sorted(scores)
        self._validate_evaluator_names(set(evaluator_names))
        evaluator_scores = {
            evaluator_name: self._mean(list(scores[evaluator_name].values())) for evaluator_name in evaluator_names
        }
        return sum(self._weights[name] * evaluator_scores[name] for name in evaluator_names)

    def _equal_weights(self) -> dict[str, float]:
        weight = 1.0 / len(self._step_sizes)
        return {name: weight for name in self._step_sizes}

    @staticmethod
    def _validate_repetition_counts(agent_runs: int, judge_replays: int) -> None:
        if agent_runs < 2:
            raise ValueError(f"agent_runs must be >= 2, got {agent_runs}")
        if judge_replays < 2:
            raise ValueError(f"judge_replays must be >= 2, got {judge_replays}")

    def _validate_evaluator_names(self, observed: set[str]) -> None:
        configured = set(self._step_sizes)
        if observed == configured:
            return
        missing = sorted(configured - observed)
        unexpected = sorted(observed - configured)
        raise ValueError(f"evaluator names do not match step_sizes; missing={missing}, unexpected={unexpected}")

    def _parse_reports(
        self,
        reports_by_run: list[list[EvaluationReport]],
    ) -> tuple[list[list[dict[str, dict[str, float]]]], list[str], list[str]]:
        if not reports_by_run:
            raise ValueError("reports_by_run must contain at least one agent run")
        if not reports_by_run[0]:
            raise ValueError("each agent run must contain at least one judge replay")

        replay_count = len(reports_by_run[0])
        if any(len(reports) != replay_count for reports in reports_by_run):
            raise ValueError("every agent run must contain the same number of judge replays")

        parsed = [
            [self._extract_report_scores(report) for report in replay_reports] for replay_reports in reports_by_run
        ]
        first = parsed[0][0]
        evaluator_names = sorted(first)
        self._validate_evaluator_names(set(evaluator_names))
        case_names = sorted(next(iter(first.values())))

        for run_index, replay_reports in enumerate(parsed):
            for replay_index, report_scores in enumerate(replay_reports):
                if set(report_scores) != set(evaluator_names):
                    raise ValueError(f"run {run_index} replay {replay_index} has a different evaluator set")
                for evaluator_name in evaluator_names:
                    if set(report_scores[evaluator_name]) != set(case_names):
                        raise ValueError(
                            f"run {run_index} replay {replay_index} evaluator "
                            f"{evaluator_name!r} has a different case set"
                        )

        return parsed, evaluator_names, case_names

    @staticmethod
    def _extract_report_scores(report: EvaluationReport) -> dict[str, dict[str, float]]:
        if len(report.cases) != len(report.scores):
            raise ValueError("report cases and scores must have equal lengths")

        scores: dict[str, dict[str, float]] = {}
        for index, (case, raw_score) in enumerate(zip(report.cases, report.scores, strict=True)):
            evaluator_name = case.get("evaluator")
            case_name = case.get("name")
            if not isinstance(evaluator_name, str) or not evaluator_name:
                raise ValueError(f"report row {index} is missing an evaluator name")
            if not isinstance(case_name, str) or not case_name:
                raise ValueError(f"report row {index} is missing a case name")
            if not math.isfinite(raw_score) or not 0.0 <= raw_score <= 1.0:
                raise ValueError(f"report row {index} score must be between 0 and 1")

            outputs = report.detailed_results[index] if index < len(report.detailed_results) else []
            if index < len(report.detailed_results) and not EvaluationReport.is_applicable(outputs):
                raise ValueError(
                    f"calibration does not yet support not-applicable rows: "
                    f"case={case_name!r}, evaluator={evaluator_name!r}"
                )

            evaluator_scores = scores.setdefault(evaluator_name, {})
            if case_name in evaluator_scores:
                raise ValueError(
                    f"report contains duplicate case/evaluator row: case={case_name!r}, evaluator={evaluator_name!r}"
                )
            evaluator_scores[case_name] = float(raw_score)

        if not scores:
            raise ValueError("report must contain at least one score")

        case_sets = {frozenset(evaluator_scores) for evaluator_scores in scores.values()}
        if len(case_sets) != 1:
            raise ValueError("every evaluator in a report must score the same cases")
        return scores

    def _estimate_reliability(
        self,
        parsed: list[list[dict[str, dict[str, float]]]],
        evaluator_name: str,
        case_names: list[str],
        run_count: int,
        replay_count: int,
    ) -> float:
        replay_variances: list[float] = []
        run_means_by_case: dict[str, list[float]] = {case_name: [] for case_name in case_names}

        for case_name in case_names:
            for run_reports in parsed:
                replay_scores = [report_scores[evaluator_name][case_name] for report_scores in run_reports]
                replay_variances.append(self._sample_variance(replay_scores))
                run_means_by_case[case_name].append(self._mean(replay_scores))

        judge_variance = self._mean(replay_variances)
        observed_run_variance = self._mean(
            [self._sample_variance(run_means) for run_means in run_means_by_case.values()]
        )
        agent_variance_raw = observed_run_variance - judge_variance / replay_count
        agent_variance = self._truncate_variance(agent_variance_raw)

        case_means = [self._mean(run_means_by_case[case_name]) for case_name in case_names]
        observed_case_variance = self._sample_variance(case_means)
        case_variance_raw = (
            observed_case_variance - agent_variance_raw / run_count - judge_variance / (run_count * replay_count)
        )
        case_variance = self._truncate_variance(case_variance_raw)

        denominator = case_variance + agent_variance / run_count + judge_variance / (run_count * replay_count)
        if denominator <= _EPSILON:
            return 0.0
        return case_variance / denominator

    def _score_parsed_reports(
        self,
        parsed: list[list[dict[str, dict[str, float]]]],
        evaluator_names: list[str],
        case_names: list[str],
    ) -> float:
        evaluator_scores: dict[str, float] = {}
        for evaluator_name in evaluator_names:
            case_scores = []
            for case_name in case_names:
                values = [
                    report_scores[evaluator_name][case_name] for run_reports in parsed for report_scores in run_reports
                ]
                case_scores.append(self._mean(values))
            evaluator_scores[evaluator_name] = self._mean(case_scores)

        return sum(self._weights[name] * evaluator_scores[name] for name in evaluator_names)

    @staticmethod
    def _sample_variance(values: list[float]) -> float:
        mean = Calibrator._mean(values)
        return sum((value - mean) ** 2 for value in values) / (len(values) - 1)

    @staticmethod
    def _mean(values: list[float]) -> float:
        return sum(values) / len(values)

    @staticmethod
    def _truncate_variance(value: float) -> float:
        return 0.0 if value <= _EPSILON else value
