"""Tests for conversion of Tau3 Harbor artifacts."""

import json
from pathlib import Path

from tau3_session import build_session


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")


def test_recovers_harbor_output_when_runtime_state_omits_final_assistant(
    tmp_path: Path,
) -> None:
    agent_dir = tmp_path / "agent"
    agent_dir.mkdir()
    (agent_dir / "instruction.txt").write_text("system prompt", encoding="utf-8")
    _write_json(
        agent_dir / "tau3_runtime_state.json",
        {
            "termination_reason": None,
            "messages": [
                {"role": "user", "content": "What is my balance?"},
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call-1",
                            "name": "get_balance",
                            "arguments": {"user_id": "user-1"},
                        }
                    ],
                },
                {
                    "role": "tool",
                    "tool_call_id": "call-1",
                    "content": '{"balance": 10}',
                },
            ],
        },
    )
    _write_json(
        agent_dir / "trajectory.json",
        {
            "session_id": "session-1",
            "agent": {
                "tool_definitions": [
                    {
                        "function": {
                            "name": "get_balance",
                            "description": "Get a balance",
                            "parameters": {"type": "object"},
                        }
                    }
                ]
            },
        },
    )
    _write_json(
        tmp_path / "result.json",
        {
            "finished_at": "2026-10-20T12:00:00Z",
            "agent_result": {
                "metadata": {
                    "output": "Your balance is $10.",
                }
            },
        },
    )

    session, final_response = build_session(tmp_path)

    assert final_response == "Your balance is $10."
    assert len(session.traces) == 1
    assert session.traces[0].spans[0].agent_response == final_response
    assert len(session.traces[0].spans) == 2
