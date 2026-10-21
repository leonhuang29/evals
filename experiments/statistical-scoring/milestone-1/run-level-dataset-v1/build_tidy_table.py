"""Build the tidy run-level evaluation table from the frozen score report."""

from __future__ import annotations

import hashlib
import json
import re
import runpy
from pathlib import Path
from typing import Any

from validate_dataset import validate

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "source"
REPORT_PATH = SOURCE / "issue_broad_report.json"
MANIFEST_PATH = ROOT / "dataset_manifest.json"
OUTPUT_PATH = ROOT / "derived" / "tidy_evaluations.json"
CASE_PATTERN = re.compile(r"^(?P<case_id>.+)-t(?P<run_index>[0-9]+)$")

COLUMNS = {
    "observation_id": {
        "type": "string",
        "description": "Unique identifier for one run, evaluator, and replay score.",
    },
    "dataset_id": {
        "type": "string",
        "description": "Identifier of the frozen source dataset.",
    },
    "case_id": {
        "type": "string",
        "description": "Stable task or evaluation case identifier.",
    },
    "case_kind": {
        "type": "string",
        "description": "Case category from the frozen task registry.",
    },
    "run_id": {
        "type": "string",
        "description": "Identifier of one fixed agent execution.",
    },
    "run_index": {
        "type": "integer",
        "description": "Zero-based agent run index within a case.",
    },
    "replay_id": {
        "type": "integer",
        "description": "Zero-based judge replay index for a fixed run.",
    },
    "evaluator_name": {
        "type": "string",
        "description": "Name of the evaluator that produced the score.",
    },
    "evaluation_unit": {
        "type": "string",
        "description": "Unit scored by the evaluator; all rows in this dataset are run-level.",
    },
    "score": {
        "type": "number",
        "description": "Evaluator score on the inclusive 0 to 1 scale.",
    },
    "source_test_pass": {
        "type": "boolean",
        "description": "The source report's test_pass value, preserved without reinterpretation.",
    },
    "reason": {
        "type": "string",
        "description": "Evaluator-provided explanation for the score.",
    },
    "source_row_index": {
        "type": "integer",
        "description": "Zero-based row position in the frozen source report.",
    },
}


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_case_kinds() -> dict[str, str]:
    tasks = runpy.run_path(str(SOURCE / "issue_cases.py"))["TASKS"]
    return {task["name"]: task["kind"] for task in tasks}


def build_rows(dataset_id: str) -> list[dict[str, Any]]:
    source_rows = json.loads(REPORT_PATH.read_text())
    case_kinds = load_case_kinds()
    rows: list[dict[str, Any]] = []

    for source_row_index, source_row in enumerate(source_rows):
        run_id = source_row["case"]
        match = CASE_PATTERN.fullmatch(run_id)
        if match is None:
            raise ValueError(f"invalid run identifier: {run_id}")

        case_id = match.group("case_id")
        run_index = int(match.group("run_index"))
        replay_id = int(source_row["trial"])
        evaluator_name = source_row["evaluator"]

        rows.append(
            {
                "observation_id": f"{run_id}|{evaluator_name}|replay-{replay_id}",
                "dataset_id": dataset_id,
                "case_id": case_id,
                "case_kind": case_kinds[case_id],
                "run_id": run_id,
                "run_index": run_index,
                "replay_id": replay_id,
                "evaluator_name": evaluator_name,
                "evaluation_unit": "run",
                "score": float(source_row["score"]),
                "source_test_pass": source_row["test_pass"],
                "reason": source_row["reason"],
                "source_row_index": source_row_index,
            }
        )

    rows.sort(
        key=lambda row: (
            row["case_id"],
            row["run_index"],
            row["evaluator_name"],
            row["replay_id"],
        )
    )
    return rows


def validate_tidy_table(table: dict[str, Any], source_row_count: int) -> None:
    rows = table["rows"]
    if len(rows) != source_row_count:
        raise ValueError(f"expected {source_row_count} tidy rows, found {len(rows)}")

    observation_ids = {row["observation_id"] for row in rows}
    if len(observation_ids) != len(rows):
        raise ValueError("tidy table contains duplicate observation identifiers")

    source_indexes = {row["source_row_index"] for row in rows}
    if source_indexes != set(range(source_row_count)):
        raise ValueError("tidy table does not map one-to-one to source report rows")

    expected_columns = set(COLUMNS)
    for row_index, row in enumerate(rows):
        if set(row) != expected_columns:
            raise ValueError(f"tidy row {row_index} does not match the declared column schema")

    dimensions = table["dimensions"]
    if len({row["case_id"] for row in rows}) != dimensions["case_count"]:
        raise ValueError("case count does not match the tidy rows")
    if len({row["run_id"] for row in rows}) != dimensions["run_count"]:
        raise ValueError("run count does not match the tidy rows")
    if len({row["replay_id"] for row in rows}) != dimensions["replay_count"]:
        raise ValueError("replay count does not match the tidy rows")
    if len({row["evaluator_name"] for row in rows}) != dimensions["evaluator_count"]:
        raise ValueError("evaluator count does not match the tidy rows")


def build_table() -> dict[str, Any]:
    source_errors = validate()
    if source_errors:
        raise ValueError(f"frozen source dataset failed validation: {source_errors}")

    manifest = json.loads(MANIFEST_PATH.read_text())
    dataset_id = manifest["dataset_id"]
    rows = build_rows(dataset_id)
    case_ids = sorted({row["case_id"] for row in rows})
    run_ids = sorted({row["run_id"] for row in rows})
    replay_ids = sorted({row["replay_id"] for row in rows})
    evaluator_names = manifest["evaluators"]

    table = {
        "schema_version": 1,
        "dataset_id": dataset_id,
        "table_name": "tidy_run_level_evaluations",
        "source": {
            "report": "source/issue_broad_report.json",
            "report_sha256": file_sha256(REPORT_PATH),
            "source_row_count": len(rows),
        },
        "grain": "One row per case, fixed agent run, judge replay, and evaluator.",
        "dimensions": {
            "case_count": len(case_ids),
            "run_count": len(run_ids),
            "replay_count": len(replay_ids),
            "evaluator_count": len(evaluator_names),
            "row_count": len(rows),
            "case_ids": case_ids,
            "run_ids": run_ids,
            "replay_ids": replay_ids,
            "evaluator_names": evaluator_names,
        },
        "columns": COLUMNS,
        "rows": rows,
    }
    validate_tidy_table(table, len(rows))
    return table


def main() -> None:
    table = build_table()
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(table, indent=2, ensure_ascii=True) + "\n")
    print(f"Wrote {len(table['rows'])} rows to {OUTPUT_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
