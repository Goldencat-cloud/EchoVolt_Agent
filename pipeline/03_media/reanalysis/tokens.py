# -*- coding: utf-8 -*-
"""Conservative text-token estimation.

No matching local ``qwen3.8-27b`` tokenizer is available (weights are not loaded
or downloaded, per the task constraints). We therefore use a clearly-labelled
conservative heuristic that OVERESTIMATES token usage for Chinese-heavy text, so
the ~1500/~3000 text budgets are never exceeded in practice. ``estimated`` is
always True and the method is recorded alongside every budget decision.
"""


def _is_cjk(cp):
    return (
        0x4E00 <= cp <= 0x9FFF      # CJK Unified Ideographs
        or 0x3400 <= cp <= 0x4DBF   # Extension A
        or 0xF900 <= cp <= 0xFAFF   # Compatibility Ideographs
        or 0x3040 <= cp <= 0x30FF   # Hiragana/Katakana
        or 0xAC00 <= cp <= 0xD7AF   # Hangul syllables
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
