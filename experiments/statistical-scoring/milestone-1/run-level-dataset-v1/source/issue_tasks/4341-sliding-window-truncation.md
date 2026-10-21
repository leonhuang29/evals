# Task

You are working in a full checkout of the strands-agents/harness-sdk monorepo (the Python SDK lives under `strands-py/`). A user filed the bug report below.

Do all of the following:
1. Reproduce the problem from the report.
2. Confirm the defect in the SDK source.
3. Decide on and implement a fix. The right scope of the fix is a design decision; justify yours.
4. Add a regression test that fails before your fix and passes after it, and run it.

Rules: work only inside this repository; do not fetch anything from the internet; do not run `git commit` or `git push` — leave all changes in the working tree. Finish with a summary containing: the root cause, the fix you chose and why, and how you verified it.

# Issue #4341: [BUG] SlidingWindowConversationManager trims messages on overflow when only the oldest tool result is untruncatable, leaving newer large results intact

### SDK Language

Python

### Steps to Reproduce

`SlidingWindowConversationManager.reduce_context()` documents that on a context overflow it "attempts to truncate large tool results first before falling back to message trimming", and that "truncation targets the oldest tool results first". In practice it only ever looks at the **oldest** message that contains a `toolResult`. If that result is small (under 400 characters) or was already truncated by an earlier overflow, `_truncate_tool_results` returns `False` and the manager falls straight through to trimming messages, even when a newer message holds a very large tool result that would have been truncated.

No model call needed:

```python
from unittest.mock import MagicMock
from strands.agent.conversation_manager import SlidingWindowConversationManager

def tool_turn(i, result_text):
    return [
        {"role": "assistant", "content": [{"toolUse": {"toolUseId": f"t{i}", "name": "tool", "input": {}}}]},
        {"role": "user", "content": [{"toolResult": {"toolUseId": f"t{i}", "status": "success", "content": [{"text": result_text}]}}]},
    ]

messages = (
    [{"role": "user", "content": [{"text": "hi"}]}]
    + tool_turn(1, "OK")            # small result, cannot be truncated
    + tool_turn(2, "X" * 20000)     # large result, the actual overflow cause
    + [{"role": "assistant", "content": [{"text": "done"}]}]
)
agent = MagicMock(); agent.messages = messages
manager = SlidingWindowConversationManager(window_size=40)

manager.reduce_context(agent, e=Exception("context overflow"))

print(len(messages), manager.removed_message_count)
print(max(len(c["toolResult"]["content"][0]["text"]) for m in messages for c in m["content"] if "toolResult" in c))
```

### Expected Behavior

The 20,000-character tool result is truncated and no messages are removed. Output:

```
6 0
443
```

### Actual Behavior

The first three messages (including the user's original prompt) are discarded and the large result is untouched:

```
3 3
20000
```

The same happens on the second overflow of a conversation with two large results: the first overflow truncates the oldest one, the second overflow finds it already truncated and trims messages instead of truncating the second.

### Additional Context

This is the common case for tool-heavy agents: early tool calls usually return short confirmations, and the result that actually blows the context window is a later one (a fetched page, a file read). With the current behaviour the overflow recovery throws away the start of the conversation while keeping the oversized payload, and only truncates it on the following overflow.
