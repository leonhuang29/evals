# Task

You are working in a full checkout of the `strands-agents/harness-sdk` monorepo. The Python SDK is
under `strands-py/`.

Reproduce the reported behavior, identify the root cause, implement a minimal fix, add a regression
test that fails before the fix and passes afterward, and run the relevant tests.

Work only inside the repository. Do not fetch anything from the internet and do not commit or push.
Finish with a summary of the root cause, changes, and verification.

# Issue #4354: Unknown agent limit names silently leave an invocation uncapped

The per-invocation `limits` argument accepts recognized caps such as `turns`, `output_tokens`, and
`total_tokens`. Invalid values for those caps already raise `TypeError`.

An unrecognized key such as `max_turns`, however, is accepted without an error:

```python
await agent.invoke_async("go", limits={"max_turns": 3})
```

No cap is applied, even though the caller reasonably believes the invocation is bounded. This is a
safety and cost risk for loops that continue requesting tools.

Unknown keys should fail before any model work begins. Valid keys and their existing value
validation must keep working.
