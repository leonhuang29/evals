"""Experimental reliability-weighted evaluation calibration."""

import asyncio
import inspect
import math
from collections.abc import Callable

from typing_extensions import Any, Generic, Self

from ..case import Case
from ..experiment import Experiment
from ..types.evaluation import InputT, OutputT
from ..types.evaluation_report import EvaluationReport
from ._calibration import (
    _WEIGHTING_METHODS,
    WeightingMethod,
    _build_calibration_context,
    _CalibrationDataset,
    _collect_repeated_reports,
    _fit_dataset,
    _initial_calibration_state,
    _prepare_calibration_dataset,
    _validate_bootstrap_options,
    _validate_calibration_compatibility,
    _validate_evaluator_names,
    _validate_repetition_counts,
    _weighted_score,
)


class Calibrator(Generic[InputT, OutputT]):
    """Learn and apply reliability-weighted evaluator weights.

    The calibrator is the public facade for collecting repeated evaluations,
    fitting candidate weighting rules, and scoring reports. Statistical data
    preparation and estimation are delegated to private calibration helpers.

    Reports passed to `fit` are grouped first by independent agent run and then
    by judge replay:

    ```python
    calibrator.fit(
        [
            [run_0_replay_0, run_0_replay_1],
            [run_1_replay_0, run_1_replay_1],
        ]
    )
    ```
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
            ValueError: If no evaluators are provided, a step is invalid, or
                the weighting method is unknown.
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
        self._state = _initial_calibration_state(self._step_sizes)

    @property
    def weighting_method(self) -> WeightingMethod:
        """Return the candidate rule used for the active weight vector."""
        return self._weighting_method

    @property
    def weights(self) -> dict[str, float]:
        """Return a copy of the current evaluator weight vector."""
        return dict(self._state.weights)

    @property
    def calibration_design(self) -> dict[str, int] | None:
        """Return the fitted agent-run and judge-replay counts."""
        if self._state.calibration_design is None:
            return None
        agent_runs, judge_replays = self._state.calibration_design
        return {
            "agent_runs": agent_runs,
            "judge_replays": judge_replays,
        }

    @property
    def calibration_context(self) -> dict[str, str] | None:
        """Return the fitted experiment compatibility fingerprint."""
        if self._state.calibration_context is None:
            return None
        return dict(self._state.calibration_context)

    @property
    def variance_components(self) -> dict[str, dict[str, float]]:
        """Return corrected non-negative variance estimates by evaluator."""
        return {name: dict(components) for name, components in self._state.variance_components.items()}

    @property
    def reliabilities(self) -> dict[str, float]:
        """Return current-design reliability estimates by evaluator."""
        return dict(self._state.reliabilities)

    @property
    def candidate_weights(self) -> dict[WeightingMethod, dict[str, float] | None]:
        """Return weight vectors for every candidate weighting rule."""
        return {
            method: None if weights is None else dict(weights)
            for method, weights in self._state.candidate_weights.items()
        }

    @property
    def bootstrap_replicates(self) -> int:
        """Return the number of bootstrap replicates from the latest fit."""
        return 0 if self._state.bootstrap_result is None else self._state.bootstrap_result.replicates

    @property
    def bootstrap_seed(self) -> int | None:
        """Return the random seed from the latest bootstrap run."""
        return None if self._state.bootstrap_result is None else self._state.bootstrap_result.seed

    @property
    def reliability_intervals(self) -> dict[str, dict[str, float | int | None]]:
        """Return bootstrap summaries for evaluator reliability."""
        if self._state.bootstrap_result is None:
            return {}
        return {name: dict(summary) for name, summary in self._state.bootstrap_result.reliability_intervals.items()}

    @property
    def candidate_weight_intervals(
        self,
    ) -> dict[WeightingMethod, dict[str, dict[str, float | int | None]]]:
        """Return bootstrap summaries for every candidate weight vector."""
        if self._state.bootstrap_result is None:
            return {}
        return {
            method: {name: dict(summary) for name, summary in intervals.items()}
            for method, intervals in self._state.bootstrap_result.candidate_weight_intervals.items()
        }

    @property
    def composite_score_intervals(self) -> dict[WeightingMethod, dict[str, float | int | None]]:
        """Return bootstrap summaries for calibration-suite composite scores."""
        if self._state.bootstrap_result is None:
            return {}
        return {
            method: dict(summary) for method, summary in self._state.bootstrap_result.composite_score_intervals.items()
        }

    @property
    def is_fitted(self) -> bool:
        """Whether fitting found measurable evaluator reliability signal."""
        return self._state.is_fitted

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
        if inspect.iscoroutinefunction(task):
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
        _validate_bootstrap_options(bootstrap_replicates, bootstrap_seed)
        _validate_repetition_counts(agent_runs, judge_replays)
        calibration_context = _build_calibration_context(
            experiment.cases,
            experiment.evaluators,
            self._step_sizes,
        )
        _validate_calibration_compatibility(
            expected_design=self._state.calibration_design,
            expected_context=self._state.calibration_context,
            actual_design=(agent_runs, judge_replays),
            actual_context=calibration_context,
            step_sizes=self._step_sizes,
            operation="evaluation",
        )
        if max_workers < 1:
            raise ValueError(f"max_workers must be >= 1, got {max_workers}")
        _validate_evaluator_names(
            {evaluator.get_name() for evaluator in experiment.evaluators},
            set(self._step_sizes),
        )

        reports_by_run = await _collect_repeated_reports(
            experiment,
            task,
            agent_runs=agent_runs,
            judge_replays=judge_replays,
            max_workers=max_workers,
            calibration_context=calibration_context,
        )

        self.fit(
            reports_by_run,
            bootstrap_replicates=bootstrap_replicates,
            bootstrap_seed=bootstrap_seed,
        )
        return self.score(reports_by_run)

    def fit(
        self,
        reports_by_run: list[list[EvaluationReport]],
        *,
        bootstrap_replicates: int = 0,
        bootstrap_seed: int = 0,
    ) -> Self:
        """Learn evaluator weights from repeated evaluation reports.

        Args:
            reports_by_run: Reports grouped by agent run and judge replay.
            bootstrap_replicates: Number of hierarchical bootstrap samples.
                Zero disables bootstrap uncertainty estimates.
            bootstrap_seed: Random seed used for reproducible resampling.

        Returns:
            This calibrator with its weight vector updated.

        Raises:
            ValueError: If reports are incomplete or incompatible, or bootstrap
                options are invalid.
        """
        _validate_bootstrap_options(bootstrap_replicates, bootstrap_seed)
        dataset = _prepare_calibration_dataset(
            reports_by_run,
            configured_evaluators=set(self._step_sizes),
            step_sizes=self._step_sizes,
            expected_design=self._state.calibration_design,
            expected_context=self._state.calibration_context,
            operation="fit",
        )
        self._state = _fit_dataset(
            dataset,
            self._step_sizes,
            self._weighting_method,
            bootstrap_replicates,
            bootstrap_seed,
        )
        return self

    def score(self, reports_by_run: list[list[EvaluationReport]]) -> float:
        """Apply the current weights to a repeated evaluation design.

        Args:
            reports_by_run: Reports grouped by agent run and judge replay.

        Returns:
            Weighted mean of the evaluator-level suite scores.

        Raises:
            ValueError: If the report hierarchy does not match the fitted
                agent-run and judge-replay counts.
        """
        dataset = self._scoring_dataset(reports_by_run)
        return _weighted_score(dataset.evaluator_scores(), self._state.weights)

    def score_candidates(
        self,
        reports_by_run: list[list[EvaluationReport]],
    ) -> dict[WeightingMethod, float | None]:
        """Score a repeated evaluation design under every candidate rule.

        Args:
            reports_by_run: Reports grouped by agent run and judge replay.

        Returns:
            Composite score for each candidate weighting rule.

        Raises:
            ValueError: If the report hierarchy does not match the fitted
                agent-run and judge-replay counts.
        """
        dataset = self._scoring_dataset(reports_by_run)
        evaluator_scores = dataset.evaluator_scores()
        return {
            method: None if weights is None else _weighted_score(evaluator_scores, weights)
            for method, weights in self._state.candidate_weights.items()
        }

    def _scoring_dataset(
        self,
        reports_by_run: list[list[EvaluationReport]],
    ) -> _CalibrationDataset:
        return _prepare_calibration_dataset(
            reports_by_run,
            configured_evaluators=set(self._step_sizes),
            step_sizes=self._step_sizes,
            expected_design=self._state.calibration_design,
            expected_context=self._state.calibration_context,
            operation="scoring",
        )
