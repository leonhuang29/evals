"""Tests for parallel Tau3 credential network assignment."""

from configure_parallel_networks import NETWORK_SLOTS, configure_task_network


def test_configure_task_network_is_idempotent(tmp_path) -> None:
    task_dir = tmp_path / "task"
    environment_dir = task_dir / "environment"
    environment_dir.mkdir(parents=True)
    (task_dir / "task.toml").write_text(
        'url = "http://169.254.170.23/"\n',
        encoding="utf-8",
    )
    compose_path = environment_dir / "docker-compose.yaml"
    compose_path.write_text(
        "url: http://169.254.170.23/\nipv4_address: 169.254.170.23\n- subnet: 169.254.170.0/24\n",
        encoding="utf-8",
    )

    configure_task_network(task_dir, NETWORK_SLOTS[1])
    configure_task_network(task_dir, NETWORK_SLOTS[1])
    configure_task_network(task_dir, NETWORK_SLOTS[0])

    assert "http://169.254.170.23/" in (task_dir / "task.toml").read_text()
    compose = compose_path.read_text()
    assert "ipv4_address: 169.254.170.23" in compose
    assert "169.254.170.233" not in compose
    assert "- subnet: 169.254.170.16/28" in compose
