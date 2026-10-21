"""Build a tidy run-level table from the pilot evaluator replay report."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "experiment_config.json"
REPORT_PATH = BASE_DIR / "evaluation_report.json"
OUTPUT_PATH = BASE_DIR / "tidy_evaluations.json"
RUN_PATTERN = re.compile(r"^(?P<case_id>.+)-t(?P<run_index>[0-9]+)$")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_table() -> dict[str, Any]:
    config = json.loads(CONFIG_PATH.read_text())
    source_rows = json.loads(REPORT_PATH.read_text())
    rows = []
    for source_index, source in enumerate(source_rows):
        match = RUN_PATTERN.fullmatch(source["case"])
        if match is None:
            raise ValueError(f"invalid run id: {source['case']}")
        case_id = match.group("case_id")
        run_index = int(match.group("run_index"))
        replay_id = int(source["trial"])
        evaluator_name = source["evaluator"]
        rows.append(
            {
                "observation_id": f"{source['case']}|{evaluator_name}|replay-{replay_id}",
                "dataset_id": config["experiment_id"],
                "case_id": case_id,
                "case_kind": "bug-fix",
                "run_id": source["case"],
                "run_index": run_index,
                "replay_id": replay_id,
                "evaluator_name": evaluator_name,
                "evaluation_unit": "run",
                "score": float(source["score"]),
                "source_test_pass": bool(source["test_pass"]),
                "reason": source["reason"],
                "source_row_index": source_index,
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
    table = {
        "schema_version": 1,
        "dataset_id": config["experiment_id"],
        "table_name": "tidy_run_level_evaluations",
        "source": {
            "report": REPORT_PATH.name,
            "report_sha256": sha256_file(REPORT_PATH),
            "source_row_count": len(source_rows),
        },
        "grain": "One row per case, fixed agent run, judge replay, and evaluator.",
        "dimensions": {
            "case_count": len({row["case_id"] for row in rows}),
            "run_count": len({row["run_id"] for row in rows}),
            "replay_count": len({row["replay_id"] for row in rows}),
            "evaluator_count": len({row["evaluator_name"] for row in rows}),
            "row_count": len(rows),
            "case_ids": sorted({row["case_id"] for row in rows}),
            "run_ids": sorted({row["run_id"] for row in rows}),
            "replay_ids": sorted({row["replay_id"] for row in rows}),
            "evaluator_names": sorted({row["evaluator_name"] for row in rows}),
        },
        "rows": rows,
    }
    return table


if __name__ == "__main__":
    result = build_table()
    OUTPUT_PATH.write_text(json.dumps(result, indent=2) + "\n")
    print(f"Wrote {len(result['rows'])} rows to {OUTPUT_PATH}")
