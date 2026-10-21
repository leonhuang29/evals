The defect is in `Agent._validate_limits` in `strands-py/src/strands/agent/agent.py`. Validation
iterates only the recognized key names and never checks the keys actually supplied, so unknown keys
silently no-op. The fix should compare supplied keys against the canonical `Limits` keys and raise
`TypeError` before model execution when any are unknown. The recognized-key list should be derived
from or kept explicitly synchronized with the `Limits` type. Existing positive-integer and boolean
validation must remain intact.
