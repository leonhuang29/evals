# Task

You are working in a full checkout of the strands-agents/harness-sdk monorepo (the Python SDK lives under `strands-py/`). A user filed the bug report below. Some sections of the original report have been removed; you must find the root cause yourself.

Do all of the following:
1. Reproduce the problem from the report.
2. Find the root cause in the SDK source and explain the exact mechanism (file, function, and why it misbehaves).
3. Implement a minimal fix.
4. Add a regression test that fails before your fix and passes after it, and run it.

Rules: work only inside this repository; do not fetch anything from the internet; do not run `git commit` or `git push` — leave all changes in the working tree. Finish with a summary containing: the root cause (file and mechanism), what you changed, and how you verified it.

# Issue #4394: [BUG] BedrockModel drops the default read timeout when boto_client_config is provided

### SDK Language

Python

### Steps to Reproduce

No AWS call is made; the client is only constructed and its resolved config inspected.

```python
from botocore.config import Config as BotocoreConfig
from strands.models import BedrockModel


def read_timeout(**kwargs):
    return BedrockModel(region_name="us-east-1", **kwargs).client.meta.config.read_timeout


print(read_timeout())                                                                  # 120
print(read_timeout(boto_client_config=BotocoreConfig()))                               # 60
print(read_timeout(boto_client_config=BotocoreConfig(retries={"max_attempts": 3})))    # 60
print(read_timeout(boto_client_config=BotocoreConfig(connect_timeout=5)))              # 60
print(read_timeout(boto_client_config=BotocoreConfig(read_timeout=900)))               # 900
```

### Expected Behavior

`read_timeout` is `DEFAULT_READ_TIMEOUT` (120 seconds) whenever the caller did not set one, with or without a `boto_client_config`. An explicit value, including `None`, wins.

### Actual Behavior

Any `boto_client_config`, even an empty one, drops the client to botocore's default of 60 seconds. Passing a config only to set `retries` or `connect_timeout` silently halves the read timeout.
