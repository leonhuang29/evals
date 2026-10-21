# Task

You are working in a full checkout of the strands-agents/harness-sdk monorepo (the Python SDK lives under `strands-py/`). Implement the feature request below in the Python SDK, following the repository's existing conventions for vended plugins.

Do all of the following:
1. Read the existing vended plugins under `strands-py/src/strands/vended_plugins/` and the hook events the proposal names, and follow their patterns.
2. Implement the plugin with a minimal, focused change.
3. Add unit tests that drive a real `strands.Agent` through the event loop with a scripted model and a real `@tool`, and run them.

Rules: work only inside this repository; do not fetch anything from the internet; do not run `git commit` or `git push` — leave all changes in the working tree. Finish with a summary of the design decisions you made, what you changed, and how you verified it.

# Issue #4262: [FEATURE] Vended plugin that detects a repeated tool batch and nudges, then ends the turn

### SDK Language

Python

### Problem Statement

An agent sometimes asks for exactly the same batch of tool calls it already made: same tool names, same inputs. The results are already in the conversation, so the repeat spends a full cycle for nothing, and a model that has started circling often repeats again until the turn or token limit fires. `Limits(turns=...)` caps the damage but cannot tell a productive cycle from a wasted one. There is nothing in the SDK today that notices a repeated batch.

### Proposed Solution

A small vended plugin, built entirely on public hooks, that ships next to the existing ones in `strands-py/src/strands/vended_plugins/`:

- `BeforeToolsEvent`: compute a signature of the batch from the assistant message (sorted JSON of `{name, input}` per `toolUse` block; order insensitive, tool use ids ignored) and count a repeat in `invocation_state`. A per-tool interrupt re-fires this event with the same assistant message, so the same message object is counted once.
- `AfterToolsEvent`: on the first repeat, append a short text block to `event.message["content"]`, the user-role tool-result message, so the model reads the note directly under the results it already has. On the second repeat, set `event.end_turn` to a final text, so the run ends with `stop_reason == "end_turn"` instead of burning the remaining budget.
- Two thresholds, `nudge_after=1` and `stop_after=2` (`None` for nudge only), and both texts configurable with a `{tools}` placeholder.
- Non-idempotent tools (live readings, clocks) are excluded by name through `ignore`.

```python
from strands import Agent
from strands.vended_plugins.loop_guard import LoopGuard

agent = Agent(tools=[...], plugins=[LoopGuard()])
```

Nothing inside the event loop changes. State lives in `invocation_state`, so it resets per invocation and survives interrupt and resume without plugin-side memory. The guard never edits the assistant message, only the tool-result message and `end_turn`, so it is provider neutral.

Suggested test coverage: the note is the text block of the second tool-result turn; the second repeat ends with `end_turn` and the model is called three times, not four; a different batch is not a repeat; the same batch with calls shuffled is a repeat; `stop_after=None` nudges and lets the model finish; a batch split by an interrupt is counted once.

### Use Case

A production AI-mechanic agent runs a tool loop over logged vehicle drives (sensor series, stored codes, freeze frames) and has carried this guard in production. In one week, 11 of 90 jobs repeated a tool batch at least once, and 3 chat runs were stopped by the guard. Two real traces:

- A chat run: 7 rounds, two repeats (`get_sensor_series` re-requested identically at call 2, then a second series at call 5), stopped by the guard. The first repeat re-issued a call whose result had been `error: unknown pidId`, so the model was retrying a failing call verbatim; the note is what broke that.
- A health check: 8 rounds, two repeats (`get_session_stats`, then `get_sensor_series`), nudged both times, and the structured report still landed.

The same need shows up for any agent with read-only data tools, where a repeat is always a wasted cycle.

### Alternatives Considered

- `Limits(turns=...)`: stops runaway loops but only at the cap, and cannot distinguish a repeat from useful work.
- A `Guide` intervention on `before_model_call`: injects a separate user message rather than a note inside the tool-result turn, and the docstring says it bypasses session management.
