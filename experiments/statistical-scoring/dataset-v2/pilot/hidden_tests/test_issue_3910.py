import copy

from strands.tools import normalize_schema, normalize_tool_spec


def test_normalize_schema_does_not_mutate_input():
    schema = {
        "type": "object",
        "properties": {
            "name": {},
            "user": {"type": "object", "properties": {"id": {}}},
        },
    }
    original = copy.deepcopy(schema)

    normalized = normalize_schema(schema)

    assert schema == original
    assert normalized["properties"]["name"]["type"] == "string"
    assert normalized["properties"]["user"]["properties"]["id"]["type"] == "string"


def test_normalize_tool_spec_does_not_mutate_input_or_drop_siblings():
    tool_spec = {
        "name": "demo",
        "description": "demo",
        "inputSchema": {
            "json": {"type": "object", "properties": {"query": {}}},
            "extra": "preserve-me",
        },
    }
    original = copy.deepcopy(tool_spec)

    normalized = normalize_tool_spec(tool_spec)

    assert tool_spec == original
    assert normalized["inputSchema"]["json"]["properties"]["query"]["type"] == "string"
    assert normalized["inputSchema"]["extra"] == "preserve-me"
