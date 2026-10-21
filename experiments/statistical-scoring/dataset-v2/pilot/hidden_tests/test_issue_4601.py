import copy

import pytest
from strands.models.bedrock import BedrockModel


@pytest.mark.parametrize("tool_input", [None, "", 0, False, [], "invalid", ["value"]])
def test_non_dictionary_tool_input_is_normalized(tool_input):
    model = object.__new__(BedrockModel)
    content = {
        "toolUse": {
            "toolUseId": "tool-1",
            "name": "lookup",
            "input": tool_input,
        }
    }
    original = copy.deepcopy(content)

    formatted = model._format_request_message_content(content)

    assert formatted["toolUse"]["input"] == {}
    assert content == original


def test_dictionary_tool_input_is_preserved():
    model = object.__new__(BedrockModel)
    tool_input = {"query": "value"}

    formatted = model._format_request_message_content(
        {"toolUse": {"toolUseId": "tool-1", "name": "lookup", "input": tool_input}}
    )

    assert formatted["toolUse"]["input"] is tool_input
