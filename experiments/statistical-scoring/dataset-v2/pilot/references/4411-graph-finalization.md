The defect is in `Graph.stream_async` in `strands-py/src/strands/multiagent/graph.py`. The terminal
result is built and yielded inside the `try`, so the async generator suspends before its `finally`
block commits execution time and invokes `AfterMultiAgentInvocationEvent`. The event is also
constructed without the active `invocation_state`. The fix should finalize the invocation in the
`finally` block, pass the state to the event, and only then build and yield the terminal result.
Regression coverage should verify ordering and state identity, while preserving cleanup on errors
and explicit stream closure.
