"""Synthetic checks for the Milestone 1 scoring formulas."""

from __future__ import annotations

import random
import unittest

from scoring_analysis import (
    CaseScores,
    RunScores,
    bootstrap_dataset,
    compute_evaluator_statistics,
    compute_weights,
    interval_summary,
)


def build_single_evaluator_dataset(case_values: list[list[list[float]]]) -> tuple[CaseScores, ...]:
    cases: list[CaseScores] = []
    for case_index, run_values in enumerate(case_values):
        runs: list[RunScores] = []
        for run_index, replay_values in enumerate(run_values):
            runs.append(
                RunScores(
                    run_id=f"case-{case_index}-run-{run_index}",
                    replays=tuple({"evaluator": score} for score in replay_values),
                )
            )
        cases.append(CaseScores(case_id=f"case-{case_index}", runs=tuple(runs)))
    return tuple(cases)


class ScoringAnalysisTests(unittest.TestCase):
    def test_perfect_case_signal_has_reliability_one(self) -> None:
        dataset = build_single_evaluator_dataset(
            [
                [[0.0, 0.0, 0.0], [0.0, 0.0, 0.0]],
                [[0.5, 0.5, 0.5], [0.5, 0.5, 0.5]],
                [[1.0, 1.0, 1.0], [1.0, 1.0, 1.0]],
            ]
        )

        result = compute_evaluator_statistics(dataset, "evaluator")

        self.assertAlmostEqual(result["variance_components"]["judge"], 0.0)
        self.assertAlmostEqual(result["variance_components"]["agent"], 0.0)
        self.assertAlmostEqual(result["variance_components"]["case"], 0.25)
        self.assertAlmostEqual(result["reliability"]["single_measurement"], 1.0)
        self.assertAlmostEqual(result["reliability"]["current_design"], 1.0)
        self.assertAlmostEqual(result["scores"]["suite_mean"], 0.5)

    def test_judge_only_noise_does_not_create_case_signal(self) -> None:
        dataset = build_single_evaluator_dataset(
            [
                [[0.0, 1.0, 0.0], [0.0, 1.0, 0.0]],
                [[0.0, 1.0, 0.0], [0.0, 1.0, 0.0]],
                [[0.0, 1.0, 0.0], [0.0, 1.0, 0.0]],
            ]
        )

        result = compute_evaluator_statistics(dataset, "evaluator")

        self.assertAlmostEqual(result["variance_components"]["judge"], 1.0 / 3.0)
        self.assertLess(result["variance_components"]["agent_raw"], 0.0)
        self.assertAlmostEqual(result["variance_components"]["agent"], 0.0)
        self.assertAlmostEqual(result["variance_components"]["case"], 0.0)
        self.assertAlmostEqual(result["reliability"]["single_measurement"], 0.0)
        self.assertAlmostEqual(result["reliability"]["current_design"], 0.0)

    def test_inverse_sqrt_step_weights_are_normalized(self) -> None:
        statistics_by_evaluator = {
            "coarse": {"reliability": {"current_design": 1.0}},
            "fine": {"reliability": {"current_design": 0.5}},
        }
        registry = {
            "evaluators": {
                "coarse": {"scale": {"declared_step": {"value": 0.5}}},
                "fine": {"scale": {"declared_step": {"value": 0.125}}},
            }
        }

        weights = compute_weights(
            statistics_by_evaluator,
            registry,
            ["coarse", "fine"],
            "inverse_sqrt_step",
        )

        self.assertIsNotNone(weights)
        assert weights is not None
        self.assertAlmostEqual(sum(weights.values()), 1.0)
        self.assertAlmostEqual(weights["coarse"], 0.5)
        self.assertAlmostEqual(weights["fine"], 0.5)

    def test_interval_summary_reports_defined_mean(self) -> None:
        summary = interval_summary([0.0, 0.5, None, 1.0])

        self.assertAlmostEqual(summary["mean"], 0.5)
        self.assertEqual(summary["defined_replicates"], 3)
        self.assertEqual(summary["undefined_replicates"], 1)

    def test_bootstrap_keeps_evaluator_vectors_together(self) -> None:
        dataset = (
            CaseScores(
                case_id="case",
                runs=(
                    RunScores(
                        run_id="run-0",
                        replays=(
                            {"left": 0.0, "right": 1.0},
                            {"left": 0.25, "right": 0.75},
                            {"left": 1.0, "right": 0.0},
                        ),
                    ),
                    RunScores(
                        run_id="run-1",
                        replays=(
                            {"left": 0.5, "right": 0.5},
                            {"left": 0.75, "right": 0.25},
                            {"left": 1.0, "right": 0.0},
                        ),
                    ),
                ),
            ),
        )

        sampled = bootstrap_dataset(dataset, random.Random(7))

        for case in sampled:
            for run in case.runs:
                for replay in run.replays:
                    self.assertAlmostEqual(replay["left"] + replay["right"], 1.0)


if __name__ == "__main__":
    unittest.main()
