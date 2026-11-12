"""Deterministic pairing for baseline and candidate evaluation reports."""

import hashlib
import json
from collections import defaultdict
from statistics import fmean
from typing import Any, Collection, Sequence

from pydantic import BaseModel, Field

from ...types.evaluation_report import EvaluationReport


class PairedScore(BaseModel):
    """One evaluator score matched between baseline and candidate reports.

    Attributes:
        case_id: Stable identifier derived from the case name or input.
        evaluator: Name of the evaluator that produced both scores.
        baseline_score: Score produced by the baseline.
        candidate_score: Score produced by the candidate.
        delta: Candidate score minus baseline score.
        trial_count: Number of trials represented by the scores.
    """

    case_id: str
    evaluator: str
    baseline_score: float
    candidate_score: float
    delta: float
    trial_count: int = Field(default=1, ge=1)


class PairedTrialScore(PairedScore):
    """One paired evaluator score from a specific trial.

    Attributes:
        trial_index: Zero-based position of the trial in the report sequences.
    """

    trial_index: int


def pair_reports(baseline: EvaluationReport, candidate: EvaluationReport) -> list[PairedScore]:
    """Match comparable evaluator scores from two reports.

    Cases are paired by exact case name when one is present. An unnamed case is
    paired by a deterministic hash of its input. Evaluator names must also
    match. Row order, generated session IDs, and task outputs do not affect
    pairing.

    Rows that are not applicable in both reports are omitted. A mismatch in
    applicability is rejected because the two scores do not represent the same
    measurement.

    Args:
        baseline: Evaluation report produced by the existing configuration.
        candidate: Evaluation report produced by the changed configuration.

    Returns:
        The matched score rows and their candidate-minus-baseline deltas.

    Raises:
        ValueError: If either report is malformed, contains ambiguous rows, or
            cannot be paired exactly with the other report.
    """

    baseline_rows = _index_report(baseline, "baseline")
    candidate_rows = _index_report(candidate, "candidate")

    baseline_keys = set(baseline_rows)
    candidate_keys = set(candidate_rows)
    if baseline_keys != candidate_keys:
        raise ValueError(
            "reports do not contain the same case/evaluator rows: "
            f"baseline_only={sorted(baseline_keys - candidate_keys)}, "
            f"candidate_only={sorted(candidate_keys - baseline_keys)}"
        )

    pairs: list[PairedScore] = []
    for key in sorted(baseline_keys):
        baseline_index = baseline_rows[key]
        candidate_index = candidate_rows[key]
        baseline_case = baseline.cases[baseline_index]
        candidate_case = candidate.cases[candidate_index]
        evaluator, case_id = key

        if _canonical_json(baseline_case["input"]) != _canonical_json(candidate_case["input"]):
            raise ValueError(f"case inputs differ between reports: case_id={case_id!r}, evaluator={evaluator!r}")

        baseline_details = (
            baseline.detailed_results[baseline_index] if baseline_index < len(baseline.detailed_results) else []
        )
        candidate_details = (
            candidate.detailed_results[candidate_index] if candidate_index < len(candidate.detailed_results) else []
        )
        baseline_applicable = EvaluationReport.is_applicable(baseline_details)
        candidate_applicable = EvaluationReport.is_applicable(candidate_details)
        if baseline_applicable != candidate_applicable:
            raise ValueError(
                f"case applicability differs between reports: case_id={case_id!r}, evaluator={evaluator!r}"
            )
        if not baseline_applicable:
            continue

        baseline_score = baseline.scores[baseline_index]
        candidate_score = candidate.scores[candidate_index]
        pairs.append(
            PairedScore(
                case_id=case_id,
                evaluator=evaluator,
                baseline_score=baseline_score,
                candidate_score=candidate_score,
                delta=candidate_score - baseline_score,
            )
        )

    return pairs


def pair_report_trials(
    baseline_reports: Sequence[EvaluationReport],
    candidate_reports: Sequence[EvaluationReport],
) -> list[PairedTrialScore]:
    """Pair corresponding baseline and candidate reports by trial index.

    Every trial must contain the same case/evaluator inputs and applicability
    pattern. The returned rows retain their trial index so callers can inspect
    individual runs before aggregating them.

    Args:
        baseline_reports: Baseline reports ordered by trial.
        candidate_reports: Candidate reports ordered by trial.

    Returns:
        Paired evaluator scores from every trial.

    Raises:
        ValueError: If no trials are supplied, the trial counts differ, or the
            reports are not comparable across trials.
    """

    if not baseline_reports or not candidate_reports:
        raise ValueError("baseline_reports and candidate_reports must contain at least one trial")
    if len(baseline_reports) != len(candidate_reports):
        raise ValueError(
            "baseline_reports and candidate_reports must contain the same number of trials: "
            f"baseline={len(baseline_reports)}, candidate={len(candidate_reports)}"
        )

    reference_inputs: dict[tuple[str, str], str] | None = None
    reference_pair_keys: set[tuple[str, str]] | None = None
    trial_pairs: list[PairedTrialScore] = []
    for trial_index, (baseline, candidate) in enumerate(zip(baseline_reports, candidate_reports, strict=True)):
        pairs = pair_reports(baseline, candidate)
        input_signatures = _input_signatures(baseline, f"baseline trial {trial_index}")
        pair_keys = {(pair.evaluator, pair.case_id) for pair in pairs}

        if reference_inputs is None:
            reference_inputs = input_signatures
            reference_pair_keys = pair_keys
        else:
            if input_signatures != reference_inputs:
                raise ValueError(
                    f"trial reports do not contain the same case/evaluator inputs: trial_index={trial_index}"
                )
            if pair_keys != reference_pair_keys:
                raise ValueError(
                    f"trial reports do not contain the same applicable case/evaluator rows: trial_index={trial_index}"
                )

        trial_pairs.extend(PairedTrialScore(**pair.model_dump(), trial_index=trial_index) for pair in pairs)

    return sorted(trial_pairs, key=lambda pair: (pair.evaluator, pair.case_id, pair.trial_index))


