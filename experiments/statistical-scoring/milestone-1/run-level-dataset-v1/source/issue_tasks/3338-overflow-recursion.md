# Task

You are working in a full checkout of the strands-agents/harness-sdk monorepo (the Python SDK lives under `strands-py/`). A user filed the bug report below. It suggests three possible fix directions; choosing between them (or another approach) is a design decision — justify your choice.

Do all of the following:
1. Confirm the mechanism described in the report against the SDK source.
2. Implement a fix that guarantees the recovery loop terminates with an actionable error instead of a `RecursionError`.
3. Add a regression test that simulates a `reduce_context` that cannot shrink the context, failing before your fix and passing after it, and run it.

Rules: work only inside this repository; do not fetch anything from the internet; do not run `git commit` or `git push` — leave all changes in the working tree. Finish with a summary containing: the fix you chose and why (compared to the alternatives), what you changed, and how you verified it.

# Issue #3338: ContextWindowOverflowException recovery recurses without convergence check — non-terminating retry loop ending in RecursionError

### Summary

`Agent._execute_event_loop_cycle` handles `ContextWindowOverflowException` by calling `conversation_manager.reduce_context(e=e)` and then **recursing into itself with no attempt counter and no convergence check**. When `SummarizingConversationManager` cannot actually shrink the context, this recursion never terminates on its own — it runs until Python's recursion limit, ending in a `RecursionError` raised from the `copy.deepcopy(agent.messages)` in `_handle_model_execution`.

Observed in production: a single agent task produced **965 consecutive `ContextWindowOverflowException` model calls** (Bedrock ValidationException, 202,271–202,297 tokens — a 26-token band, i.e. the context never shrank between attempts), one cycle every 0.5–2s, terminated only by the `RecursionError`.

### Mechanism

1. `agent.py` — `_execute_event_loop_cycle`: `except ContextWindowOverflowException as e:` → `reduce_context(self, e=e)` → recursive call to `_execute_event_loop_cycle`. No bound, no check that anything shrank.
2. `summarizing_conversation_manager.py` — `_summarize_oldest` hard-protects the last `preserve_recent_messages` (default 10) messages, and `messages_to_summarize_count = max(1, int(len(messages) * summary_ratio))` means summarization always "succeeds" while `len(messages) > preserve_recent_messages` — it will happily re-summarize its own previous summary each round.
3. When the token mass sits **inside** the protected recent messages — e.g. one turn issued many parallel tool calls whose results each landed under the ContextOffloader's `max_result_tokens` but together pushed the conversation past the model window — each round replaces small old messages with a similar-sized summary. Net reduction ≈ 0. Overflow again. Recurse.
4. Each recursion adds nested generator frames; the eventual `RecursionError` surfaces from `copy.deepcopy(agent.messages)` in `_handle_model_execution`, masking the real problem.

Note `reduce_context`'s reactive contract ("MUST remove enough history for the next model call to succeed, or re-raise") is effectively unenforceable for the summarizing manager: it cannot know whether the summary is small enough, and it never re-raises as long as there is at least one unprotected message to fold into the summary.

### Reproduction sketch

- `SummarizingConversationManager()` defaults (`preserve_recent_messages=10`), any model with a hard context limit.
- Construct a conversation where the 10 most recent messages alone exceed the model's context window (e.g. one assistant turn with many toolUse blocks followed by large toolResult messages).
- Invoke the agent. Every cycle: overflow → `_summarize_oldest` folds oldest non-protected message(s) into a summary → total unchanged → overflow. Loop ends only at the recursion limit.

### Suggested fixes (any one of these breaks the loop)

1. Bound the reactive recovery: track consecutive `ContextWindowOverflowException` recoveries per invocation in `_execute_event_loop_cycle` and re-raise after N attempts.
2. Convergence check: after `reduce_context`, compare estimated tokens (the machinery from `_estimate_input_tokens` exists) and re-raise if the reduction made no progress.
3. Make the recursion a loop: the recursion also makes the eventual failure a `RecursionError` from deepcopy instead of the underlying overflow, which is materially harder to diagnose.
