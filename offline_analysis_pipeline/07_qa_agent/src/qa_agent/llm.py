"""Pluggable LLM client: OpenAI-compatible chat completions via stdlib urllib.

Config resolution (first wins):
  1. process environment REPORT_KB_LLM_BASE_URL / REPORT_KB_LLM_API_KEY / REPORT_KB_LLM_MODEL
  2. module-root .env file (simple KEY=VALUE; values do not override the real env)
  3. configs/llm.json {"base_url": ..., "model": ..., "api_key_env": "NAME"}
Secrets must only live in .env (gitignored) or the process environment - never
in the repository. No configuration -> QaError("llm_not_configured").
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path

from .paths import CONFIGS, MODULE_ROOT

ENV_KEYS = ("REPORT_KB_LLM_BASE_URL", "REPORT_KB_LLM_API_KEY", "REPORT_KB_LLM_MODEL")


def load_dotenv(path: Path | None = None) -> dict:
    """Load KEY=VALUE pairs from module-root .env into os.environ (no override).

    stdlib-only mini loader: strips BOM/quotes, ignores blank lines and # comments.
    Returns the parsed mapping for diagnostics.
    """
    path = path or MODULE_ROOT / ".env"
    parsed = {}
    if not path.is_file():
        return parsed
    for raw in path.read_text(encoding="utf-8-sig").split("\n"):
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key in ENV_KEYS and value and key not in os.environ:
            os.environ[key] = value
            parsed[key] = value
    return parsed


class QaError(Exception):
    def __init__(self, code: str, detail: str = ""):
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


def load_config():
    load_dotenv()
    base = os.environ.get("REPORT_KB_LLM_BASE_URL")
    key = os.environ.get("REPORT_KB_LLM_API_KEY")
    model = os.environ.get("REPORT_KB_LLM_MODEL")
    cfg_path = CONFIGS / "llm.json"
    if cfg_path.is_file():
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        base = base or cfg.get("base_url")
        model = model or cfg.get("model")
        env_name = cfg.get("api_key_env")
        key = key or (os.environ.get(env_name) if env_name else None)
    if base and key and model:
        return {"base_url": base.rstrip("/"), "api_key": key, "model": model}
    return None


def chat(messages, timeout: int = 90) -> str:
    cfg = load_config()
    if not cfg:
        raise QaError("llm_not_configured",
                      "set REPORT_KB_LLM_BASE_URL / REPORT_KB_LLM_API_KEY / REPORT_KB_LLM_MODEL "
                      "or provide configs/llm.json")
    payload = json.dumps({"model": cfg["model"], "messages": messages,
                          "temperature": 0.2}).encode("utf-8")
    req = urllib.request.Request(
        cfg["base_url"] + "/chat/completions", data=payload, method="POST",
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {cfg['api_key']}"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise QaError("llm_request_failed", f"HTTP {e.code}: {e.reason}") from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise QaError("llm_request_failed", str(e)) from e
    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as e:
        raise QaError("llm_bad_response", json.dumps(data)[:400]) from e
