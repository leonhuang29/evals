"""Shared registry for the harness-sdk issue tasks.

Each entry names a frozen task prompt under `issue_tasks/` and carries the mentor reference
verdict used as `expected_output` by the judge evaluators. The prompt files are the single
source of truth for case inputs: `stan_issue_runner.py` feeds them to Stan, and
`stan_issue_evals.py` reuses them verbatim so the judged input matches what the agent saw.

Redaction note: for the three diagnose-framed bugs (4394, 4337, 4379) the prompt files omit
the root-cause and suggested-fix sections of the original GitHub report, so the reference
below is information the agent did NOT see. For the rest, the report is included in full
(minus reporter boilerplate) and the grading weight shifts to fix quality and verification.
"""

TASKS: list[dict[str, str]] = [
    {
        "name": "4245-http-timeout",
        "kind": "bug-fix",
        "prompt_file": "issue_tasks/4245-http-timeout.md",
        # Easy anchor: near-certain success. Keep it to detect judge false positives / ceiling.
        "reference": (
            "The fix validates the timeout in the http_request vended tool's timeout resolution "
            "(strands-py, vended_tools/http_request): non-finite values (NaN, +/-infinity) are rejected "
            "with a clear error before any request is made, in addition to the existing zero/negative "
            "check (math.isfinite, consistent with the vended sleep tool). A regression test covers NaN, "
            "positive infinity, and negative infinity, and the test was run and passes."
        ),
    },
    {
        "name": "4394-bedrock-read-timeout",
        "kind": "bug-diagnose",
        "prompt_file": "issue_tasks/4394-bedrock-read-timeout.md",
        "reference": (
            "Root cause: in BedrockModel.__init__ (strands-py/src/strands/models/bedrock.py) the default "
            "read timeout DEFAULT_READ_TIMEOUT (120s) is applied only on the branch where no "
            "boto_client_config is provided. The custom-config branch layers user_agent_extra and "
            "signature_version on top of the caller's botocore Config but not the read timeout, so any "
            "caller-provided config (even an empty one) falls back to botocore's 60s default. "
            "Correct fix: when the caller's config does not set read_timeout, layer DEFAULT_READ_TIMEOUT "
            "onto it; an explicit caller value (including None) must win. A regression test constructs "
            "BedrockModel with an empty/partial boto_client_config and asserts read_timeout == 120, and "
            "with an explicit read_timeout asserting the explicit value wins."
        ),
    },
    {
        "name": "4337-async-callable-hooks",
        "kind": "bug-diagnose",
        "prompt_file": "issue_tasks/4337-async-callable-hooks.md",
        "reference": (
            "Root cause: HookRegistry (strands-py/src/strands/hooks/registry.py) decides sync-vs-async "
            "dispatch with inspect.iscoroutinefunction(callback), which is False for a callable object "
            "whose __call__ is async def; the async path is skipped and the returned coroutine is "
            "discarded. Correct fix: detect async callables robustly (also inspect __call__, or invoke "
            "once and await the result if inspect.isawaitable says so), keeping sync callback behavior "
            "and interrupt aggregation intact, and making the synchronous dispatch path handle such "
            "hooks consistently (await is impossible there, so it should raise or warn rather than "
            "silently drop). A regression test registers a callable object with async __call__ and "
            "asserts the hook body ran with no 'never awaited' warning."
        ),
    },
    {
        "name": "4004-text-dropped-tooluse",
        "kind": "bug-fix",
        "prompt_file": "issue_tasks/4004-text-dropped-tooluse.md",
        "reference": (
            "The fix changes handle_content_block_stop in strands-py/src/strands/event_loop/streaming.py "
            "so co-pending content types are all appended instead of the elif chain keeping only one: "
            "when both current_tool_use and text are pending, both blocks land in the assistant message "
            "with the text preamble ordered before the toolUse block, and both state slots are cleared. "
            "A strong answer also addresses (or explicitly considers) the analogous co-pending "
            "reasoning-text branch in the same chain. A regression test exercises the both-pending state "
            "and asserts both blocks and their order; the test was run and passes."
        ),
    },
    {
        "name": "4379-nested-required-dropped",
        "kind": "bug-diagnose",
        "prompt_file": "issue_tasks/4379-nested-required-dropped.md",
        "reference": (
            "Root cause: in strands-py/src/strands/tools/structured_output/structured_output_utils.py, "
            "the schema flattening loop (_flatten_schema) reuses the outer property's is_required local "
            "while iterating the nested model's sub-properties, so after processing a nested model whose "
            "last-declared field is optional the clobbered value makes the parent drop the nested field "
            "from the top-level required list. Correct fix: compute the nested sub-property's "
            "required-ness in its own local so the outer is_required survives to the point where the "
            "parent's required list is assembled; Outer must emit required=['inner'] regardless of field "
            "declaration order inside Inner. A regression test covers both declaration orders and was run."
        ),
    },
    {
        "name": "4341-sliding-window-truncation",
        "kind": "bug-fix",
        "prompt_file": "issue_tasks/4341-sliding-window-truncation.md",
        "reference": (
            "Root cause: SlidingWindowConversationManager's overflow recovery only attempts truncation "
            "on the oldest toolResult-bearing message; if that one is small or already truncated it falls "
            "through to trimming messages even when newer messages hold large truncatable results. "
            "An acceptable fix walks toolResult messages (oldest to newest) and truncates the first one "
            "where truncation actually changes something, falling back to trimming only when none can be "
            "truncated; other scopes (e.g. truncating all large results) are acceptable if justified and "
            "the documented contract ('truncate large tool results first, oldest first') is restored. "
            "The issue's repro must now output '6 0 / 443' (large result truncated, no messages removed). "
            "A regression test based on that repro was added and run."
        ),
    },
    {
        "name": "3338-overflow-recursion",
        "kind": "bug-fix",
        "prompt_file": "issue_tasks/3338-overflow-recursion.md",
        "reference": (
            "The fix bounds the ContextWindowOverflowException recovery in Agent._execute_event_loop_cycle "
            "so it terminates deterministically: an attempt counter that re-raises after N consecutive "
            "recoveries, a convergence check that re-raises when reduce_context made no progress "
            "(estimated tokens did not shrink), converting the recursion into a loop, or a combination. "
            "Any of these is acceptable if justified against the alternatives; the failure surfaced must "
            "be the underlying overflow error (actionable), never a RecursionError from deepcopy. A "
            "regression test simulates a reduce_context that cannot shrink the context and asserts the "
            "loop ends with the overflow error after a bounded number of attempts; the test was run."
        ),
    },
    {
        "name": "3577-delete-memory-tool",
        "kind": "feature",
        "prompt_file": "issue_tasks/3577-delete-memory-tool.md",
        "reference": (
            "A delete_memory (or forget_memory) agent tool on MemoryManager following the existing "
            "search_memory/add_memory patterns: targets writable stores only, identifies the memory by "
            "the identifier surfaced in search results (a query-based variant is acceptable if justified), "
            "delegates deletion to a new delete method on the store interface, fails gracefully on "
            "read-only stores, and exposes a config toggle mirroring the add-tool config. Unit tests "
            "exercise the tool against an in-repo store implementation (deleting an existing memory, "
            "deleting a missing id, read-only store rejection) and were run."
        ),
    },
    {
        "name": "4262-loop-guard-plugin",
        "kind": "feature",
        "prompt_file": "issue_tasks/4262-loop-guard-plugin.md",
        "reference": (
            "A vended plugin (e.g. loop_guard) under strands-py/src/strands/vended_plugins/ built only on "
            "public hooks: BeforeToolsEvent computes an order-insensitive signature of the tool batch "
            "(sorted JSON of {name, input}, ids ignored) and counts repeats in invocation_state; "
            "AfterToolsEvent appends a nudge text block to the tool-result message on the first repeat "
            "and ends the turn (end_turn) on the second; nudge_after/stop_after thresholds and both texts "
            "configurable ({tools} placeholder), with an ignore list for non-idempotent tools; the "
            "assistant message is never edited. Tests drive a real Agent with a scripted model and a real "
            "@tool covering: nudge placement, end_turn on second repeat with exactly three model calls, "
            "different batch not a repeat, shuffled batch is a repeat, stop_after=None nudges only. "
            "Tests were run."
        ),
    },
    {
        "name": "2951-get-plugin-api",
        "kind": "feature",
        "prompt_file": "issue_tasks/2951-get-plugin-api.md",
        "reference": (
            "A public, typed getter on both Agent and Graph returning a registered plugin instance by "
            "type, e.g. get_plugin(SomePlugin) -> SomePlugin | None (a get_plugins() list is an acceptable "
            "companion or alternative if justified), implemented consistently on both classes without "
            "requiring consumers to touch private attributes, scoped to plugins only (no callback "
            "exposure). Type hints make the return type narrow to the requested plugin class. Unit tests "
            "cover both Agent and Graph (found, not-found, and subclass lookup behavior stated one way or "
            "the other) and were run."
        ),
    },
]

TASKS_BY_NAME = {task["name"]: task for task in TASKS}
