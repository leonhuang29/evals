# Task

You are working in a full checkout of the strands-agents/harness-sdk monorepo (the Python SDK lives under `strands-py/`). A user filed the bug report below. Some sections of the original report have been removed; you must find the root cause yourself.

Do all of the following:
1. Reproduce the problem from the report.
2. Find the root cause in the SDK source and explain the exact mechanism (file, function, and why it misbehaves).
3. Implement a minimal fix. Consider carefully how the synchronous dispatch path should treat such hooks.
4. Add a regression test that fails before your fix and passes after it, and run it.

Rules: work only inside this repository; do not fetch anything from the internet; do not run `git commit` or `git push` — leave all changes in the working tree. Finish with a summary containing: the root cause (file and mechanism), what you changed, and how you verified it.

# Issue #4337: [BUG] Async callable object hooks are not awaited

### SDK Language

Python

### Description

A callable object whose `__call__` method is `async def` can be registered as a hook, but when the callbacks are invoked the hook body never runs and Python reports that its coroutine was never awaited.

This conflicts with the `HookCallback` protocol, which permits `Awaitable[None]`, and with `Agent.add_hook()`, which documents support for asynchronous callbacks.

### Steps to reproduce

Run this offline from the Python SDK development environment:

```python
import asyncio
import gc
import warnings
from unittest.mock import Mock

from strands.hooks import BeforeInvocationEvent, HookRegistry


class AsyncCallableHook:
    def __init__(self) -> None:
        self.call_count = 0

    async def __call__(self, event: BeforeInvocationEvent) -> None:
        self.call_count += 1


async def main() -> None:
    registry = HookRegistry()
    callback = AsyncCallableHook()
    registry.add_callback(BeforeInvocationEvent, callback)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", RuntimeWarning)
        await registry.invoke_callbacks_async(
            BeforeInvocationEvent(agent=Mock(), invocation_state={})
        )
        gc.collect()

    print(callback.call_count)
    print([str(item.message) for item in caught])


asyncio.run(main())
```

Observed output:

```text
0
["coroutine 'AsyncCallableHook.__call__' was never awaited"]
```

The same result occurs when the callback is registered through `Agent.add_hook()` and an offline mock model is invoked: the Agent completes, but the hook body is skipped.

### Expected behavior

Async hook callbacks should be awaited regardless of whether they are async functions, bound async methods, or callable objects with an async `__call__`.

### Impact

State updates, validation, telemetry, cleanup, or intervention logic placed in such a hook can be silently skipped while the Agent continues running. The only signal may be a runtime warning. This affects hook dispatch across the Agent lifecycle because lifecycle events share `HookRegistry`.
