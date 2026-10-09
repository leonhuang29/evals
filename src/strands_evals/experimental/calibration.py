"""Experimental reliability-weighted evaluation calibration."""

import asyncio
import math
import random
from collections.abc import Callable

from typing_extensions import Any, Generic, Literal, Self

from ..case import Case
from ..experiment import Experiment
from ..types.evaluation import EvaluationData, InputT, OutputT
from ..types.evaluation_report import EvaluationReport

_EPSILON = 1e-15

WeightingMethod = Literal["equal", "reliability", "inverse_step", "inverse_sqrt_step"]
_WEIGHTING_METHODS: tuple[WeightingMethod, ...] = (
    "equal",
    "reliability",
    "inverse_step",
    "inverse_sqrt_step",
)
_BootstrapSummary = dict[str, float | int | None]
_ParsedReports = list[list[dict[str, dict[str, float]]]]


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

    def __init__(
        self,
        step_sizes: dict[str, float],
        weighting_method: WeightingMethod = "inverse_sqrt_step",
    ) -> None:
        """Initialize a calibrator with declared evaluator score steps.

        Args:
            step_sizes: Mapping from evaluator instance name to its smallest
                meaningful score increment.
            weighting_method: Candidate rule used for the active weight vector.

        Raises:
            ValueError: If no evaluators are provided or a step is not finite
                and greater than zero, or if the weighting method is unknown.
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
        if weighting_method not in _WEIGHTING_METHODS:
            raise ValueError(f"unknown weighting method: {weighting_method!r}")

        self._step_sizes = {name: float(step) for name, step in step_sizes.items()}
        self._weighting_method = weighting_method
        self._weights = self._equal_weights()
        self._variance_components: dict[str, dict[str, float]] = {}
        self._reliabilities: dict[str, float] = {}
        self._candidate_weights = self._initial_candidate_weights()
        self._bootstrap_replicates = 0
        self._bootstrap_seed: int | None = None
        self._reliability_intervals: dict[str, _BootstrapSummary] = {}
        self._candidate_weight_intervals: dict[WeightingMethod, dict[str, _BootstrapSummary]] = {}
        self._composite_score_intervals: dict[WeightingMethod, _BootstrapSummary] = {}
        self._is_fitted = False

    @property
    def weighting_method(self) -> WeightingMethod:
        """Return the candidate rule used for the active weight vector."""
        return self._weighting_method

    @property
    def weights(self) -> dict[str, float]:
        """Return a copy of the current evaluator weight vector."""
        return dict(self._weights)

    @property
    def variance_components(self) -> dict[str, dict[str, float]]:
        """Return corrected non-negative variance estimates by evaluator."""
        return {name: dict(components) for name, components in self._variance_components.items()}

    @property
    def reliabilities(self) -> dict[str, float]:
        """Return current-design reliability estimates by evaluator."""
        return dict(self._reliabilities)

    @property
    def candidate_weights(self) -> dict[WeightingMethod, dict[str, float] | None]:
        """Return weight vectors for every candidate weighting rule."""
        return {
            method: None if weights is None else dict(weights) for method, weights in self._candidate_weights.items()
        }

    @property
    def bootstrap_replicates(self) -> int:
        """Return the number of bootstrap replicates from the latest fit."""
        return self._bootstrap_replicates

    @property
    def bootstrap_seed(self) -> int | None:
        """Return the random seed from the latest bootstrap run."""
        return self._bootstrap_seed

    @property
    def reliability_intervals(self) -> dict[str, dict[str, float | int | None]]:
        """Return bootstrap summaries for evaluator reliability."""
        return {name: dict(summary) for name, summary in self._reliability_intervals.items()}

    @property
    def candidate_weight_intervals(
        self,
    ) -> dict[WeightingMethod, dict[str, dict[str, float | int | None]]]:
        """Return bootstrap summaries for every candidate weight vector."""
        return {
            method: {name: dict(summary) for name, summary in intervals.items()}
            for method, intervals in self._candidate_weight_intervals.items()
        }

    @property
    def composite_score_intervals(self) -> dict[WeightingMethod, dict[str, float | int | None]]:
        """Return bootstrap summaries for calibration-suite composite scores."""
        return {method: dict(summary) for method, summary in self._composite_score_intervals.items()}

    @property
    def is_fitted(self) -> bool:
        """Whether fitting found measurable evaluator reliability signal."""
        return self._is_fitted

    def run_evaluations(
        self,
        experiment: Experiment[InputT, OutputT],
        task: Callable[[Case[InputT, OutputT]], OutputT | dict[str, Any]],
        *,
        agent_runs: int,
        judge_replays: int,
        max_workers: int = 1,
        bootstrap_replicates: int = 0,
        bootstrap_seed: int = 0,
    ) -> float:
        """Run repeated evaluations, fit weights, and return a suite score.

        Args:
            experiment: Existing experiment containing cases and evaluators.
            task: Task function evaluated by the experiment.
            agent_runs: Number of independent task executions per case.
            judge_replays: Number of evaluator passes over each fixed output.
            max_workers: Maximum parallel case workers used by the experiment.
            bootstrap_replicates: Number of hierarchical bootstrap samples.
                Zero disables bootstrap uncertainty estimates.
            bootstrap_seed: Random seed used for reproducible resampling.

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
                bootstrap_replicates=bootstrap_replicates,
                bootstrap_seed=bootstrap_seed,
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
        bootstrap_replicates: int = 0,
        bootstrap_seed: int = 0,
    ) -> float:
        """Asynchronously collect repeated reports, fit weights, and score them.

        Args:
            experiment: Existing experiment containing cases and evaluators.
            task: Synchronous or asynchronous task function.
            agent_runs: Number of independent task executions per case.
            judge_replays: Number of evaluator passes over each fixed output.
            max_workers: Maximum parallel case workers used by the experiment.
            bootstrap_replicates: Number of hierarchical bootstrap samples.
                Zero disables bootstrap uncertainty estimates.
            bootstrap_seed: Random seed used for reproducible resampling.

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

        self.fit(
            reports_by_run,
            bootstrap_replicates=bootstrap_replicates,
            bootstrap_seed=bootstrap_seed,
        )
        parsed, evaluator_names, case_names = self._parse_reports(reports_by_run)
        return self._score_parsed_reports(parsed, evaluator_names, case_names)

    def fit(
        self,
        reports_by_run: list[list[EvaluationReport]],
        *,
        bootstrap_replicates: int = 0,
        bootstrap_seed: int = 0,
    ) -> Self:
        """Learn evaluator weights from repeated evaluation reports.

        The outer list represents independent agent runs. Each inner list
        contains repeated judge evaluations of that run's fixed outputs.

        Args:
            reports_by_run: Reports grouped by agent run and judge replay.
            bootstrap_replicates: Number of hierarchical bootstrap samples.
                Zero disables bootstrap uncertainty estimates.
            bootstrap_seed: Random seed used for reproducible resampling.

        Returns:
            This calibrator with its weight vector updated.

        Raises:
            ValueError: If the report hierarchy is incomplete, unbalanced, or
                incompatible with the configured evaluator names, or bootstrap
                options are invalid.
        """
        self._validate_bootstrap_options(bootstrap_replicates, bootstrap_seed)
        parsed, evaluator_names, case_names = self._parse_reports(reports_by_run)
        run_count = len(parsed)
        replay_count = len(parsed[0])
        self._validate_repetition_counts(run_count, replay_count)
        if len(case_names) < 2:
            raise ValueError("calibration requires at least two cases")

        self._weights = self._equal_weights()
        self._variance_components = {}
        self._reliabilities = {}
        self._candidate_weights = self._initial_candidate_weights()
        self._reset_bootstrap()
        self._is_fitted = False

        for evaluator_name in evaluator_names:
            variance_components, reliability = self._estimate_statistics(
                parsed,
                evaluator_name,
                case_names,
                run_count,
                replay_count,
            )
            self._variance_components[evaluator_name] = variance_components
            self._reliabilities[evaluator_name] = reliability

        self._candidate_weights = {
            method: self._compute_weights(method, evaluator_names, self._reliabilities) for method in _WEIGHTING_METHODS
        }
        selected_weights = self._candidate_weights[self._weighting_method]
        if selected_weights is not None:
            self._weights = selected_weights

        self._is_fitted = any(reliability > _EPSILON for reliability in self._reliabilities.values())
        if bootstrap_replicates:
            self._run_bootstrap(
                parsed,
                evaluator_names,
                case_names,
                bootstrap_replicates,
                bootstrap_seed,
            )
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

    def score_candidates(self, report: EvaluationReport) -> dict[WeightingMethod, float | None]:
        """Score one report under every candidate weighting rule.

        A reliability-based score is `None` when the calibration data contained
        no measurable reliability signal for any evaluator.

        Args:
            report: Flattened report containing one row per case and evaluator.

        Returns:
            Composite score for each candidate weighting rule.
        """
        scores = self._extract_report_scores(report)
        evaluator_names = sorted(scores)
        self._validate_evaluator_names(set(evaluator_names))
        evaluator_scores = {
            evaluator_name: self._mean(list(scores[evaluator_name].values())) for evaluator_name in evaluator_names
        }

        candidate_scores: dict[WeightingMethod, float | None] = {}
        for method in _WEIGHTING_METHODS:
            weights = self._candidate_weights[method]
            candidate_scores[method] = (
                None if weights is None else sum(weights[name] * evaluator_scores[name] for name in evaluator_names)
            )
        return candidate_scores

    def _equal_weights(self) -> dict[str, float]:
        weight = 1.0 / len(self._step_sizes)
        return {name: weight for name in self._step_sizes}

    def _initial_candidate_weights(self) -> dict[WeightingMethod, dict[str, float] | None]:
        return {
            "equal": self._equal_weights(),
            "reliability": None,
            "inverse_step": None,
            "inverse_sqrt_step": None,
        }

    def _compute_weights(
        self,
        method: WeightingMethod,
        evaluator_names: list[str],
        reliabilities: dict[str, float],
    ) -> dict[str, float] | None:
        if method == "equal":
            return self._equal_weights()

        unnormalized: dict[str, float] = {}
        for evaluator_name in evaluator_names:
            reliability = reliabilities[evaluator_name]
            step = self._step_sizes[evaluator_name]
            if method == "reliability":
                value = reliability
            elif method == "inverse_step":
                value = reliability / step
            else:
                value = reliability / math.sqrt(step)
            unnormalized[evaluator_name] = value

        total = sum(unnormalized.values())
        if total <= _EPSILON:
            return None
        return {name: value / total for name, value in unnormalized.items()}

    def _reset_bootstrap(self) -> None:
        self._bootstrap_replicates = 0
        self._bootstrap_seed = None
        self._reliability_intervals = {}
        self._candidate_weight_intervals = {}
        self._composite_score_intervals = {}

    @staticmethod
    def _validate_bootstrap_options(replicates: int, seed: int) -> None:
        if not isinstance(replicates, int) or isinstance(replicates, bool) or replicates < 0 or replicates == 1:
            raise ValueError(f"bootstrap_replicates must be 0 or >= 2, got {replicates}")
        if not isinstance(seed, int) or isinstance(seed, bool):
            raise ValueError(f"bootstrap_seed must be an integer, got {seed!r}")

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
    ) -> tuple[_ParsedReports, list[str], list[str]]:
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

    def _estimate_statistics(
        self,
        parsed: _ParsedReports,
        evaluator_name: str,
        case_names: list[str],
        run_count: int,
        replay_count: int,
    ) -> tuple[dict[str, float], float]:
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
        reliability = 0.0 if denominator <= _EPSILON else case_variance / denominator
        variance_components = {
            "judge": judge_variance,
            "agent": agent_variance,
            "case": case_variance,
        }
        return variance_components, reliability

    def _score_parsed_reports(
        self,
        parsed: _ParsedReports,
        evaluator_names: list[str],
        case_names: list[str],
    ) -> float:
        evaluator_scores = self._evaluator_scores(parsed, evaluator_names, case_names)
        return self._weighted_score(evaluator_scores, self._weights)

    def _evaluator_scores(
        self,
        parsed: _ParsedReports,
        evaluator_names: list[str],
        case_names: list[str],
    ) -> dict[str, float]:
        evaluator_scores: dict[str, float] = {}
        for evaluator_name in evaluator_names:
            case_scores = []
            for case_name in case_names:
                values = [
                    report_scores[evaluator_name][case_name] for run_reports in parsed for report_scores in run_reports
                ]
                case_scores.append(self._mean(values))
            evaluator_scores[evaluator_name] = self._mean(case_scores)
        return evaluator_scores

    @staticmethod
    def _weighted_score(evaluator_scores: dict[str, float], weights: dict[str, float]) -> float:
        return sum(weights[name] * evaluator_scores[name] for name in evaluator_scores)

    def _run_bootstrap(
        self,
        parsed: _ParsedReports,
        evaluator_names: list[str],
        case_names: list[str],
        replicates: int,
        seed: int,
    ) -> None:
        rng = random.Random(seed)
        reliability_distributions: dict[str, list[float | None]] = {name: [] for name in evaluator_names}
        weight_distributions: dict[WeightingMethod, dict[str, list[float | None]]] = {
            method: {name: [] for name in evaluator_names} for method in _WEIGHTING_METHODS
        }
        score_distributions: dict[WeightingMethod, list[float | None]] = {method: [] for method in _WEIGHTING_METHODS}

        for _ in range(replicates):
            sampled, sampled_case_names = self._bootstrap_sample(parsed, evaluator_names, case_names, rng)
            sampled_reliabilities: dict[str, float] = {}
            for evaluator_name in evaluator_names:
                _, reliability = self._estimate_statistics(
                    sampled,
                    evaluator_name,
                    sampled_case_names,
                    len(sampled),
                    len(sampled[0]),
                )
                sampled_reliabilities[evaluator_name] = reliability
                reliability_distributions[evaluator_name].append(reliability)

            evaluator_scores = self._evaluator_scores(sampled, evaluator_names, sampled_case_names)
            for method in _WEIGHTING_METHODS:
                weights = self._compute_weights(method, evaluator_names, sampled_reliabilities)
                for evaluator_name in evaluator_names:
                    weight_distributions[method][evaluator_name].append(
                        None if weights is None else weights[evaluator_name]
                    )
                score_distributions[method].append(
                    None if weights is None else self._weighted_score(evaluator_scores, weights)
                )

        self._bootstrap_replicates = replicates
        self._bootstrap_seed = seed
        self._reliability_intervals = {
            name: self._summarize_distribution(values) for name, values in reliability_distributions.items()
        }
        self._candidate_weight_intervals = {
            method: {
                name: self._summarize_distribution(values) for name, values in weight_distributions[method].items()
            }
            for method in _WEIGHTING_METHODS
        }
        self._composite_score_intervals = {
            method: self._summarize_distribution(values) for method, values in score_distributions.items()
        }

    @staticmethod
    def _bootstrap_sample(
        parsed: _ParsedReports,
        evaluator_names: list[str],
        case_names: list[str],
        rng: random.Random,
    ) -> tuple[_ParsedReports, list[str]]:
        run_count = len(parsed)
        replay_count = len(parsed[0])
        sampled: _ParsedReports = [
            [{evaluator_name: {} for evaluator_name in evaluator_names} for _ in range(replay_count)]
            for _ in range(run_count)
        ]
        sampled_case_names: list[str] = []

        for case_slot in range(len(case_names)):
            source_case = rng.choice(case_names)
            sampled_case = f"{source_case}#bootstrap-case-{case_slot}"
            sampled_case_names.append(sampled_case)
            for run_slot in range(run_count):
                source_run = rng.randrange(run_count)
                for replay_slot in range(replay_count):
                    source_replay = rng.randrange(replay_count)
                    source_scores = parsed[source_run][source_replay]
                    for evaluator_name in evaluator_names:
                        sampled[run_slot][replay_slot][evaluator_name][sampled_case] = source_scores[evaluator_name][
                            source_case
                        ]

        return sampled, sampled_case_names

    @staticmethod
    def _summarize_distribution(values: list[float | None]) -> _BootstrapSummary:
        defined = sorted(value for value in values if value is not None and math.isfinite(value))
        if not defined:
            return {
                "mean": None,
                "lower_2_5": None,
                "median": None,
                "upper_97_5": None,
                "defined_replicates": 0,
                "undefined_replicates": len(values),
            }

        return {
            "mean": Calibrator._mean(defined),
            "lower_2_5": Calibrator._percentile(defined, 0.025),
            "median": Calibrator._percentile(defined, 0.5),
            "upper_97_5": Calibrator._percentile(defined, 0.975),
            "defined_replicates": len(defined),
            "undefined_replicates": len(values) - len(defined),
        }

    @staticmethod
    def _percentile(values: list[float], probability: float) -> float:
        if len(values) == 1:
            return values[0]
        position = (len(values) - 1) * probability
        lower_index = math.floor(position)
        upper_index = math.ceil(position)
        if lower_index == upper_index:
            return values[lower_index]
        fraction = position - lower_index
        return values[lower_index] + fraction * (values[upper_index] - values[lower_index])

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
