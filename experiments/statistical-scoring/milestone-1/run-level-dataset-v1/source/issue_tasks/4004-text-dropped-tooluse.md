# Task

You are working in a full checkout of the strands-agents/harness-sdk monorepo (the Python SDK lives under `strands-py/`). A user filed the bug report below.

Do all of the following:
1. Reproduce the problem from the report.
2. Confirm the defect in the SDK source.
3. Implement a fix. Think about the ordering of content blocks in the resulting assistant message, and about whether other co-pending content-type pairs in the same handler have the same defect.
4. Add a regression test that fails before your fix and passes after it, and run it.

Rules: work only inside this repository; do not fetch anything from the internet; do not run `git commit` or `git push` — leave all changes in the working tree. Finish with a summary containing: the root cause, what you changed and why, and how you verified it.

# Issue #4004: Text content block is silently dropped when a toolUse is pending in the same content block stop

### Summary

`handle_content_block_stop` in `strands-py/src/strands/event_loop/streaming.py` uses an `elif` chain, so when a content block stops with **both** a pending `current_tool_use` **and** accumulated `text`, the text is silently discarded — never appended to the assistant message, and left stranded in `state["text"]`.

This is the same defect class as #1394 (reasoning vs. text), for a different pair of branches.

### Current code (`main`)

```python
if current_tool_use:
    ...
    content.append({"toolUse": tool_use})
    state["current_tool_use"] = {}

elif text:                       # <-- elif
    ...
    content.append({"text": text})
    state["text"] = ""

elif reasoning_text or "signature" in state:
    ...
```

### Reproduction

Calling the real function with both a tool use and text pending:

```python
from strands.event_loop.streaming import handle_content_block_stop

# A. text alone — works
state = {"content": [], "current_tool_use": {}, "text": "Let me check that for you.",
         "reasoningText": "", "citationsContent": [], "redactedContent": None}
handle_content_block_stop(state)
# content -> [{'text': 'Let me check that for you.'}]      leftover text -> ''

# B. text AND a pending tool use — text is dropped
state = {"content": [],
         "current_tool_use": {"toolUseId": "t1", "name": "read_file", "input": "{}"},
         "text": "Let me check that for you.",
         "reasoningText": "", "citationsContent": [], "redactedContent": None}
handle_content_block_stop(state)
# content -> [{'toolUse': {...}}]                          leftover text -> 'Let me check that for you.'
#                                                          ^ never appended, never cleared
```

### Why it matters

A model that streams a short preamble and then calls a tool in the same assistant turn ("Let me check that for you." → `toolUse`) has that preamble delivered to the client but **absent from the assistant message in conversation history**. Every later reader of that history — a subsequent model pass, a session snapshot/restore, a transcript view, a replay — sees a turn in which the assistant said nothing before calling the tool.

The dropped-text path is real and demonstrable by executing the function; how often a given provider hits it depends on whether that provider emits the text in its own content block before opening the tool block.

### Precedent

- #1394 — same `elif` chain, reasoning vs. text.
- #1395 — changed the branches to independent `if` statements. Reviewed positively as a "foundational fix that benefits all providers", then closed unmerged.
- #1557 — merged, but it only changes `models/gemini.py` so that provider never emits both types at one `contentBlockStop`. The generic `elif` in `streaming.py` was not touched.

So the reasoning-vs-text case was resolved provider-side, and the generic handler still drops one of two co-pending content types. The `current_tool_use` vs `text` pair has no provider-side mitigation.
