# -*- coding: utf-8 -*-
"""Fixed-prompt loading/rendering. The Section-六 prompt is the single, verbatim,
hashed instruction used for every summarization call. A separate, versioned
synthesis prompt is used ONLY when a post must be chunked."""
from pathlib import Path

from . import config
from . import util

USER_PREFIX = "[帖子输入]\n"
CHUNK_USER_PREFIX_FMT = "[帖子输入-第%d/%d段]\n"


def load_prompt(path=config.PROMPT_FILE):
    """Return ``(prompt_text, prompt_sha256)`` for the fixed summary prompt."""
    raw = Path(path).read_bytes()
    return raw.decode("utf-8"), util.sha256_bytes(raw)


def load_synthesis_prompt(path=config.SYNTH_PROMPT_FILE):
    raw = Path(path).read_bytes()
    return raw.decode("utf-8"), util.sha256_bytes(raw)


def render_user(post_input_json):
    """The exact user-message content for a single (non-chunked) call."""
    return USER_PREFIX + post_input_json


def render_chunk_user(post_input_json, k, n):
    """User-message content for chunk ``k`` of ``n`` (1-indexed)."""
    return (CHUNK_USER_PREFIX_FMT % (k, n)) + post_input_json


def build_payload(system_text, user_text, model, params):
    """Deterministic chat-completion payload (text-only)."""
    return {
        "model": model,
        "messages": [
            {"role": "system", "content": system_text},
            {"role": "user", "content": user_text},
        ],
        "max_tokens": params["max_tokens"],
        "temperature": params["temperature"],
        "chat_template_kwargs": {"enable_thinking": params["enable_thinking"]},
        "stream": False,
    }
