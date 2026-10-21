"""Validate the dataset-v2 pilot structure and its historical regression boundaries."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent
MANIFEST_PATH = BASE_DIR / "pilot_manifest.json"
REPORT_PATH = BASE_DIR / "pilot_validation_results.json"
EXPECTED_ISSUES = {4601, 4411, 4354, 4155, 3910}


class ValidationError(RuntimeError):
    """Raised when a frozen pilot invariant does not hold."""


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(
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


def output_text(result: subprocess.CompletedProcess[bytes]) -> str:
    return (result.stdout + result.stderr).decode(errors="replace")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def validate_structure() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    manifest = load_json(MANIFEST_PATH)
    candidate_path = (BASE_DIR / manifest["candidate_manifest"]).resolve()
    candidate_manifest = load_json(candidate_path)
    candidates = {candidate["issue_number"]: candidate for candidate in candidate_manifest["candidates"]}

    cases = manifest["cases"]
    if manifest["case_count"] != len(cases):
        raise ValidationError("case_count does not match the number of pilot cases")

    issue_numbers = {case["issue_number"] for case in cases}
    if issue_numbers != EXPECTED_ISSUES:
        raise ValidationError(f"pilot issues are {sorted(issue_numbers)}, expected {sorted(EXPECTED_ISSUES)}")

    names = [case["name"] for case in cases]
    if len(names) != len(set(names)):
        raise ValidationError("pilot case names must be unique")

    for case in cases:
        issue_number = case["issue_number"]
        candidate = candidates.get(issue_number)
        if candidate is None or candidate["status"] != "selected":
            raise ValidationError(f"issue #{issue_number} is not a selected candidate")
        if candidate["base_commit"] != case["base_commit"]:
            raise ValidationError(f"issue #{issue_number} base commit differs from candidate audit")
        if candidate["merge_commit"] != case["fix_commit"]:
            raise ValidationError(f"issue #{issue_number} fix commit differs from candidate audit")
        if candidate["fix_pr_number"] != case["fix_pr_number"]:
            raise ValidationError(f"issue #{issue_number} fix PR differs from candidate audit")
        if candidate["source_files"] != case["source_files"]:
            raise ValidationError(f"issue #{issue_number} source files differ from candidate audit")

        for file_key, hash_key in (
            ("prompt_file", "prompt_sha256"),
            ("reference_file", "reference_sha256"),
        ):
            path = BASE_DIR / case[file_key]
            if not path.is_file():
                raise ValidationError(f"issue #{issue_number} is missing {path}")
            actual_hash = sha256_file(path)
            if actual_hash != case[hash_key]:
                raise ValidationError(
                    f"issue #{issue_number} {file_key} hash is {actual_hash}, expected {case[hash_key]}"
                )

        hidden_test = BASE_DIR / case["hidden_test_file"]
        if not hidden_test.is_file():
            raise ValidationError(f"issue #{issue_number} is missing {hidden_test}")
        if not case["hidden_test_target"].startswith("strands-py/tests/"):
            raise ValidationError(f"issue #{issue_number} hidden test target is outside tests")

    return manifest, cases


def git(repo: Path, *args: str, input_bytes: bytes | None = None) -> subprocess.CompletedProcess[bytes]:
    return run(["git", "-C", str(repo), *args], input_bytes=input_bytes)


def require_success(result: subprocess.CompletedProcess[bytes], description: str) -> None:
    if result.returncode != 0:
        raise ValidationError(f"{description} failed:\n{output_text(result)}")


def validate_commit_provenance(repo: Path, case: dict[str, Any]) -> None:
    issue_number = case["issue_number"]
    for key in ("base_commit", "fix_commit"):
        result = git(repo, "cat-file", "-e", f"{case[key]}^{{commit}}")
        require_success(result, f"issue #{issue_number} {key} lookup")

    parent = git(repo, "rev-parse", f"{case['fix_commit']}^1")
    require_success(parent, f"issue #{issue_number} fix-parent lookup")
    if parent.stdout.decode().strip() != case["base_commit"]:
        raise ValidationError(f"issue #{issue_number} base commit is not the fix's first parent")

    changed = git(
        repo,
        "diff",
        "--name-only",
        case["base_commit"],
        case["fix_commit"],
        "--",
        *case["source_files"],
    )
    require_success(changed, f"issue #{issue_number} source diff lookup")
    changed_files = {line for line in changed.stdout.decode().splitlines() if line}
    if changed_files != set(case["source_files"]):
        raise ValidationError(
            f"issue #{issue_number} changed source files are {sorted(changed_files)}, "
            f"expected {sorted(case['source_files'])}"
        )


def run_hidden_test(
    repo: Path,
    case: dict[str, Any],
    python: Path,
    temporary_root: Path,
) -> dict[str, Any]:
    issue_number = case["issue_number"]
    worktree = temporary_root / case["name"]
    add_result = git(repo, "worktree", "add", "--detach", str(worktree), case["base_commit"])
    require_success(add_result, f"issue #{issue_number} worktree creation")

    try:
        hidden_test_source = BASE_DIR / case["hidden_test_file"]
        hidden_test_target = worktree / case["hidden_test_target"]
        hidden_test_target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(hidden_test_source, hidden_test_target)

        package_dir = worktree / "strands-py"
        relative_test = hidden_test_target.relative_to(package_dir)
        environment = os.environ.copy()
        source_path = str(package_dir / "src")
        existing_pythonpath = environment.get("PYTHONPATH")
        environment["PYTHONPATH"] = (
            f"{source_path}{os.pathsep}{existing_pythonpath}" if existing_pythonpath else source_path
        )
        test_command = [
            str(python),
            "-m",
            "pytest",
            "-q",
            "-c",
            os.devnull,
            "--confcutdir",
            str(relative_test.parent),
            str(relative_test),
        ]

        baseline = run(test_command, cwd=package_dir, env=environment)
        if baseline.returncode != 1:
            raise ValidationError(
                f"issue #{issue_number} baseline must fail with pytest status 1, "
                f"got {baseline.returncode}:\n{output_text(baseline)}"
            )

        source_patch = git(
            repo,
            "diff",
            "--binary",
            case["base_commit"],
            case["fix_commit"],
            "--",
            *case["source_files"],
        )
        require_success(source_patch, f"issue #{issue_number} reference source patch")
        if not source_patch.stdout:
            raise ValidationError(f"issue #{issue_number} reference source patch is empty")

        apply_result = run(
            ["git", "apply", "--whitespace=nowarn", "-"],
            cwd=worktree,
            input_bytes=source_patch.stdout,
        )
        require_success(apply_result, f"issue #{issue_number} source patch application")

        fixed = run(test_command, cwd=package_dir, env=environment)
        if fixed.returncode != 0:
            raise ValidationError(
                f"issue #{issue_number} hidden test did not pass after the known source fix:\n{output_text(fixed)}"
            )

        return {
            "name": case["name"],
            "issue_number": issue_number,
            "base_commit": case["base_commit"],
            "fix_commit": case["fix_commit"],
            "source_patch_sha256": hashlib.sha256(source_patch.stdout).hexdigest(),
            "baseline_status": "failed_as_expected",
            "fixed_status": "passed",
            "baseline_output_tail": output_text(baseline)[-2000:],
            "fixed_output_tail": output_text(fixed)[-2000:],
        }
    finally:
        remove_result = git(repo, "worktree", "remove", "--force", str(worktree))
        require_success(remove_result, f"issue #{issue_number} worktree removal")


def execute_historical_validation(
    repo: Path,
    cases: list[dict[str, Any]],
    python: Path,
) -> dict[str, Any]:
    if not (repo / ".git").exists():
        raise ValidationError(f"{repo} is not a git checkout")
    if not python.is_file():
        raise ValidationError(f"Python executable does not exist: {python}")

    for case in cases:
        validate_commit_provenance(repo, case)

    version = run([str(python), "--version"])
    require_success(version, "Python version lookup")

    with tempfile.TemporaryDirectory(prefix="statistical-evals-pilot-") as directory:
        temporary_root = Path(directory)
        results = [run_hidden_test(repo, case, python, temporary_root) for case in cases]

    report = {
        "validated_at": datetime.now(UTC).isoformat(),
        "repository": str(repo.resolve()),
        "python": str(python.absolute()),
        "python_version": output_text(version).strip(),
        "case_count": len(results),
        "all_boundaries_valid": True,
        "cases": results,
    }
    REPORT_PATH.write_text(json.dumps(report, indent=2) + "\n")
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--execute",
        action="store_true",
        help="run each hidden test before and after its known source fix",
    )
    parser.add_argument(
        "--repo",
        type=Path,
        help="local harness-sdk git checkout containing the recorded commits",
    )
    parser.add_argument(
        "--python",
        type=Path,
        default=Path(sys.executable),
        help="Python executable with harness-sdk test dependencies installed",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    _, cases = validate_structure()
    print(f"Pilot structure validated: {len(cases)} frozen cases")

    if not args.execute:
        return
    if args.repo is None:
        raise SystemExit("--repo is required with --execute")

    report = execute_historical_validation(
        args.repo.resolve(),
        cases,
        args.python.expanduser().absolute(),
    )
    print(f"Historical boundaries validated: {report['case_count']} cases fail before and pass after")
    print(f"Report written to {REPORT_PATH}")


if __name__ == "__main__":
    main()
