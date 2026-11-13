"""`strands-evals compare` — statistically compare paired evaluation reports."""

from __future__ import annotations

import argparse
from pathlib import Path

from rich.console import Console
from rich.table import Table

from ...experimental.comparison import PairedComparisonResult, compare_paired
from ...types.evaluation_report import EvaluationReport
from .._common import EXIT_OK, resolve_format
from .._io import write_text_output


def _load_reports(paths: list[str]) -> list[EvaluationReport]:
    return [EvaluationReport.model_validate_json(Path(path).expanduser().read_text(encoding="utf-8")) for path in paths]


def _render_result(result: PairedComparisonResult) -> None:
    console = Console()
    table = Table(title=f"Comparison: {result.verdict.replace('_', ' ')}")
    table.add_column("Evaluator", no_wrap=True)
    table.add_column("N", justify="right")
    table.add_column("Trials", justify="right")
    table.add_column("Delta", justify="right")
    table.add_column("CI", justify="right")
    table.add_column("Adj. p", justify="right")
    table.add_column("Verdict")

    for summary in result.evaluator_summaries:
        interval = (
            f"[{summary.confidence_lower:.4f}, {summary.confidence_upper:.4f}]"
            if summary.confidence_lower is not None and summary.confidence_upper is not None
            else "N/A"
        )
        adjusted_p = f"{summary.adjusted_p_value:.4g}" if summary.adjusted_p_value is not None else "N/A"
        table.add_row(
            summary.evaluator,
            str(summary.case_count),
            str(summary.trial_count),
            f"{summary.mean_delta:+.4f}",
            interval,
            adjusted_p,
            summary.verdict.replace("_", " "),
        )

    console.print(table)


def _run(args: argparse.Namespace) -> int:
    result = compare_paired(
        _load_reports(args.baseline),
        _load_reports(args.candidate),
        corrupted_trial_indices=args.corrupted_trial,
        confidence_level=args.confidence_level,
        bootstrap_samples=args.bootstrap_samples,
        seed=args.seed,
        minimum_effect=args.minimum_effect,
    )

    if args.output is not None or resolve_format(args) == "json":
        write_text_output(result.model_dump_json(indent=2), args.output)
    else:
        _render_result(result)

    return EXIT_OK


def add_subparser(
    subparsers: argparse._SubParsersAction,
    parent: argparse.ArgumentParser,
) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        "compare",
        parents=[parent],
        help="statistically compare paired evaluation reports",
        description=(
            "Compare baseline and candidate EvaluationReport JSON files. Repeat "
            "--baseline and --candidate in matching trial order for N-trial comparison."
        ),
    )
    parser.add_argument(
        "--baseline",
        action="append",
        required=True,
        metavar="REPORT",
        help="baseline EvaluationReport JSON file; repeat once per trial",
    )
    parser.add_argument(
        "--candidate",
        action="append",
        required=True,
        metavar="REPORT",
        help="candidate EvaluationReport JSON file; repeat once per trial",
    )
    parser.add_argument(
        "--corrupted-trial",
        action="append",
        default=[],
        type=int,
        metavar="INDEX",
        help="zero-based trial index to exclude from both sides; may be repeated",
    )
    parser.add_argument(
        "--confidence-level",
        default=0.95,
        type=float,
        help="bootstrap confidence interval coverage (default: 0.95)",
    )
    parser.add_argument(
        "--bootstrap-samples",
        default=2_000,
        type=int,
        help="number of case-bootstrap resamples (default: 2000)",
    )
    parser.add_argument(
        "--seed",
        default=0,
        type=int,
        help="bootstrap random seed (default: 0)",
    )
    parser.add_argument(
        "--minimum-effect",
        default=0.0,
        type=float,
        help="smallest absolute score change eligible for a directional verdict",
    )
    parser.add_argument(
        "-o",
        "--output",
        default=None,
        metavar="PATH",
        help="write comparison JSON to PATH instead of stdout",
    )
    parser.set_defaults(func=_run)
    return parser
