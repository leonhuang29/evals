# Task

You are working in a full checkout of the `strands-agents/harness-sdk` monorepo. The Python SDK is
under `strands-py/`.

Reproduce the reported behavior, identify the root cause, implement a minimal fix, add a regression
test that fails before the fix and passes afterward, and run the relevant tests.

Work only inside the repository. Do not fetch anything from the internet and do not commit or push.
Finish with a summary of the root cause, changes, and verification.

# Issue #3910: Schema normalization mutates caller-owned dictionaries

The schema normalization helpers should return normalized values without changing their inputs:

```python
from strands.tools import normalize_schema, normalize_tool_spec

schema = {"type": "object", "properties": {"name": {}}}
normalize_schema(schema)
print(schema)

tool_spec = {
    "name": "demo",
    "description": "demo",
    "inputSchema": {
        "json": {"type": "object", "properties": {"query": {}}},
        "extra": "preserve-me",
    },
}
normalize_tool_spec(tool_spec)
print(tool_spec)
```

Both calls currently write defaults into nested dictionaries owned by the caller. The returned
normalized values should retain existing behavior and preserve sibling `inputSchema` fields, while
the original inputs remain byte-for-byte equivalent as Python values.
