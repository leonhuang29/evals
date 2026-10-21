# Task

You are working in a full checkout of the strands-agents/harness-sdk monorepo (the Python SDK lives under `strands-py/`). A user filed the bug report below. Some sections of the original report have been removed; you must find the root cause yourself.

Do all of the following:
1. Reproduce the problem from the report.
2. Find the root cause in the SDK source and explain the exact mechanism (file, function, and why field declaration order changes the result).
3. Implement a minimal fix.
4. Add a regression test that fails before your fix and passes after it (cover both declaration orders), and run it.

Rules: work only inside this repository; do not fetch anything from the internet; do not run `git commit` or `git push` — leave all changes in the working tree. Finish with a summary containing: the root cause (file and mechanism), what you changed, and how you verified it.

# Issue #4379: [BUG] `required` is dropped for a required nested-model field when that nested model's last-declared field is optional

### SDK Language

Python (pydantic 2.x)

### Steps to Reproduce

```python
from pydantic import BaseModel

from strands.tools.structured_output.structured_output_utils import convert_pydantic_to_tool_spec


class Inner(BaseModel):
    """Inner."""

    a: int
    b: str = "default"  # optional, declared last


class Outer(BaseModel):
    """Outer."""

    inner: Inner  # required nested model


produced = convert_pydantic_to_tool_spec(Outer)["inputSchema"]["json"]
print("produced required      :", produced.get("required"))
print("expected required      :", ["inner"])


# Same model, only the declaration order inside Inner differs.
class Inner2(BaseModel):
    """Inner."""

    b: str = "default"  # optional, declared first
    a: int


class Outer2(BaseModel):
    """Outer."""

    inner: Inner2


produced2 = convert_pydantic_to_tool_spec(Outer2)["inputSchema"]["json"]
print("reordered required     :", produced2.get("required"))
```

Run with a checkout of `strands-py/` on `PYTHONPATH`.

### Expected Behavior

`Outer.inner` is a required field (`inner: Inner`, no default), so the emitted tool `inputSchema.json` should carry `"required": ["inner"]`, matching what the same model produces when the last field declared inside `Inner` happens to be required. JSON Schema semantics: `required` lists the properties that must be present, and `inner` is required on `Outer` regardless of what `Inner` declares internally.

### Actual Behavior

The key `required` is omitted from the top-level schema entirely, so the model is told `inner` is optional. The nested `Inner` schema itself is emitted correctly.

Reproduction output (verbatim):

```
produced required      : None
expected required      : ['inner']
reordered required     : ['inner']
```

Only the declaration order of the fields inside `Inner` differs between the first and third lines of that output, and it flips `required` between absent and `["inner"]`.

Behavior across a matrix of shapes:

```
nested last=optional   -> required = None
nested last=required   -> required = ['inner']
two nested (opt,req)   -> required = ['b']
leaf only              -> required = ['x']
```

### Additional Context

Reachability: `convert_pydantic_to_tool_spec` is exported from `strands.tools`. It is called by `StructuredOutputTool.__init__` and directly by the structured-output configs for Bedrock, Anthropic and LiteLLM, so the malformed schema is what is sent to the model as the structured-output tool's input schema: the model is told a field the caller declared as required may be omitted.
