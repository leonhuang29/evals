# Task

You are working in a full checkout of the `strands-agents/harness-sdk` monorepo. The Python SDK is
under `strands-py/`.

Reproduce the reported behavior, identify the root cause, implement a minimal fix, add a regression
test that fails before the fix and passes afterward, and run the relevant tests.

Work only inside the repository. Do not fetch anything from the internet and do not commit or push.
Finish with a summary of the root cause, changes, and verification.

# Issue #4411: Graph exposes its terminal result before invocation cleanup

`Graph.stream_async()` can yield its terminal result before
`AfterMultiAgentInvocationEvent` hooks have run. A streaming caller that stops when it receives the
result therefore observes a completed graph while cleanup is still pending.

The after-invocation event also does not receive the same `invocation_state` object supplied to the
graph.

The following lifecycle must hold:

1. Before the terminal result is yielded, after-invocation hooks have run exactly once.
2. The after-invocation event carries the active `invocation_state`.
3. Errors and explicitly closed partial streams still invoke the after hook.
4. If cleanup itself fails, a successful terminal result must not be exposed.

No live model service or API key should be needed to reproduce or test the problem.
