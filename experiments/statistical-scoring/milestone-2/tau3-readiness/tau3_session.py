"""Convert a completed Tau3 Harbor trial into a strands-evals Session."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from strands_evals.types.trace import (
    AgentInvocationSpan,
    Session,
    SpanInfo,
    ToolCall,
    ToolConfig,
    ToolExecutionSpan,
    ToolResult,
    Trace,
)


def _load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"expected a JSON object at {path}")
    return data


def _timestamp(value: object, fallback: datetime) -> datetime:
    if not isinstance(value, str) or not value:
        return fallback
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _tool_configs(trajectory: dict[str, Any]) -> list[ToolConfig]:
    agent = trajectory.get("agent")
    definitions = agent.get("tool_definitions", []) if isinstance(agent, dict) else []
    tools: list[ToolConfig] = []
    for definition in definitions:
        function = definition.get("function") if isinstance(definition, dict) else None
        if not isinstance(function, dict) or not isinstance(function.get("name"), str):
            continue
        tools.append(
            ToolConfig(
                name=function["name"],
                description=function.get("description"),
                parameters=function.get("parameters"),
            )
        )
    return tools


def _harbor_final_response(result: dict[str, Any]) -> str:
    agent_result = result.get("agent_result")
    metadata = agent_result.get("metadata") if isinstance(agent_result, dict) else None
    output = metadata.get("output") if isinstance(metadata, dict) else None
    return output.strip() if isinstance(output, str) else ""


def _finalize_trace(
    *,
    session_id: str,
    turn: int,
    user_message: dict[str, Any],
    assistant_message: dict[str, Any],
    tool_observations: list[tuple[dict[str, Any], dict[str, Any]]],
    available_tools: list[ToolConfig],
    system_prompt: str,
    fallback_time: datetime,
) -> Trace:
    trace_id = f"{session_id}-trace-{turn}"
    agent_span_id = f"{trace_id}-agent"
    start_time = _timestamp(user_message.get("timestamp"), fallback_time)
    end_time = _timestamp(
        assistant_message.get("timestamp"),
        start_time + timedelta(microseconds=1),
    )
    if end_time < start_time:
        end_time = start_time

    agent_span = AgentInvocationSpan(
        span_info=SpanInfo(
            trace_id=trace_id,
            span_id=agent_span_id,
            session_id=session_id,
            start_time=start_time,
            end_time=end_time,
        ),
        user_prompt=str(user_message.get("content") or ""),
        agent_response=str(assistant_message.get("content") or ""),
        available_tools=available_tools,
        system_prompt=system_prompt,
    )

    spans: list[AgentInvocationSpan | ToolExecutionSpan] = [agent_span]
    for index, (call_message, result_message) in enumerate(tool_observations):
        raw_call = (call_message.get("tool_calls") or [])[0]
        call_id = str(raw_call.get("id") or f"{trace_id}-tool-{index}")
        tool_start = _timestamp(
            call_message.get("timestamp"),
            start_time + timedelta(microseconds=index + 1),
        )
        tool_end = _timestamp(
            result_message.get("timestamp"),
            tool_start + timedelta(microseconds=1),
        )
        if tool_end < tool_start:
            tool_end = tool_start
        error = result_message.get("error")
        spans.append(
            ToolExecutionSpan(
                span_info=SpanInfo(
                    trace_id=trace_id,
                    span_id=f"{trace_id}-tool-{index}",
                    session_id=session_id,
                    parent_span_id=agent_span_id,
                    start_time=tool_start,
                    end_time=tool_end,
                ),
                tool_call=ToolCall(
                    name=str(raw_call.get("name") or "unknown"),
                    arguments=raw_call.get("arguments") or {},
                    tool_call_id=call_id,
                ),
                tool_result=ToolResult(
                    content=str(result_message.get("content") or ""),
                    error=str(error) if error else None,
                    tool_call_id=call_id,
                ),
                agent_span_id=agent_span_id,
            )
        )

    return Trace(spans=spans, trace_id=trace_id, session_id=session_id)


def build_session(trial_dir: Path) -> tuple[Session, str]:
    """Build a native Session and return its final user-visible agent response."""
    trial_dir = trial_dir.expanduser().resolve()
    runtime_state = _load_json(trial_dir / "agent/tau3_runtime_state.json")
    trajectory = _load_json(trial_dir / "agent/trajectory.json")
    result = _load_json(trial_dir / "result.json")
    system_prompt = (trial_dir / "agent/instruction.txt").read_text(encoding="utf-8")
    messages = runtime_state.get("messages")
    if not isinstance(messages, list):
        raise ValueError("Tau3 runtime state does not contain a message list")

    session_id = str(trajectory.get("session_id") or trial_dir.name)
    available_tools = _tool_configs(trajectory)
    fallback_time = datetime.now(UTC)
    traces: list[Trace] = []
    current_user: dict[str, Any] | None = None
    pending_calls: dict[str, dict[str, Any]] = {}
    tool_observations: list[tuple[dict[str, Any], dict[str, Any]]] = []
    final_response = ""

    for message in messages:
        if not isinstance(message, dict):
            continue
        role = message.get("role")
        content = str(message.get("content") or "")

        if role == "user" and content:
            current_user = message
            pending_calls = {}
            tool_observations = []
            continue

        if role == "assistant" and message.get("tool_calls"):
            for raw_call in message["tool_calls"]:
                if isinstance(raw_call, dict):
                    call_id = str(raw_call.get("id") or "")
                    if call_id:
                        pending_calls[call_id] = {
                            **message,
                            "tool_calls": [raw_call],
                        }
            continue

        if role == "tool":
            call_id = str(message.get("id") or message.get("tool_call_id") or "")
            call_message = pending_calls.pop(call_id, None)
            if call_message is not None:
                tool_observations.append((call_message, message))
            continue

        if role == "assistant" and content and current_user is not None:
            if "###STOP###" not in content:
                traces.append(
                    _finalize_trace(
                        session_id=session_id,
                        turn=len(traces),
                        user_message=current_user,
                        assistant_message=message,
                        tool_observations=tool_observations,
                        available_tools=available_tools,
                        system_prompt=system_prompt,
                        fallback_time=fallback_time,
                    )
                )
                final_response = content
            current_user = None
            pending_calls = {}
            tool_observations = []

    if (
        not traces
        and current_user is not None
        and runtime_state.get("termination_reason") is None
        and (harbor_response := _harbor_final_response(result))
    ):
        traces.append(
            _finalize_trace(
                session_id=session_id,
                turn=0,
                user_message=current_user,
                assistant_message={
                    "role": "assistant",
                    "content": harbor_response,
                    "timestamp": result.get("finished_at"),
                },
                tool_observations=tool_observations,
                available_tools=available_tools,
                system_prompt=system_prompt,
                fallback_time=fallback_time,
            )
        )
        final_response = harbor_response

    if not traces:
        raise ValueError("Tau3 trial did not contain a complete user-to-agent turn")
    return Session(traces=traces, session_id=session_id), final_response
