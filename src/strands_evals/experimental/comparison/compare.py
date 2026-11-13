"""Public orchestration for statistical evaluation-report comparison."""

from typing import Collection, Literal, Sequence

from pydantic import BaseModel

from ...types.evaluation_report import EvaluationReport
from .pairing import PairedScore, aggregate_trial_pairs, pair_report_trials
from .summary import EvaluatorSummary, summarize_pairs

PairedComparisonVerdict = Literal["improved", "regressed", "tradeoff", "no_clear_change"]


class PairedComparisonResult(BaseModel):
    """Statistical comparison of baseline and candidate evaluation reports.

    Attributes:
        pairs: Trial-averaged scores for each comparable case and evaluator.
        evaluator_summaries: Statistical results grouped by evaluator.
        verdict: Overall direction across evaluator verdicts.
        trial_count: Number of usable trials represented in the result.
        corrupted_trial_indices: Explicitly excluded trial indices.
    """

    pairs: list[PairedScore]
    evaluator_summaries: list[EvaluatorSummary]
    verdict: PairedComparisonVerdict
    trial_count: int
    corrupted_trial_indices: list[int]


def compare_paired(
    baseline: EvaluationReport | Sequence[EvaluationReport],
    candidate: EvaluationReport | Sequence[EvaluationReport],
    *,
    corrupted_trial_indices: Collection[int] = (),
    confidence_level: float = 0.95,
    bootstrap_samples: int = 2_000,
    seed: int = 0,
    minimum_effect: float = 0.0,
) -> PairedComparisonResult:
    """Compare one or more baseline and candidate evaluation reports.

    Report sequences are aligned by position, so trial `k` on the baseline is
    paired with trial `k` on the candidate. Explicitly corrupted trials are
    removed from both sides before repeated scores are averaged within cases.

    Args:
        baseline: One baseline report or an ordered sequence of trial reports.
        candidate: One candidate report or an ordered sequence of trial reports.
        corrupted_trial_indices: Trial indices to exclude from both sides.
        confidence_level: Desired bootstrap confidence interval coverage.
        bootstrap_samples: Number of case-bootstrap resamples.
        seed: Seed used to make bootstrap results reproducible.
        minimum_effect: Smallest absolute score change that can receive a
            directional evaluator verdict.

    Returns:
        Paired case scores, evaluator statistics, and an overall verdict.

    Raises:
        ValueError: If the trial inputs cannot be paired or the comparison
            settings are invalid.
    """

    baseline_reports = _as_reports(baseline)
    candidate_reports = _as_reports(candidate)
    corrupted = set(corrupted_trial_indices)
    unknown_corrupted = corrupted - set(range(len(baseline_reports)))
    if unknown_corrupted:
        raise ValueError(f"corrupted_trial_indices contain unknown trials: {sorted(unknown_corrupted)}")
    if baseline_reports and len(corrupted) == len(baseline_reports):
        raise ValueError("no usable trials remain after removing corrupted trials")

    trial_pairs = pair_report_trials(baseline_reports, candidate_reports)
    pairs = aggregate_trial_pairs(trial_pairs, corrupted_trial_indices=corrupted) if trial_pairs else []
    summaries = summarize_pairs(
        pairs,
        confidence_level=confidence_level,
        bootstrap_samples=bootstrap_samples,
        seed=seed,
        minimum_effect=minimum_effect,
    )
    return PairedComparisonResult(
        pairs=pairs,
        evaluator_summaries=summaries,
        verdict=_comparison_verdict(summaries),
        trial_count=len(baseline_reports) - len(corrupted),
        corrupted_trial_indices=sorted(corrupted),
    )


def _as_reports(report_or_reports: EvaluationReport | Sequence[EvaluationReport]) -> tuple[EvaluationReport, ...]:
    if isinstance(report_or_reports, EvaluationReport):
        return (report_or_reports,)
    return tuple(report_or_reports)


def _comparison_verdict(summaries: Sequence[EvaluatorSummary]) -> PairedComparisonVerdict:
    verdicts = {summary.verdict for summary in summaries}
    if "improved" in verdicts and "regressed" in verdicts:
        return "tradeoff"
    if "regressed" in verdicts:
        return "regressed"
    if "improved" in verdicts:
        return "improved"
    return "no_clear_change"
