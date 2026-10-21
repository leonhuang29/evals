import pytest
from strands import Agent
from strands.hooks import AfterMultiAgentInvocationEvent
from strands.multiagent import GraphBuilder
from tests.fixtures.mocked_model_provider import MockedModelProvider


@pytest.mark.asyncio
async def test_after_hook_runs_before_terminal_result_with_invocation_state():
    model = MockedModelProvider([{"role": "assistant", "content": [{"text": "done"}]}])
    agent = Agent(model=model, callback_handler=None)
    builder = GraphBuilder()
    builder.add_node(agent, "only")
    builder.set_entry_point("only")
    graph = builder.build()

    invocation_state = {"request_id": "pilot"}
    after_events = []
    graph.add_hook(lambda event: after_events.append(event), AfterMultiAgentInvocationEvent)

    stream = graph.stream_async("run", invocation_state=invocation_state)
    try:
        async for event in stream:
            if "result" not in event:
                continue
            assert len(after_events) == 1
            assert after_events[0].invocation_state is invocation_state
            assert event["result"].execution_time == graph.state.execution_time
            break
        else:
            pytest.fail("Graph did not yield a terminal result")
    finally:
        await stream.aclose()

    assert len(after_events) == 1
