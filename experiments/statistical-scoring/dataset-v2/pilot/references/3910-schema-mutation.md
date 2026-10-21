The defect is in `normalize_schema` and `normalize_tool_spec` in
`strands-py/src/strands/tools/tools.py`. Both start with shallow top-level copies and then write into
shared nested `properties` or `inputSchema` dictionaries, mutating caller-owned data. The fix should
rebuild the nested mappings before normalization. Returned normalized output must remain unchanged,
recursive properties must still be normalized, and sibling fields inside `inputSchema` must be
preserved.
