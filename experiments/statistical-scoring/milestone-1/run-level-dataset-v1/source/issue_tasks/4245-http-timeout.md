# Task

You are working in a full checkout of the strands-agents/harness-sdk monorepo (the Python SDK lives under `strands-py/`). A user filed the bug report below.

Do all of the following:
1. Reproduce the problem from the report.
2. Confirm the root cause in the SDK source.
3. Implement a minimal fix.
4. Add a regression test that fails before your fix and passes after it, and run it.

Rules: work only inside this repository; do not fetch anything from the internet; do not run `git commit` or `git push` — leave all changes in the working tree. Finish with a summary containing: the root cause (file and mechanism), what you changed, and how you verified it.

# Issue #4245: [BUG] http_request accepts NaN and infinite timeout values

### SDK Language

Python

### Steps to Reproduce

Run the following against the current Python SDK:

```python
import asyncio
import math

import httpx

from strands.vended_tools.http_request.http_request import make_http_request


async def main():
    async def handler(request: httpx.Request) -> httpx.Response:
        print(request.extensions["timeout"])
        return httpx.Response(200, text="ok")

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        timeout=None,
    )
    try:
        tool = make_http_request(client=client)
        for timeout in (math.nan, math.inf):
            result = await tool(
                method="GET",
                url="https://example.com",
                timeout=timeout,
            )
            print(timeout, result["status"])
    finally:
        await client.aclose()


asyncio.run(main())
```

Output:

```text
{'connect': nan, 'read': nan, 'write': nan, 'pool': nan}
nan 200
{'connect': inf, 'read': inf, 'write': inf, 'pool': inf}
inf 200
```

### Expected Behavior

The HTTP request tool should reject non-finite timeout values before making the request, just as it rejects zero and negative values. A timeout should be finite and greater than zero.

### Actual Behavior

`math.nan` and `math.inf` pass validation and are forwarded to all four HTTPX timeout phases (`connect`, `read`, `write`, and `pool`). This can silently defeat the intended timeout cap or produce transport-dependent behavior.

### Additional Context

`_resolve_timeout()` currently checks only `model_timeout <= 0`. That comparison is false for `NaN`, while positive infinity also passes. The vendored `sleep` tool already uses `math.isfinite()` when validating its duration, so applying the same constraint here would make timeout handling consistent.
