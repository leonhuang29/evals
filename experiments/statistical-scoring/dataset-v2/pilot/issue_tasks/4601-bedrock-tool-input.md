# Task

You are working in a full checkout of the `strands-agents/harness-sdk` monorepo. The Python SDK is
under `strands-py/`.

Reproduce the reported behavior, identify the root cause, implement a minimal fix, add a regression
test that fails before the fix and passes afterward, and run the relevant tests.

Work only inside the repository. Do not fetch anything from the internet and do not commit or push.
Finish with a summary of the root cause, changes, and verification.

# Issue #4601: Bedrock rejects replayed tool-use blocks with malformed input

`BedrockModel` can replay a conversation containing a tool-use block whose `input` is `None`, an
empty string, a list, or another non-object value. This can occur with tools that have no required
arguments.

On the next Converse request, Bedrock rejects the history with an error similar to:

```text
ValidationException: The value at messages.N.content.M.toolUse.input is empty
```

or:

```text
... is invalid. Provide a json object for the field and try again.
```

The formatter should emit an empty JSON object for malformed or non-dictionary tool input. Valid
dictionary input, including an empty dictionary, must remain unchanged. Formatting must not mutate
the original message.
