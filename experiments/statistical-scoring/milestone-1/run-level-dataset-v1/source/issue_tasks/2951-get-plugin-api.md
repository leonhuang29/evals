# Task

You are working in a full checkout of the strands-agents/harness-sdk monorepo (the Python SDK lives under `strands-py/`). Implement the feature request below in the Python SDK, following the repository's existing conventions.

Do all of the following:
1. Read how plugins are registered on `Agent` and `Graph` today.
2. Implement the feature with a minimal, focused change. The exact API shape is open; justify your design decision.
3. Add unit tests covering both `Agent` and `Graph`, and run them.

Rules: work only inside this repository; do not fetch anything from the internet; do not run `git commit` or `git push` — leave all changes in the working tree. Finish with a summary of the design decisions you made, what you changed, and how you verified it.

# Issue #2951: [FEATURE] Public API to retrieve registered plugins from Agent / Graph

### SDK Language

Python

### Problem Statement

There is currently no public API to retrieve the plugin instances registered on an Agent or Graph. Consumers that need to look up a specific plugin attached to an agent/graph have to reach into private internals to do it, which is brittle and breaks across releases when those internals change shape.

### Proposed Solution

Add a public getter on both Agent and Graph that returns a registered plugin instance by type:

```
agent.get_plugin(SomePlugin) -> SomePlugin | None
graph.get_plugin(SomePlugin) -> SomePlugin | None
```

A method to list all registered plugins would also work:

```
agent.get_plugins() -> list[Plugin]
graph.get_plugins() -> list[Plugin]
```

Exact shape is open to whatever fits the SDK best. The key need is retrieving the plugin instance, not just a boolean of whether one is attached.

Scope is intentionally limited to plugins. This does not expose registered callbacks directly.

### Use Case

We build a plugin that customers attach to their own Agent and Graph objects. At runtime we need to retrieve our plugin's reference from the customer's agent/graph to validate it is properly attached before we rely on it. A public, type-based getter gives us a stable way to do this without depending on SDK internals.