def aggregate_trial_pairs(
    pairs: Sequence[PairedTrialScore],
    *,
    corrupted_trial_indices: Collection[int] = (),
) -> list[PairedScore]:
    """Average repeated trial scores within each case and evaluator.

    Each case/evaluator group must contain exactly one row for every observed
    trial index that was not explicitly marked as corrupted. Aggregating before
    statistical comparison keeps repeated agent runs from being treated as
    independent cases. Corruption is never inferred from a low score or failed
    evaluation because those may represent genuine agent behavior.

    Args:
        pairs: Trial-indexed scores returned by `pair_report_trials`.
        corrupted_trial_indices: Trial indices to remove uniformly from every
            case and evaluator before aggregation.

    Returns:
        One averaged paired score per case and evaluator.

    Raises:
        ValueError: If a corrupted trial index is unknown, no usable trials
            remain, a trial row is duplicated, or a case/evaluator group is
            missing an observed usable trial.
    """

    if not pairs:
        return []

    observed_trial_indices = {pair.trial_index for pair in pairs}
    corrupted = set(corrupted_trial_indices)
    unknown_corrupted = corrupted - observed_trial_indices
    if unknown_corrupted:
        raise ValueError(f"corrupted_trial_indices contain unknown trials: {sorted(unknown_corrupted)}")

    trial_indices = observed_trial_indices - corrupted
    if not trial_indices:
        raise ValueError("no usable trials remain after removing corrupted trials")

    grouped: defaultdict[tuple[str, str], list[PairedTrialScore]] = defaultdict(list)
    seen: set[tuple[int, str, str]] = set()
    for pair in pairs:
        row_key = (pair.trial_index, pair.evaluator, pair.case_id)
        if row_key in seen:
            raise ValueError(
                "pairs contain duplicate trial/case/evaluator row: "
                f"trial_index={pair.trial_index}, case_id={pair.case_id!r}, evaluator={pair.evaluator!r}"
            )
        seen.add(row_key)
        if pair.trial_index not in corrupted:
            grouped[(pair.evaluator, pair.case_id)].append(pair)

    aggregated: list[PairedScore] = []
    for evaluator, case_id in sorted(grouped):
        case_pairs = grouped[(evaluator, case_id)]
        case_trial_indices = {pair.trial_index for pair in case_pairs}
        if case_trial_indices != trial_indices:
            raise ValueError(
                "case/evaluator group does not contain every trial: "
                f"case_id={case_id!r}, evaluator={evaluator!r}, "
                f"expected={sorted(trial_indices)}, actual={sorted(case_trial_indices)}"
            )

        baseline_score = fmean(pair.baseline_score for pair in case_pairs)
        candidate_score = fmean(pair.candidate_score for pair in case_pairs)
        aggregated.append(
            PairedScore(
                case_id=case_id,
                evaluator=evaluator,
                baseline_score=baseline_score,
                candidate_score=candidate_score,
                delta=candidate_score - baseline_score,
                trial_count=len(trial_indices),
            )
        )

    return aggregated


def _index_report(report: EvaluationReport, report_name: str) -> dict[tuple[str, str], int]:
    if len(report.cases) != len(report.scores):
        raise ValueError(f"{report_name} report has {len(report.cases)} cases but {len(report.scores)} scores")

    rows: dict[tuple[str, str], int] = {}
    for index, case in enumerate(report.cases):
        evaluator = case.get("evaluator")
        if not isinstance(evaluator, str) or not evaluator.strip():
            raise ValueError(f"{report_name} report row {index} is missing a non-empty evaluator name")

        if "input" not in case:
            raise ValueError(f"{report_name} report row {index} is missing its case input")

        case_id = _case_id(case, report_name, index)
        key = (evaluator, case_id)
        if key in rows:
            raise ValueError(
                f"{report_name} report contains duplicate case/evaluator row: "
                f"case_id={case_id!r}, evaluator={evaluator!r}"
            )

        rows[key] = index

    return rows


def _input_signatures(report: EvaluationReport, report_name: str) -> dict[tuple[str, str], str]:
    rows = _index_report(report, report_name)
    return {key: _canonical_json(report.cases[index]["input"]) for key, index in rows.items()}


def _case_id(case: dict, report_name: str, index: int) -> str:
    name = case.get("name")
    if name is not None and not isinstance(name, str):
        raise ValueError(f"{report_name} report row {index} has a non-string case name")
    if isinstance(name, str) and name.strip():
        return name.strip()

    input_signature = _canonical_json(case["input"])
    digest = hashlib.sha256(input_signature.encode("utf-8")).hexdigest()
    return f"input:{digest}"


def _canonical_json(value: Any) -> str:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    except (TypeError, ValueError) as error:
        raise ValueError("case input must be JSON-serializable") from error
