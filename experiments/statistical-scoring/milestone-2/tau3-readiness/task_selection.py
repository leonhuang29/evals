"""Shared task ordering for Tau3 calibration collection and analysis."""

from typing import Any


def ordered_task_ids(
    manifest: dict[str, Any],
    *,
    stage: str,
    domain_order: list[str],
) -> list[str]:
    """Return stage task IDs interleaved across domains.

    The manifest preserves the deterministic rank within each domain. Round
    robin ordering makes every collection checkpoint approximately balanced
    instead of completing one entire domain before starting the next.
    """
    tasks_by_domain: dict[str, list[str]] = {domain: [] for domain in domain_order}
    for task in manifest["tasks"]:
        if stage not in task["stages"]:
            continue
        domain = str(task["domain"])
        if domain not in tasks_by_domain:
            raise ValueError(f"manifest contains an unexpected domain: {domain}")
        tasks_by_domain[domain].append(str(task["harbor_task_id"]))

    lengths = {len(task_ids) for task_ids in tasks_by_domain.values()}
    if len(lengths) != 1:
        raise ValueError(
            f"{stage} task allocation must be balanced across domains: "
            f"{ {domain: len(task_ids) for domain, task_ids in tasks_by_domain.items()} }"
        )

    tasks_per_domain = lengths.pop()
    return [tasks_by_domain[domain][task_index] for task_index in range(tasks_per_domain) for domain in domain_order]
