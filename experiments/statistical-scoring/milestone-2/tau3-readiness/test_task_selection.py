"""Tests for deterministic cross-domain task ordering."""

import pytest
from task_selection import ordered_task_ids


def _manifest(domain_counts: dict[str, int]) -> dict:
    return {
        "tasks": [
            {
                "domain": domain,
                "harbor_task_id": f"{domain}-{index}",
                "stages": ["main"],
            }
            for domain, count in domain_counts.items()
            for index in range(count)
        ]
    }


def test_ordered_task_ids_interleaves_domains() -> None:
    manifest = _manifest({"airline": 2, "retail": 2})

    assert ordered_task_ids(
        manifest,
        stage="main",
        domain_order=["airline", "retail"],
    ) == ["airline-0", "retail-0", "airline-1", "retail-1"]


def test_ordered_task_ids_rejects_unbalanced_domains() -> None:
    manifest = _manifest({"airline": 2, "retail": 1})

    with pytest.raises(ValueError, match="must be balanced"):
        ordered_task_ids(
            manifest,
            stage="main",
            domain_order=["airline", "retail"],
        )
