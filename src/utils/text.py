import re

_PATTERNS = [
    r"<think>.*?</think>",
    r"<analysis>.*?</analysis>",
    r"<chain[_\- ]?of[_\- ]?thought>.*?</chain[_\- ]?of[_\- ]?thought>",
]
def sanitize_model_text(s: str) -> str:
    if not s:
        return s
    for pat in _PATTERNS:
        s = re.sub(pat, "", s, flags=re.IGNORECASE | re.DOTALL)
    s = re.sub(r"</?think[^>]*>", "", s, flags=re.IGNORECASE)
    s = s.strip()
    return s
