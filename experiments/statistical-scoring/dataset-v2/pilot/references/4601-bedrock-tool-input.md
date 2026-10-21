The defect is in `BedrockModel._format_request_message_content` in
`strands-py/src/strands/models/bedrock.py`. Its `toolUse` branch forwards `tool_use["input"]`
verbatim, even though Bedrock requires a JSON object. The fix should read the input safely and
replace any non-dictionary value with `{}`, while preserving dictionary inputs and avoiding mutation
of the original message. Regression coverage should include several falsy and non-dictionary values
plus a valid dictionary.
