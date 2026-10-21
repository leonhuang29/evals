"""Translate Harbor's Docker Compose invocation to Finch Compose."""

import os
import subprocess
import sys
import tempfile
from pathlib import Path

_HARBOR_COMPOSE_VARIABLES = {
    "ADA_CREDENTIALS_URL",
    "AWS_CONTAINER_CREDENTIALS_FULL_URI",
    "CONTEXT_DIR",
    "CPUS",
    "EGRESS_CONTROL_INITIAL_ALLOWED_HOSTS",
    "EGRESS_CONTROL_INITIAL_NETWORK_MODE",
    "EGRESS_CONTROL_SIDECAR_IMAGE_NAME",
    "ENV_AGENT_LOGS_PATH",
    "ENV_ARTIFACTS_PATH",
    "ENV_VERIFIER_LOGS_PATH",
    "HARBOR_CONTAINER_NAME",
    "HOST_AGENT_LOGS_PATH",
    "HOST_ARTIFACTS_PATH",
    "HOST_VERIFIER_LOGS_PATH",
    "MAIN_IMAGE_NAME",
    "MEMORY",
    "PREBUILT_IMAGE_NAME",
}


def _remove_unsupported_down_arguments(arguments: list[str]) -> list[str]:
    if "down" not in arguments:
        return arguments

    translated: list[str] = []
    index = 0
    while index < len(arguments):
        argument = arguments[index]
        if argument == "--rmi":
            index += 2
            continue
        if argument.startswith("--rmi="):
            index += 1
            continue
        translated.append(argument)
        index += 1
    return translated


def _interpolate_compose_file(path: Path) -> Path | None:
    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        return None

    interpolated = content
    for name in _HARBOR_COMPOSE_VARIABLES:
        if name in os.environ:
            interpolated = interpolated.replace(f"${{{name}}}", os.environ[name])
    if interpolated == content:
        return None

    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        prefix=".harbor-finch-compose-",
        suffix=path.suffix,
        dir=Path.cwd(),
        delete=False,
    ) as compose_file:
        compose_file.write(interpolated)
        return Path(compose_file.name)


def _interpolate_compose_arguments(
    arguments: list[str],
) -> tuple[list[str], list[Path]]:
    translated: list[str] = []
    temporary_paths: list[Path] = []
    index = 0
    while index < len(arguments):
        argument = arguments[index]
        if argument in {"-f", "--file"} and index + 1 < len(arguments):
            original_path = Path(arguments[index + 1])
            temporary_path = _interpolate_compose_file(original_path)
            translated.extend([argument, str(temporary_path or original_path)])
            if temporary_path is not None:
                temporary_paths.append(temporary_path)
            index += 2
            continue
        if argument.startswith("--file="):
            original_path = Path(argument.split("=", 1)[1])
            temporary_path = _interpolate_compose_file(original_path)
            translated.append(f"--file={temporary_path or original_path}")
            if temporary_path is not None:
                temporary_paths.append(temporary_path)
            index += 1
            continue
        translated.append(argument)
        index += 1
    return translated, temporary_paths


def main() -> int:
    """Run Finch Compose with Harbor's non-secret placeholders resolved."""
    arguments = _remove_unsupported_down_arguments(sys.argv[1:])
    arguments, temporary_paths = _interpolate_compose_arguments(arguments)
    try:
        result = subprocess.run(
            ["finch", "compose", *arguments],
            check=False,
        )
        return result.returncode
    finally:
        for path in temporary_paths:
            path.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
