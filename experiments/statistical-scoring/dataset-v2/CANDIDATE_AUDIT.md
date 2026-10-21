# Dataset v2 Candidate Audit

**Date:** 2026-09-29  
**Repository:** `strands-agents/harness-sdk`  
**Status:** Candidate selection complete; generation not started

## Objective

Expand the run-level evaluator dataset from 10 to 30 outer cases. More cases are needed because the
between-case variance and case-level bootstrap currently rely on only 10 independent sampling units.

The v1 dataset remains frozen. The additional data will be generated as a versioned v2 dataset
instead of appending rows to v1.

## Why v2 must be regenerated

The v1 artifacts do not record every resolved configuration needed to make new runs homogeneous,
including the exact agent model, default judge model, evaluator package version, and judge decoding
configuration. V2 should rerun the original 10 cases and generate the 20 additions under one explicit
configuration.

Target source-code commits may differ by case. Every case will record its own pre-fix base commit and
known fix commit, while the agent model, tools, run budget, evaluator implementations, and judge
configuration remain fixed across the dataset.

## Candidate pool

The GitHub audit queried closed issues in the official repository with the `bug` and `python` labels.
The tracker contained:

- 1,020 closed issues overall;
- 399 closed issues labeled both `bug` and `python`;
- 82 such issues closed since 2026-07-01;
- 35 manually screened candidates; and
- 20 selected additions.

Candidates were selected from issue and fix metadata only. No candidate was selected based on its
evaluator score or expected effect on the weighting results.

## Inclusion criteria

A selected issue must:

1. be a closed Python bug in the official repository;
2. have a merged pull request that resolves the issue;
3. change at least one file under `strands-py/src/`;
4. add or modify regression tests;
5. have a deterministic offline or mockable reproduction;
6. have a bounded task scope suitable for an isolated agent run;
7. provide enough issue and fix evidence to write a reference verdict; and
8. not duplicate one of the original 10 cases.

## Exclusion and deferral criteria

Issues were deferred when they:

- lacked a linked merged fix;
- were closed as not planned or could not be reproduced;
- depended on a live provider, account, platform, or external service with no mockable path;
- were primarily documentation, packaging, or test-only work;
- overlapped strongly with another selected defect; or
- required a broad redesign whose acceptance criteria could not be reduced to a focused task.

## Selected additions

All 20 selected fixes modify Python implementation code and regression tests.

