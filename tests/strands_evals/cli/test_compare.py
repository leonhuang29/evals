"""Tests for `strands-evals compare`."""

import json
from pathlib import Path

from strands_evals.cli.main import main
from strands_evals.types.evaluation_report import EvaluationReport


def _write_report(path: Path, delta: float) -> None:
    scores = [0.2 + index * 0.05 + delta for index in range(6)]
    report = EvaluationReport(
        overall_score=sum(scores) / len(scores),
        scores=scores,
        cases=[
            {
                "name": f"case-{index}",
                "input": f"input-{index}",
                "evaluator": "correctness",
            }
            for index in range(6)
        ],
        test_passes=[True] * 6,
        detailed_results=[[] for _ in scores],
    )
    path.write_text(report.model_dump_json(), encoding="utf-8")


def test_compare_json_output(tmp_path: Path, capsys):
    baseline = tmp_path / "baseline.json"
    candidate = tmp_path / "candidate.json"
    _write_report(baseline, 0.0)
    _write_report(candidate, 0.1)

    exit_code = main(
        [
            "--json",
            "compare",
            "--baseline",
            str(baseline),
            "--candidate",
            str(candidate),
            "--bootstrap-samples",
            "100",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["verdict"] == "improved"
    assert payload["trial_count"] == 1
    assert payload["evaluator_summaries"][0]["evaluator"] == "correctness"


def test_compare_multiple_trials_and_exclusion(tmp_path: Path, capsys):
    baseline_0 = tmp_path / "baseline-0.json"
    baseline_1 = tmp_path / "baseline-1.json"
    candidate_0 = tmp_path / "candidate-0.json"
    candidate_1 = tmp_path / "candidate-1.json"
    _write_report(baseline_0, 0.0)
    _write_report(baseline_1, 0.02)
    _write_report(candidate_0, 0.1)
    _write_report(candidate_1, -0.2)

    exit_code = main(
        [
            "--json",
            "compare",
            "--baseline",
            str(baseline_0),
            "--baseline",
            str(baseline_1),
            "--candidate",
            str(candidate_0),
            "--candidate",
            str(candidate_1),
            "--corrupted-trial",
            "1",
            "--bootstrap-samples",
            "100",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["verdict"] == "improved"
    assert payload["trial_count"] == 1
    assert payload["corrupted_trial_indices"] == [1]


def test_compare_rich_output(tmp_path: Path, capsys):
    baseline = tmp_path / "baseline.json"
    candidate = tmp_path / "candidate.json"
    _write_report(baseline, 0.0)
    _write_report(candidate, 0.1)

    exit_code = main(
        [
            "--rich",
            "compare",
            "--baseline",
            str(baseline),
            "--candidate",
            str(candidate),
            "--bootstrap-samples",
            "100",
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Comparison: improved" in output
    assert "correctness" in output


def test_compare_output_file_is_json(tmp_path: Path):
    baseline = tmp_path / "baseline.json"
    candidate = tmp_path / "candidate.json"
    output = tmp_path / "comparison.json"
    _write_report(baseline, 0.0)
    _write_report(candidate, 0.1)

    exit_code = main(
        [
            "--rich",
            "compare",
            "--baseline",
            str(baseline),
            "--candidate",
            str(candidate),
            "--bootstrap-samples",
            "100",
            "--output",
            str(output),
        ]
    )

    assert exit_code == 0
    assert json.loads(output.read_text(encoding="utf-8"))["verdict"] == "improved"
