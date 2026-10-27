"""Generate the frozen Tau3 smoke or main task directories."""

import argparse
import json
import shutil
from pathlib import Path

from freeze_tasks import (
    CONFIG_PATH,
    MANIFEST_PATH,
    _load_module,
    build_manifest,
)

_RUNTIME_DOCKERFILES = (
    Path("environment/Dockerfile"),
    Path("environment/runtime-server/Dockerfile"),
)
_REPO_ARGUMENT = (
    'ARG TAU2_BENCH_REPO="https://github.com/sierra-research/tau2-bench.git"'
)
_CLONE_COMMAND = (
    '    && git clone --depth=1 "${TAU2_BENCH_REPO}" "${TAU2_BENCH_ROOT}" \\'
)
_INSTALL_TARGET = 'pip install --no-cache-dir "${TAU2_BENCH_ROOT}[knowledge]"'
_TASK_CONFIG_PATH = Path("task.toml")
_COMPOSE_PATH = Path("environment/docker-compose.yaml")
_CREDENTIAL_PROXY_SOURCE = Path(__file__).with_name("credential_proxy.py")
_CREDENTIAL_PROXY_IP = "169.254.170.23"


def _replace_once(content: str, old: str, new: str, path: Path) -> str:
    if old not in content:
        raise ValueError(f"cannot configure unexpected template at {path}")
    return content.replace(old, new, 1)


def _freeze_task_runtime(task_dir: Path, tau2_commit: str) -> None:
    for relative_path in _RUNTIME_DOCKERFILES:
        dockerfile_path = task_dir / relative_path
        content = dockerfile_path.read_text(encoding="utf-8")
        required_fragments = (_REPO_ARGUMENT, _CLONE_COMMAND, _INSTALL_TARGET)
        missing = [
            fragment for fragment in required_fragments if fragment not in content
        ]
        if missing:
            raise ValueError(
                f"cannot freeze unexpected Dockerfile template at {dockerfile_path}: "
                f"missing={missing}"
            )

        pinned_repository = (
            f"{_REPO_ARGUMENT}\n"
            f'ARG TAU2_BENCH_COMMIT="{tau2_commit}"'
        )
        pinned_checkout = "\n".join(
            (
                '    && git init "${TAU2_BENCH_ROOT}" \\',
                '    && git -C "${TAU2_BENCH_ROOT}" remote add origin '
                '"${TAU2_BENCH_REPO}" \\',
                '    && git -C "${TAU2_BENCH_ROOT}" fetch --depth=1 origin '
                '"${TAU2_BENCH_COMMIT}" \\',
                '    && git -C "${TAU2_BENCH_ROOT}" checkout --detach FETCH_HEAD \\',
            )
        )
        content = content.replace(_REPO_ARGUMENT, pinned_repository, 1)
        content = content.replace(_CLONE_COMMAND, pinned_checkout, 1)
        content = content.replace(
            _INSTALL_TARGET,
            f'{_INSTALL_TARGET} "websockets>=13.0" "boto3"',
            1,
        )
        dockerfile_path.write_text(content, encoding="utf-8")


