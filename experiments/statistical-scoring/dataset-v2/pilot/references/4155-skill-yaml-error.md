The defect is in `_parse_frontmatter` in
`strands-py/src/strands/vended_plugins/skills/skill.py`. The first `yaml.safe_load` failure is caught
and retried after the colon-quoting fallback, but the second parse is unwrapped and leaks
`yaml.YAMLError`. The fix should translate an unrecoverable fallback parse into `ValueError`, chained
from the YAML error. This restores the documented `Skill.from_content` contract and allows
`Skill.from_directory` to skip the malformed skill while loading valid siblings.
