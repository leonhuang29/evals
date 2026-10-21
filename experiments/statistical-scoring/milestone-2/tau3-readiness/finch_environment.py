"""Harbor environment adapter backed by Finch."""

import shutil
import subprocess
import sys
from pathlib import Path

from harbor.environments.docker.docker import DockerEnvironment
from harbor.environments.docker.runtime import ContainerRuntime


_COMPOSE_WRAPPER = Path(__file__).with_name("_finch_compose.py")

FINCH_RUNTIME = ContainerRuntime(
    engine=("finch",),
    compose=(sys.executable, str(_COMPOSE_WRAPPER)),
    supports_compose_wait=False,
    supports_compose_cp=True,
    supports_compose_project_directory=True,
)


class FinchEnvironment(DockerEnvironment):
    """Run Harbor's local container workflow through Finch."""

    @classmethod
    def runtime(cls) -> ContainerRuntime:
        """Return the Finch engine and Compose commands used by Harbor."""
        return FINCH_RUNTIME

    @classmethod
    def preflight(cls) -> None:
        """Verify that Finch and its Compose frontend are available."""
        if not shutil.which("finch"):
            raise SystemExit(
                "Finch is not installed or not on PATH. Install Finch and try again."
            )

        commands = (
            (cls._engine_cmd("info"), "Finch VM"),
            (cls.runtime().compose_cmd("version"), "Finch Compose"),
        )
        for command, component in commands:
            try:
                subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    timeout=30,
                    check=True,
                )
            except (
                OSError,
                subprocess.CalledProcessError,
                subprocess.TimeoutExpired,
            ) as exc:
                detail = ""
                if isinstance(exc, subprocess.CalledProcessError):
                    detail = (exc.stderr or exc.stdout or "").strip()
                suffix = f"\nOutput: {detail}" if detail else ""
                raise SystemExit(
                    f"{component} is not responding. Start Finch with "
                    f"'finch vm start' and try again.{suffix}"
                ) from exc