def _configure_bedrock_runtime(task_dir: Path, model_id: str) -> None:
    litellm_model = f"bedrock/{model_id}"
    credential_env = (
        'AWS_CONTAINER_CREDENTIALS_FULL_URI = '
        '"${AWS_CONTAINER_CREDENTIALS_FULL_URI:-'
        f"http://{_CREDENTIAL_PROXY_IP}/"
        '}", '
        'AWS_REGION = "${AWS_REGION:-us-west-2}", '
        'AWS_DEFAULT_REGION = "${AWS_DEFAULT_REGION:-us-west-2}"'
    )

    task_config_path = task_dir / _TASK_CONFIG_PATH
    task_config = task_config_path.read_text(encoding="utf-8")
    task_config = _replace_once(
        task_config,
        'env = { OPENAI_API_KEY = "${OPENAI_API_KEY}", '
        'OPENAI_BASE_URL = "${OPENAI_BASE_URL}", '
        'TAU2_NL_ASSERTIONS_MODEL = "${TAU2_NL_ASSERTIONS_MODEL:-gpt-5.2}" }',
        'env = { OPENAI_API_KEY = "${OPENAI_API_KEY:-}", '
        'OPENAI_BASE_URL = "${OPENAI_BASE_URL:-}", '
        f'TAU2_NL_ASSERTIONS_MODEL = "${{TAU2_NL_ASSERTIONS_MODEL:-{litellm_model}}}", '
        f"{credential_env} }}",
        task_config_path,
    )
    task_config = _replace_once(
        task_config,
        'env = { OPENAI_API_KEY = "${OPENAI_API_KEY}", '
        'OPENAI_BASE_URL = "${OPENAI_BASE_URL}", '
        'TAU2_USER_MODEL = "${TAU2_USER_MODEL:-gpt-5.2}", '
        'TAU2_USER_REASONING_EFFORT = "${TAU2_USER_REASONING_EFFORT:-low}", '
        'TAU2_USER_TEMPERATURE = "${TAU2_USER_TEMPERATURE:-}", '
        'TAU2_USER_LLM_ARGS_JSON = "${TAU2_USER_LLM_ARGS_JSON:-}" }',
        'env = { OPENAI_API_KEY = "${OPENAI_API_KEY:-}", '
        'OPENAI_BASE_URL = "${OPENAI_BASE_URL:-}", '
        f'TAU2_USER_MODEL = "${{TAU2_USER_MODEL:-{litellm_model}}}", '
        'TAU2_USER_REASONING_EFFORT = "${TAU2_USER_REASONING_EFFORT:-low}", '
        'TAU2_USER_TEMPERATURE = "${TAU2_USER_TEMPERATURE:-}", '
        'TAU2_USER_LLM_ARGS_JSON = "${TAU2_USER_LLM_ARGS_JSON:-}", '
        f"{credential_env} }}",
        task_config_path,
    )
    task_config_path.write_text(task_config, encoding="utf-8")

    compose_path = task_dir / _COMPOSE_PATH
    compose = compose_path.read_text(encoding="utf-8")
    compose = _replace_once(
        compose,
        "      - TAU2_USER_MODEL=${TAU2_USER_MODEL:-gpt-5.2}",
        f"      - TAU2_USER_MODEL=${{TAU2_USER_MODEL:-{litellm_model}}}",
        compose_path,
    )
    compose = _replace_once(
        compose,
        "      - TAU2_USER_REASONING_EFFORT="
        "${TAU2_USER_REASONING_EFFORT:-low}",
        "\n".join(
            (
                "      - TAU2_USER_REASONING_EFFORT="
                "${TAU2_USER_REASONING_EFFORT:-low}",
                "      - AWS_CONTAINER_CREDENTIALS_FULL_URI="
                "${AWS_CONTAINER_CREDENTIALS_FULL_URI:-"
                f"http://{_CREDENTIAL_PROXY_IP}/"
                "}",
                "      - AWS_REGION=${AWS_REGION:-us-west-2}",
                "      - AWS_DEFAULT_REGION=${AWS_DEFAULT_REGION:-us-west-2}",
            )
        ),
        compose_path,
    )
    compose = _replace_once(
        compose,
        "  tau3-runtime:\n    build:",
        "  tau3-runtime:\n"
        "    depends_on:\n"
        "      aws-credential-proxy:\n"
        "        condition: service_healthy\n"
        "    build:",
        compose_path,
    )
    compose += (
        "\n  aws-credential-proxy:\n"
        "    build:\n"
        "      context: ./runtime-server\n"
        '    command: ["python3", "credential_proxy.py"]\n'
        "    environment:\n"
        "      - ADA_CREDENTIALS_URL=${ADA_CREDENTIALS_URL}\n"
        "    networks:\n"
        "      default:\n"
        f"        ipv4_address: {_CREDENTIAL_PROXY_IP}\n"
        "    healthcheck:\n"
        "      test: [\"CMD\", \"python3\", \"-c\", "
        "\"import socket; s=socket.create_connection(('localhost',80),timeout=2); "
        "s.close()\"]\n"
        "      interval: 2s\n"
        "      timeout: 5s\n"
        "      retries: 15\n"
        "      start_period: 2s\n"
        "\nnetworks:\n"
        "  default:\n"
        "    ipam:\n"
        "      config:\n"
        "        - subnet: 169.254.170.0/24\n"
    )
    compose_path.write_text(compose, encoding="utf-8")

    runtime_dir = task_dir / "environment/runtime-server"
    shutil.copy2(_CREDENTIAL_PROXY_SOURCE, runtime_dir / _CREDENTIAL_PROXY_SOURCE.name)
    runtime_dockerfile = runtime_dir / "Dockerfile"
    dockerfile = runtime_dockerfile.read_text(encoding="utf-8")
    dockerfile = _replace_once(
        dockerfile,
        "COPY server.py ./\n",
        "COPY server.py ./\nCOPY credential_proxy.py ./\n",
        runtime_dockerfile,
    )
    runtime_dockerfile.write_text(dockerfile, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--harbor-root", type=Path, required=True)
    parser.add_argument("--tau2-root", type=Path, required=True)
    parser.add_argument("--stage", choices=("smoke", "main"), required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    harbor_root = args.harbor_root.expanduser().resolve()
    tau2_root = args.tau2_root.expanduser().resolve()
    output_dir = args.output_dir.expanduser().resolve()
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    regenerated = build_manifest(harbor_root, tau2_root)
    if regenerated != manifest:
        raise ValueError("task_manifest.json does not match the pinned source checkouts")

    if output_dir.exists() and any(output_dir.iterdir()):
        if not args.overwrite:
            raise ValueError(
                f"output directory is not empty: {output_dir}; pass --overwrite to replace it"
            )
        shutil.rmtree(output_dir)

    task_ids = [
        task["harbor_task_id"]
        for task in manifest["tasks"]
        if args.stage in task["stages"]
    ]
    adapter_path = (
        harbor_root
        / "adapters"
        / "tau3-bench"
        / "src"
        / "tau3_bench"
        / "adapter.py"
    )
    adapter_module = _load_module(adapter_path)
    adapter_module.Tau3BenchAdapter(
        output_dir=output_dir,
        overwrite=False,
        task_ids=task_ids,
        tau2_root=tau2_root,
        split_name=config["sources"]["tau2_bench"]["split"],
        domains=config["sampling"]["domains"],
    ).run()

    tau2_commit = config["sources"]["tau2_bench"]["commit"]
    model_id = config["models"]["simulated_user"]["model_id"]
    for task_dir in output_dir.iterdir():
        if task_dir.is_dir():
            _freeze_task_runtime(task_dir, tau2_commit)
            _configure_bedrock_runtime(task_dir, model_id)

    generated_ids = sorted(path.name for path in output_dir.iterdir() if path.is_dir())
    if generated_ids != sorted(task_ids):
        raise ValueError(
            f"generated task set differs from the manifest: "
            f"expected={sorted(task_ids)}, actual={generated_ids}"
        )
    print(f"Generated {len(generated_ids)} {args.stage} tasks in {output_dir}")


if __name__ == "__main__":
    main()