| Rank | Issue | Area | Fix | Why it is useful |
|---:|---|---|---|---|
| 1 | [#4601](https://github.com/strands-agents/harness-sdk/issues/4601) | Model formatting | [PR #4625](https://github.com/strands-agents/harness-sdk/pull/4625) | Small deterministic normalization bug |
| 2 | [#4411](https://github.com/strands-agents/harness-sdk/issues/4411) | Multi-agent lifecycle | [PR #4580](https://github.com/strands-agents/harness-sdk/pull/4580) | Offline graph and hook ordering repro |
| 3 | [#4354](https://github.com/strands-agents/harness-sdk/issues/4354) | Agent limits | [PR #4355](https://github.com/strands-agents/harness-sdk/pull/4355) | Clear safety invariant and mocked model |
| 4 | [#4251](https://github.com/strands-agents/harness-sdk/issues/4251) | Structured output | [PR #4263](https://github.com/strands-agents/harness-sdk/pull/4263) | Focused forced-tool-choice contract |
| 5 | [#4220](https://github.com/strands-agents/harness-sdk/issues/4220) | Model metadata | [PR #4221](https://github.com/strands-agents/harness-sdk/pull/4221) | Pure lookup logic with exact expected values |
| 6 | [#4210](https://github.com/strands-agents/harness-sdk/issues/4210) | Telemetry | [PR #4222](https://github.com/strands-agents/harness-sdk/pull/4222) | Observable privacy and schema contract |
| 7 | [#4198](https://github.com/strands-agents/harness-sdk/issues/4198) | Sessions | [PR #4199](https://github.com/strands-agents/harness-sdk/pull/4199) | In-memory storage and canonical ID validation |
| 8 | [#4168](https://github.com/strands-agents/harness-sdk/issues/4168) | Model caching | [PR #4186](https://github.com/strands-agents/harness-sdk/pull/4186) | Deterministic request-construction behavior |
| 9 | [#4167](https://github.com/strands-agents/harness-sdk/issues/4167) | Agent result | [PR #4313](https://github.com/strands-agents/harness-sdk/pull/4313) | Direct serialization contract with bytes |
| 10 | [#4155](https://github.com/strands-agents/harness-sdk/issues/4155) | Skills | [PR #4192](https://github.com/strands-agents/harness-sdk/pull/4192) | Filesystem-only error handling and batch isolation |
| 11 | [#4135](https://github.com/strands-agents/harness-sdk/issues/4135) | Model streaming | [PR #4139](https://github.com/strands-agents/harness-sdk/pull/4139) | Fully mocked truncated tool-call stream |
| 12 | [#4113](https://github.com/strands-agents/harness-sdk/issues/4113) | Tool streaming | [PR #4195](https://github.com/strands-agents/harness-sdk/pull/4195) | Small zero-argument parsing boundary |
| 13 | [#4049](https://github.com/strands-agents/harness-sdk/issues/4049) | File editor | [PR #4182](https://github.com/strands-agents/harness-sdk/pull/4182) | Hermetic file mutation with exact byte output |
| 14 | [#4035](https://github.com/strands-agents/harness-sdk/issues/4035) | Model streaming | [PR #4036](https://github.com/strands-agents/harness-sdk/pull/4036) | Stubbed SSE framing with exact output |
| 15 | [#4017](https://github.com/strands-agents/harness-sdk/issues/4017) | Context offloading | [PR #4059](https://github.com/strands-agents/harness-sdk/pull/4059) | Silent data-loss bug with local fixtures |
| 16 | [#3910](https://github.com/strands-agents/harness-sdk/issues/3910) | Tool schemas | [PR #4426](https://github.com/strands-agents/harness-sdk/pull/4426) | Direct purity and mutation invariant |
| 17 | [#3718](https://github.com/strands-agents/harness-sdk/issues/3718) | Error classification | [PR #3722](https://github.com/strands-agents/harness-sdk/pull/3722) | Unit-testable provider error mapping |
| 18 | [#3623](https://github.com/strands-agents/harness-sdk/issues/3623) | Hooks and usage | [PR #3627](https://github.com/strands-agents/harness-sdk/pull/3627) | Scripted model and exact token accounting |
| 19 | [#3493](https://github.com/strands-agents/harness-sdk/issues/3493) | Context retrieval | [PR #3680](https://github.com/strands-agents/harness-sdk/pull/3680) | In-memory error-status contract |
| 20 | [#3425](https://github.com/strands-agents/harness-sdk/issues/3425) | Stream state | [PR #3472](https://github.com/strands-agents/harness-sdk/pull/3472) | Deterministic multi-block state leak |

## Recommended pilot

Generate these five cases first:

| Issue | Reason |
|---|---|
| #4601 | Small model-formatting task |
| #4411 | More complex graph lifecycle task |
| #4354 | Agent-level validation task |
| #4155 | Filesystem and exception-handling task |
| #3910 | Pure data-mutation task |

This pilot spans five subsystems and several difficulty levels without requiring live provider calls.
If the historical checkouts, hidden tests, prompts, sessions, and manifests are correct for the pilot,
the remaining 15 cases can use the same pipeline.

## Screened alternatives

| Issue | Disposition | Reason |
|---|---|---|
| #4191 | Alternate | Merged fix exists, but the catastrophic-regex repro can hang workers and the fix PR is broad |
| #4016 | Alternate | Strong deterministic case, but its merged fix landed after the initial audit query |
| #3068 | Alternate | Strong graph-resume case; reserve for replacing a failed selected case |
| #3063 | Alternate | Strong context-search case; overlaps the selected context-offloader cases |
| #2051 | Alternate | Merged fix exists, but overlaps the selected zero-argument JSON parsing case |
| #3144 | Alternate | Valid caching bug, but the merged fix is breaking and changes product policy |
| #4420 | Deferred | Closing pull request was not merged |
| #4338 | Deferred | Closing pull request was not merged |
| #4088 | Deferred | No linked merged fix |
| #4087 | Deferred | No linked merged fix |
| #4009 | Deferred | No linked merged fix |
| #4130 | Deferred | No linked merged fix and depends on MCP 2.x internals |
| #2296 | Deferred | No linked merged fix and the original repro depends on AgentCore Memory |
| #3628 | Rejected | Closed as not planned |
| #4542 | Deferred | Windows-specific path behavior requires a separate platform strategy |

## V2 generation requirements

Each generated case must freeze:

- issue number, URL, title, and prompt text;
- pre-fix base commit and known fix commit;
- source and regression-test files changed by the fix;
- prompt and reference-verdict hashes;
- resolved agent model and model parameters;
- Stan and harness-sdk commits;
- Python and package versions;
- built-in tool list and run timeout;
- evaluator names, versions, rubric hashes, and declared scales;
- judge model, temperature, and replay count;
- agent output, diff, session trace, test result, and failure classification.

Agents must run without web access and without repository git history that reveals the fix.

## Expected statistical effect

Moving from 10 to 30 cases does not guarantee narrow intervals, but it gives the between-case
variance and outer bootstrap three times as many independent units. The expanded case mix should also
reduce the current ceiling saturation if the selected issues produce a broader range of solution
quality.

The expanded dataset should validate the weighting method, not be selected to make any evaluator's
weight look more balanced.

