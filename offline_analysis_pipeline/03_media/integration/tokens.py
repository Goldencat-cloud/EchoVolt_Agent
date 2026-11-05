# -*- coding: utf-8 -*-
"""Conservative text-token estimation (reused method from AUTO-006/007).

No matching local ``qwen3.8-27b`` tokenizer is available (weights are not
loaded or downloaded). We use a clearly-labelled conservative heuristic that
OVERESTIMATES token usage for Chinese-heavy text, so the input budget is never
exceeded in practice. ``estimated`` is always True and the method is recorded
alongside every budget decision. Character count is never conflated with real
tokens.
"""


def _is_cjk(cp):
    return (
        0x4E00 <= cp <= 0x9FFF      # CJK Unified Ideographs
        or 0x3400 <= cp <= 0x4DBF   # Extension A
        or 0xF900 <= cp <= 0xFAFF   # Compatibility Ideographs
        or 0x3040 <= cp <= 0x30FF   # Hiragana/Katakana
        or 0xAC00 <= cp <= 0xD7AF   # Hangul syllables
        or 0x3000 <= cp <= 0x303F   # CJK punctuation
        or 0xFF00 <= cp <= 0xFFEF   # Fullwidth forms
    )


TOKEN_METHOD = (
    "heuristic:cjk=1tok/char,noncjk=1tok/3char,conservative(upper-bound);"
    "no matching local qwen3.8-27b tokenizer available (weights not loaded/downloaded)"
)


def estimate_tokens(text):
    """Estimate the token count of ``text`` (conservative upper bound)."""
    if not text:
        return 0
    cjk = 0
    other = 0
    for ch in text:
        if _is_cjk(ord(ch)):
            cjk += 1
        elif not ch.isspace():
            other += 1
    return cjk + -(-other // 3)  # ceil(other / 3)
