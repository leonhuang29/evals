"""Re-run pilot hidden tests against the exact diffs stored in run manifests."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent
MANIFEST_PATH = BASE_DIR / "pilot_manifest.json"
RUNS_DIR = BASE_DIR / "runs"
WORKTREES_DIR = BASE_DIR / "recheck_worktrees"


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


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


def require_success(result: subprocess.CompletedProcess[bytes], description: str) -> None:
    if result.returncode != 0:
        raise RuntimeError(f"{description} failed:\n{command_output(result)}")


def git(repo: Path, *args: str, input_bytes: bytes | None = None) -> subprocess.CompletedProcess[bytes]:
    return run_command(["git", "-C", str(repo), *args], input_bytes=input_bytes)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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
        "-p",
        "no:cacheprovider",
        "-c",
        os.devnull,
        "--confcutdir",
        str(relative_test.parent),
        str(relative_test),
    ]
    result = run_command(command, cwd=package_dir, env=environment)
    hidden_target.unlink(missing_ok=True)
    return {
        "status": "passed" if result.returncode == 0 else "failed",
        "return_code": result.returncode,
        "command": command,
        "output_tail": command_output(result)[-6000:],
        "checked_at": datetime.now(UTC).isoformat(),
        "test_sha256": sha256_file(hidden_source),
    }


def recheck(repo: Path, run_path: Path, cases: dict[str, dict[str, Any]]) -> str:
    run = load_json(run_path)
    case = cases[run["case_id"]]
    run_id = run["run_id"]
    worktree = WORKTREES_DIR / run_id

    if worktree.exists():
        require_success(
            git(repo, "worktree", "remove", "--force", str(worktree)),
            f"remove stale worktree for {run_id}",
        )
    require_success(
        git(repo, "worktree", "add", "--detach", str(worktree), run["base_commit"]),
        f"create worktree for {run_id}",
    )
    try:
        require_success(
            git(worktree, "apply", "--binary", "-", input_bytes=run["diff"].encode()),
            f"apply frozen diff for {run_id}",
        )
        if "hidden_test_initial" not in run:
            run["hidden_test_initial"] = run.get("hidden_test")
        run["hidden_test"] = run_hidden_test(worktree, case)
        run_path.write_text(json.dumps(run, indent=2) + "\n")
        return run["hidden_test"]["status"]
    finally:
        require_success(
            git(repo, "worktree", "remove", "--force", str(worktree)),
            f"remove worktree for {run_id}",
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True, help="local harness-sdk checkout")
    args = parser.parse_args()
    repo = args.repo.resolve()

    manifest = load_json(MANIFEST_PATH)
    cases = {case["name"]: case for case in manifest["cases"]}
    WORKTREES_DIR.mkdir(parents=True, exist_ok=True)

    failures = []
    for run_path in sorted(RUNS_DIR.glob("*.json")):
        status = recheck(repo, run_path, cases)
        print(f"[{status}] {run_path.stem}")
        if status != "passed":
            failures.append(run_path.stem)

    if failures:
        raise SystemExit(f"hidden tests failed for: {', '.join(failures)}")


if __name__ == "__main__":
    main()
