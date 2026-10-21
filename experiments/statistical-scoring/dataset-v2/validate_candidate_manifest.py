"""Validate the Dataset v2 candidate manifest."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
MANIFEST_PATH = ROOT / "candidate_manifest.json"
COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")


def validate() -> list[str]:
    errors: list[str] = []
    manifest = json.loads(MANIFEST_PATH.read_text())
    candidates: list[dict[str, Any]] = manifest["candidates"]

    if manifest["manifest_version"] != 1:
        errors.append("manifest_version must be 1")
    if manifest["target_design"]["new_case_count"] != 20:
        errors.append("target_design.new_case_count must be 20")
    if len(candidates) != 20:
        errors.append(f"expected 20 candidates, found {len(candidates)}")

    ranks = [candidate["rank"] for candidate in candidates]
    if ranks != list(range(1, len(candidates) + 1)):
        errors.append("candidate ranks must be contiguous and ordered")

    for field in ("issue_number", "fix_pr_number", "base_commit", "merge_commit"):
        values = [candidate[field] for candidate in candidates]
        if len(values) != len(set(values)):
            errors.append(f"{field} values must be unique")

    for candidate in candidates:
        label = f"candidate #{candidate['issue_number']}"
        if candidate["status"] != "selected":
            errors.append(f"{label} must have selected status")
        if not COMMIT_PATTERN.fullmatch(candidate["base_commit"]):
            errors.append(f"{label} has an invalid base_commit")
        if not COMMIT_PATTERN.fullmatch(candidate["merge_commit"]):
            errors.append(f"{label} has an invalid merge_commit")
        if not candidate["source_files"]:
            errors.append(f"{label} has no source files")
        if not candidate["test_files"]:
            errors.append(f"{label} has no test files")
        if not all(path.startswith("strands-py/src/") for path in candidate["source_files"]):
            errors.append(f"{label} contains a source path outside strands-py/src")
        if not all("test" in path.lower() for path in candidate["test_files"]):
            errors.append(f"{label} contains a non-test path in test_files")
        expected_issue_url = f"https://github.com/strands-agents/harness-sdk/issues/{candidate['issue_number']}"
        if candidate["issue_url"] != expected_issue_url:
            errors.append(f"{label} has an unexpected issue_url")
        expected_pr_url = f"https://github.com/strands-agents/harness-sdk/pull/{candidate['fix_pr_number']}"
        if candidate["fix_pr_url"] != expected_pr_url:
            errors.append(f"{label} has an unexpected fix_pr_url")

    return errors


def main() -> None:
    errors = validate()
    if errors:
        print("Candidate manifest validation failed:")
        for error in errors:
            print(f"- {error}")
        raise SystemExit(1)

    print("Candidate manifest validation passed: 20 selected issues with source and test provenance.")


if __name__ == "__main__":
    main()
