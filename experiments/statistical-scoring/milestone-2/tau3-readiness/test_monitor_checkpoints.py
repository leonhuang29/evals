"""Tests for automatic Tau3 checkpoint selection."""

from monitor_checkpoints import _checkpoint_rows


def test_checkpoint_rows_waits_for_every_selected_case() -> None:
    rows = [{"case": "case-0"}, {"case": "case-1"}]

    assert (
        _checkpoint_rows(
            rows,
            checkpoint_cases=["case-0", "case-1"],
            complete_cases={"case-0"},
        )
        is None
    )


def test_checkpoint_rows_excludes_later_cases() -> None:
    rows = [{"case": "case-0"}, {"case": "case-1"}, {"case": "case-2"}]

    assert _checkpoint_rows(
        rows,
        checkpoint_cases=["case-0", "case-1"],
        complete_cases={"case-0", "case-1", "case-2"},
    ) == [{"case": "case-0"}, {"case": "case-1"}]
