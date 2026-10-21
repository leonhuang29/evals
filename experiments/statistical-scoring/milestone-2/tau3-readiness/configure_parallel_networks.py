"""Assign non-overlapping credential networks to two Tau3 task shards."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from task_selection import ordered_task_ids

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "experiment_config.json"
MANIFEST_PATH = BASE_DIR / "task_manifest.json"


@dataclass(frozen=True)
class NetworkSlot:
    """One non-overlapping network using an AWS SDK-approved credential IP."""

    proxy_ip: str
    subnet: str


NETWORK_SLOTS = (
    NetworkSlot(proxy_ip="169.254.170.23", subnet="169.254.170.16/28"),
    NetworkSlot(proxy_ip="169.254.170.2", subnet="169.254.170.0/28"),
)
_KNOWN_PROXY_IPS = tuple(slot.proxy_ip for slot in NETWORK_SLOTS)
_KNOWN_SUBNETS = ("169.254.170.0/24",) + tuple(slot.subnet for slot in NETWORK_SLOTS)


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object at {path}")
    return value


def configure_task_network(task_dir: Path, slot: NetworkSlot) -> None:
    """Rewrite one prepared task to use the selected credential network."""
    task_path = task_dir / "task.toml"
    compose_path = task_dir / "environment/docker-compose.yaml"

    task_config = task_path.read_text(encoding="utf-8")
    compose = compose_path.read_text(encoding="utf-8")
    for proxy_ip in _KNOWN_PROXY_IPS:
        task_config = task_config.replace(
            f"http://{proxy_ip}/",
            f"http://{slot.proxy_ip}/",
        )
        compose = compose.replace(
            f"http://{proxy_ip}/",
            f"http://{slot.proxy_ip}/",
        )
    compose = re.sub(
        r"(?m)^(\s*ipv4_address:\s*)169\.254\.170\.(?:2|23|233)\s*$",
        rf"\g<1>{slot.proxy_ip}",
        compose,
    )
    for subnet in _KNOWN_SUBNETS:
        compose = compose.replace(
            f"- subnet: {subnet}",
            f"- subnet: {slot.subnet}",
        )

    expected_uri = f"http://{slot.proxy_ip}/"
    if expected_uri not in task_config or expected_uri not in compose:
        raise ValueError(f"credential URI was not configured in {task_dir}")
    if f"ipv4_address: {slot.proxy_ip}" not in compose:
        raise ValueError(f"credential proxy IP was not configured in {task_dir}")
    if f"- subnet: {slot.subnet}" not in compose:
        raise ValueError(f"credential subnet was not configured in {task_dir}")

    task_path.write_text(task_config, encoding="utf-8")
    compose_path.write_text(compose, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tasks-dir", type=Path, required=True)
    parser.add_argument("--stage", choices=("smoke", "main"), default="main")
    args = parser.parse_args()

    tasks_dir = args.tasks_dir.expanduser().resolve()
    config = _load_json(CONFIG_PATH)
    manifest = _load_json(MANIFEST_PATH)
    task_ids = ordered_task_ids(
        manifest,
        stage=args.stage,
        domain_order=[str(domain) for domain in config["sampling"]["domains"]],
    )
    for task_index, task_id in enumerate(task_ids):
        configure_task_network(
            tasks_dir / task_id,
            NETWORK_SLOTS[task_index % len(NETWORK_SLOTS)],
        )
    print(f"configured {len(task_ids)} tasks for two parallel network slots")  # noqa: T201


if __name__ == "__main__":
    main()
