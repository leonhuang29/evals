"""Generate two isolated Stan runs for each dataset-v2 pilot case."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.metadata
import json
import os
import platform
import shutil
import subprocess
import sys
import time
import traceback
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent
SCRIPT_PATH = Path(__file__).resolve()
PILOT_MANIFEST_PATH = BASE_DIR / "pilot_manifest.json"
CONFIG_PATH = BASE_DIR / "experiment_config.json"
RUNS_DIR = BASE_DIR / "runs"
SESSIONS_DIR = BASE_DIR / "sessions"
LOGS_DIR = BASE_DIR / "logs"
WORKTREES_DIR = BASE_DIR / "worktrees"


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_command(
    command: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    input_bytes: bytes | None = None,
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        command,
        cwd=cwd,
        env=env,
        input=input_bytes,
        capture_output=True,
        check=False,
    )


def command_output(result: subprocess.CompletedProcess[bytes]) -> str:
    return (result.stdout + result.stderr).decode(errors="replace")


def git(repo: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    return run_command(["git", "-C", str(repo), *args])


def require_success(result: subprocess.CompletedProcess[bytes], description: str) -> None:
    if result.returncode != 0:
        raise RuntimeError(f"{description} failed:\n{command_output(result)}")


def package_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def json_safe(value: Any) -> Any:
    return json.loads(json.dumps(value, default=str))


def stan_commit() -> str | None:
    result = run_command(["git", "rev-parse", "HEAD"], cwd=BASE_DIR)
    return result.stdout.decode().strip() if result.returncode == 0 else None


def worker_main(case_name: str, trial: int) -> None:
    from opentelemetry import baggage, context
    from opentelemetry import trace as otel_trace
    from strands_evals.mappers.strands_in_memory_session_mapper import StrandsInMemorySessionMapper
    from strands_evals.telemetry import StrandsEvalsTelemetry

    from strands_stan import harness_agent

    manifest = load_json(PILOT_MANIFEST_PATH)
    config = load_json(CONFIG_PATH)
    case = next(item for item in manifest["cases"] if item["name"] == case_name)
    agent_config = config["agent"]
    run_id = f"{case_name}-t{trial}"
    prompt = (BASE_DIR / case["prompt_file"]).read_text()

    telemetry = StrandsEvalsTelemetry().setup_in_memory_exporter()
    mapper = StrandsInMemorySessionMapper()
    run_manifest: dict[str, Any] = {
        "run_id": run_id,
        "case_id": case_name,
        "issue_number": case["issue_number"],
        "trial": trial,
        "session_id": run_id,
        "base_commit": case["base_commit"],
        "fix_commit": case["fix_commit"],
        "workdir": os.getcwd(),
        "started_at": datetime.now(UTC).isoformat(),
        "agent_configuration": agent_config,
        "experiment_config_sha256": sha256_file(CONFIG_PATH),
        "pilot_manifest_sha256": sha256_file(PILOT_MANIFEST_PATH),
        "runner_sha256": sha256_file(SCRIPT_PATH),
        "environment": {
            "python": sys.version,
            "platform": platform.platform(),
            "strands_agents_version": package_version("strands-agents"),
            "strands_stan_version": package_version("strands-agents-stan"),
            "strands_evals_version": package_version("strands-agents-evals"),
            "stan_commit": stan_commit(),
        },
    }

    ctx = baggage.set_baggage("session.id", run_id)
    ctx = baggage.set_baggage("gen_ai.conversation.id", run_id, ctx)
    token = context.attach(ctx)
    start = time.monotonic()
    try:
        agent = harness_agent(
            model=agent_config["model"],
            thinking=agent_config["thinking"],
            builtin_tools=agent_config["builtin_tools"],
            builtin_plugins=agent_config["builtin_plugins"],
            background_tasks=agent_config["background_tasks"],
            caching=agent_config["caching"],
            context_management=agent_config["context_management"],
            session=agent_config["session"],
            memory=agent_config["memory"],
            skills_dir=agent_config["skills_dir"],
            callback_handler=None,
        )
        run_manifest["resolved_model_config"] = json_safe(agent.model.get_config())
        result = agent(prompt)
        run_manifest["output"] = str(result)
    except Exception as error:
        run_manifest["error"] = f"{type(error).__name__}: {error}"
        run_manifest["traceback"] = traceback.format_exc()
    finally:
        context.detach(token)
        run_manifest["duration_seconds"] = round(time.monotonic() - start, 3)
        run_manifest["finished_at"] = datetime.now(UTC).isoformat()

    spans = list(telemetry.in_memory_exporter.get_finished_spans())
    session = mapper.map_to_session(spans, run_id)
    run_manifest["finished_span_count"] = len(spans)
    run_manifest["mapped_trace_count"] = len(session.traces)
    (SESSIONS_DIR / f"{run_id}.json").write_text(session.model_dump_json(indent=2) + "\n")
    (RUNS_DIR / f"{run_id}.json").write_text(json.dumps(run_manifest, indent=2) + "\n")

    try:
        otel_trace.get_tracer_provider().force_flush()
    except Exception:
        pass


def capture_diff(worktree: Path) -> tuple[str, list[str], str]:
    require_success(git(worktree, "add", "-A"), "stage run changes")
    diff = git(worktree, "diff", "--cached", "--binary")
    require_success(diff, "capture run diff")
    changed = git(worktree, "diff", "--cached", "--name-only")
    require_success(changed, "capture changed files")
    stat = git(worktree, "diff", "--cached", "--stat")
    require_success(stat, "capture diff stat")
    return (
        diff.stdout.decode(errors="replace"),
        [line for line in changed.stdout.decode().splitlines() if line],
        stat.stdout.decode(errors="replace"),
    )


def run_hidden_test(worktree: Path, case: dict[str, Any]) -> dict[str, Any]:
    hidden_source = BASE_DIR / case["hidden_test_file"]
    hidden_target = worktree / case["hidden_test_target"]
    hidden_target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(hidden_source, hidden_target)

    package_dir = worktree / "strands-py"
    relative_test = hidden_target.relative_to(package_dir)
    environment = os.environ.copy()
    local_source = str(package_dir / "src")
    existing_pythonpath = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = (
        f"{local_source}{os.pathsep}{existing_pythonpath}" if existing_pythonpath else local_source
    )
    command = [
        sys.executable,
        "-m",
        "pytest",
        "-q",
        "-c",
        os.devnull,
        "--confcutdir",
        str(relative_test.parent),
        str(relative_test),
    ]
    result = run_command(command, cwd=package_dir, env=environment)
    try:
        hidden_target.unlink()
    except FileNotFoundError:
        pass

    return {
        "status": "passed" if result.returncode == 0 else "failed",
        "return_code": result.returncode,
        "command": command,
        "output_tail": command_output(result)[-6000:],
    }


async def run_one(
    repo: Path,
    case: dict[str, Any],
    trial: int,
    semaphore: asyncio.Semaphore,
    git_lock: asyncio.Lock,
    timeout_seconds: float,
) -> None:
    run_id = f"{case['name']}-t{trial}"
    run_path = RUNS_DIR / f"{run_id}.json"
    session_path = SESSIONS_DIR / f"{run_id}.json"
    if run_path.exists() and session_path.exists():
        existing = load_json(run_path)
        if "diff" in existing and "hidden_test" in existing:
            print(f"[skip] {run_id}")
            return

    async with semaphore:
        worktree = WORKTREES_DIR / run_id
        async with git_lock:
            if worktree.exists():
                remove = git(repo, "worktree", "remove", "--force", str(worktree))
                require_success(remove, f"remove stale worktree for {run_id}")
            add = git(repo, "worktree", "add", "--detach", str(worktree), case["base_commit"])
            require_success(add, f"create worktree for {run_id}")

        print(f"[start] {run_id}")
        log_path = LOGS_DIR / f"{run_id}.log"
        status = "ok"
        with log_path.open("w") as log_file:
            process = await asyncio.create_subprocess_exec(
                sys.executable,
                str(SCRIPT_PATH),
                "--worker",
                case["name"],
                str(trial),
                cwd=worktree,
                stdout=log_file,
                stderr=asyncio.subprocess.STDOUT,
            )
            try:
                return_code = await asyncio.wait_for(process.wait(), timeout=timeout_seconds)
                if return_code != 0:
                    status = f"worker-exit-{return_code}"
            except TimeoutError:
                process.kill()
                await process.wait()
                status = f"timeout-{int(timeout_seconds)}s"

        run_manifest = (
            load_json(run_path)
            if run_path.exists()
            else {
                "run_id": run_id,
                "case_id": case["name"],
                "issue_number": case["issue_number"],
                "trial": trial,
                "base_commit": case["base_commit"],
                "fix_commit": case["fix_commit"],
            }
        )
        if status != "ok" and "error" not in run_manifest:
            run_manifest["error"] = f"run did not complete: {status}"

        try:
            diff, changed_files, diff_stat = await asyncio.to_thread(capture_diff, worktree)
            run_manifest["diff"] = diff
            run_manifest["diff_sha256"] = hashlib.sha256(diff.encode()).hexdigest()
            run_manifest["changed_files"] = changed_files
            run_manifest["diff_stat"] = diff_stat
        except Exception as error:
            run_manifest["diff"] = ""
            run_manifest["changed_files"] = []
            run_manifest["diff_error"] = f"{type(error).__name__}: {error}"

        run_manifest["hidden_test"] = await asyncio.to_thread(run_hidden_test, worktree, case)
        run_manifest["orchestrator_status"] = status
        run_path.write_text(json.dumps(run_manifest, indent=2) + "\n")

        async with git_lock:
            remove = git(repo, "worktree", "remove", "--force", str(worktree))
            require_success(remove, f"remove worktree for {run_id}")

        final_status = "error" if "error" in run_manifest else run_manifest["hidden_test"]["status"]
        print(
            f"[{final_status}] {run_id} "
            f"{run_manifest.get('duration_seconds', '?')}s "
            f"files={len(run_manifest.get('changed_files', []))}"
        )


async def orchestrate(repo: Path, only: str | None) -> None:
    manifest = load_json(PILOT_MANIFEST_PATH)
    config = load_json(CONFIG_PATH)
    agent_config = config["agent"]

    for directory in (RUNS_DIR, SESSIONS_DIR, LOGS_DIR, WORKTREES_DIR):
        directory.mkdir(parents=True, exist_ok=True)

    if not (repo / ".git").exists():
        raise RuntimeError(f"{repo} is not a git checkout")

    cases = [
        case for case in manifest["cases"] if only is None or only in case["name"] or only == str(case["issue_number"])
    ]
    if not cases:
        raise RuntimeError(f"no pilot cases match {only!r}")

    runs = [(case, trial) for case in cases for trial in range(agent_config["runs_per_case"])]
    print(
        f"{len(runs)} runs | model={agent_config['model']} | "
        f"concurrency={agent_config['max_concurrent_runs']} | "
        f"timeout={agent_config['timeout_seconds']}s"
    )

    semaphore = asyncio.Semaphore(agent_config["max_concurrent_runs"])
    git_lock = asyncio.Lock()
    await asyncio.gather(
        *[
            run_one(
                repo,
                case,
                trial,
                semaphore,
                git_lock,
                agent_config["timeout_seconds"],
            )
            for case, trial in runs
        ]
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, help="local harness-sdk checkout")
    parser.add_argument("--only", help="run only case names containing this value")
    parser.add_argument("--worker", nargs=2, metavar=("CASE", "TRIAL"))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.worker:
        worker_main(args.worker[0], int(args.worker[1]))
        return
    if args.repo is None:
        raise SystemExit("--repo is required")
    asyncio.run(orchestrate(args.repo.resolve(), args.only))


if __name__ == "__main__":
    main()
