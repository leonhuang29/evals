"""Experimental utilities for comparing evaluation reports."""

from .compare import PairedComparisonResult, PairedComparisonVerdict, compare_paired
from .pairing import PairedScore, PairedTrialScore, aggregate_trial_pairs, pair_report_trials, pair_reports
from .summary import EvaluatorSummary, EvaluatorVerdict, summarize_pairs

__all__ = [
    "EvaluatorSummary",
    "EvaluatorVerdict",
    "PairedScore",
    "PairedComparisonResult",
    "PairedComparisonVerdict",
    "PairedTrialScore",
    "aggregate_trial_pairs",
    "compare_paired",
    "pair_reports",
    "pair_report_trials",
    "summarize_pairs",
]
