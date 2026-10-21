# Task

You are working in a full checkout of the strands-agents/harness-sdk monorepo (the Python SDK lives under `strands-py/`). Implement the feature request below in the Python SDK, following the repository's existing conventions.

Do all of the following:
1. Read the existing `MemoryManager`, its `search_memory` / `add_memory` tools, and the store interfaces, and follow their patterns.
2. Implement the feature with a minimal, focused change. The exact interface shape is open; justify your design decisions.
3. Add unit tests and run them.

Rules: work only inside this repository; do not fetch anything from the internet; do not run `git commit` or `git push` — leave all changes in the working tree. Finish with a summary of the design decisions you made, what you changed, and how you verified it.

# Issue #3577: [FEATURE] Add `delete_memory` / `forget_memory` tool to MemoryManager

### Problem Statement

The `MemoryManager` currently provides `search_memory` and `add_memory` tools for agents, but there is no way for an agent to delete or forget previously stored memories. Once a memory is written to a writable store (e.g., `BedrockKnowledgeBaseStore`), it persists indefinitely with no SDK-level mechanism to remove it.

This creates problems when:
- A user asks the agent to forget something they previously shared
- Memories become stale or incorrect and need to be removed
- Users want control over what personal data the agent retains (privacy/GDPR considerations)
- Extracted memories contain errors that the agent should be able to correct by deletion

### Proposed Solution

Add a `delete_memory` tool (or `forget_memory`) to the `MemoryManager` that:

1. Accepts a `memory_id` or `query` parameter to identify which memory to delete
2. Operates on writable stores only (similar to `add_memory`)
3. Delegates deletion to the store's backend (e.g., removing the S3 object and triggering a KB re-sync for `BedrockKnowledgeBaseStore`)

Example interface:

```python
# Agent-invocable tool
def delete_memory(memory_id: str, store: str | None = None) -> str:
    """Delete a specific memory from a writable store."""
    ...
```

The store interface would need a `delete` method. A `MemoryDeleteToolConfig` (similar to `MemoryAddToolConfig`) could control whether the tool is exposed to the agent.

### Use Case

1. **User-requested forgetting:** A user tells the agent "Forget that my favorite color is blue" — the agent should be able to remove that specific memory from the user's store.
2. **Privacy compliance:** Users request deletion of personal data. The agent can act on this immediately rather than requiring manual admin intervention.
3. **Memory correction:** Rather than adding a contradicting memory ("Actually my favorite color is NOT blue"), the agent can cleanly delete the incorrect one and optionally store the correction.
4. **Session cleanup:** An agent that stores temporary context as memories during a long task can clean up after itself.

### Alternatives Considered

1. **Overwrite with contradicting memory** — works today; accumulates stale data, relies on retrieval ranking, no actual deletion.
2. **Custom `@tool` wrapping the backing store's APIs** — works today; tightly couples to the store implementation, duplicates logic the SDK should own, different for every store backend.
3. **Admin API / out-of-band deletion** — not agent-driven, doesn't solve the in-conversation "forget this" use case.

### Additional Context

The `search_memory` tool already returns results that could include a memory identifier. This identifier could be passed to `delete_memory` to target a specific entry. The `add_memory` flow already handles writing and syncing, so the inverse operation should follow the same pattern.
