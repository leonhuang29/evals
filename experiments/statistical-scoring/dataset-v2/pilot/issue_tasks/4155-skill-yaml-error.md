# Task

You are working in a full checkout of the `strands-agents/harness-sdk` monorepo. The Python SDK is
under `strands-py/`.

Reproduce the reported behavior, identify the root cause, implement a minimal fix, add a regression
test that fails before the fix and passes afterward, and run the relevant tests.

Work only inside the repository. Do not fetch anything from the internet and do not commit or push.
Finish with a summary of the root cause, changes, and verification.

# Issue #4155: A malformed skill aborts loading its valid siblings

`Skill.from_content` documents `ValueError` for invalid frontmatter, but malformed YAML such as an
unterminated quote leaks a YAML parser exception:

```python
from strands.vended_plugins.skills.skill import Skill

bad = """---
name: bad-skill
description: "unterminated
---
Body
"""

Skill.from_content(bad)
```

This also breaks `Skill.from_directory`. That method is intended to skip one invalid skill and keep
loading valid sibling directories, but the unexpected exception escapes its per-skill error
handling.

Malformed frontmatter should honor the documented exception contract, and one invalid `SKILL.md`
must not prevent valid siblings from loading.
