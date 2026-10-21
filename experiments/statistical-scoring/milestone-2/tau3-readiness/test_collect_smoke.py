"""Tests for resumable Tau3 collection helpers."""

from collect_smoke import MAX_TRIAL_NAME_LENGTH, _task_ids, _trial_name


def test_trial_name_preserves_short_task_id() -> None:
    assert _trial_name("tau3-airline-2", 1) == "tau3-airline-2-run-1"


def test_trial_name_hashes_overlong_task_id_deterministically() -> None:
    task_id = "tau3-telecom-" + "long-component-" * 20

    first = _trial_name(task_id, 0)
    second = _trial_name(task_id, 0)

    assert first == second
    assert first.startswith("tau3-smoke-")
    assert first.endswith("-run-0")
    assert len(first) <= MAX_TRIAL_NAME_LENGTH
    assert _trial_name(task_id, 1) != first


def test_trial_name_distinguishes_collection_stages() -> None:
    task_id = "tau3-telecom-" + "long-component-" * 20

    assert _trial_name(task_id, 0, "smoke").startswith("tau3-smoke-")
    assert _trial_name(task_id, 0, "main").startswith("tau3-main-")


def test_main_task_shards_are_disjoint_and_complete() -> None:
    task_ids = _task_ids("main")
    first = task_ids[0::2]
    second = task_ids[1::2]

    assert set(first).isdisjoint(second)
    assert set(first) | set(second) == set(task_ids)
