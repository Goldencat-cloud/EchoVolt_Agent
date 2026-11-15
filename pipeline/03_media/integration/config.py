# -*- coding: utf-8 -*-
"""AUTO-008 configuration: paths, parameters, budgets, versions, retry policy.

Everything is derived from the experiment directory so the package is
relocatable. Inputs are read-only; bulky runtime outputs go to a dedicated
directory under collaboration/result/auto008 (never overwriting other results).
Credentials are reused locally from G:\\QwenHome and are never printed/persisted.
"""
from pathlib import Path

CHANGE_ID = "auto-008-post-integrated-summary"

# ---- locations (derived, relocatable) ------------------------------------- #
EXP_DIR = Path(__file__).resolve().parent.parent          # pipeline/03_media
PIPELINE_ROOT = EXP_DIR.parent                            # pipeline/
WORKSPACE = PIPELINE_ROOT                                 # 兼容旧名；指向管道根

PROMPT_FILE = EXP_DIR / "prompts" / "full_summary_prompt.txt"
SYNTH_PROMPT_FILE = EXP_DIR / "prompts" / "synthesis_prompt.txt"
SCHEMA_FILE = EXP_DIR / "schema" / "summary_result.schema.json"

DATA_DIR = EXP_DIR / "source_metadata"
CSV004 = DATA_DIR / "004_A4_图片策展_主链路终版.csv"
CSV003 = DATA_DIR / "003_A4_图片下载_图片清单.csv"
RES006 = WORKSPACE / "03_media" / "auto006" / "results_final.jsonl.gz"
RES007 = WORKSPACE / "03_media" / "auto007" / "results_final.jsonl.gz"

# ---- runtime outputs (allowed write tree; bulky; non-committed) ------------ #
OUT_DIR = WORKSPACE / "data" / "runtime" / "auto008"
REQUESTS_DIRNAME = "requests"

# ---- credentials (local reuse; never printed/persisted) -------------------- #
SETTINGS = WORKSPACE / "local-config/settings.json"
ENV_FILE = WORKSPACE / "local-config/.env"

# ---- model ----------------------------------------------------------------- #
MODEL_EXPECTED = "qwen3.8-27b"   # informational; the actual requested model comes from SETTINGS

# ---- parameters (text-only summary; calibrated during smoke) --------------- #
PARAMS = {
    "max_tokens": 2048,          # calibrated in smoke if truncation is observed
    "temperature": 0.0,
    "enable_thinking": False,
    "timeout": 180,
}
MAX_RETRIES = 3
DEFAULT_CONCURRENCY = 4

# ---- version labels (the SHA-256 hashes are the ground truth for resume) ---- #
PROMPT_VERSION = "auto-008-v1"
SCHEMA_VERSION = "auto-008-v1"
CHUNK_POLICY_VERSION = "chunk-v1"
SYNTH_VERSION = "synth-v1"

# ---- input budget (total request tokens: fixed prompt + post input) -------- #
# A post whose estimated total input exceeds this is chunked (never truncated).
# Calibrated against the offline-computed maximum during smoke.
INPUT_TOKEN_BUDGET = 20000

# ---- limits / retry policy (mirror AUTO-006/007) --------------------------- #
MAX_RESPONSE_BYTES = 2_097_152
TRANSIENT_HTTP = {408, 429, 500, 502, 503, 504}
BACKOFF_BASE = 1.5
BACKOFF_FACTOR = 2.0
BACKOFF_CAP = 20.0
TRANSPORT_CODES = {"request_timeout", "connection_error", "connection_reset", "transport_or_json_error"}
# Sporadic content non-compliance is retried (bounded); deterministic failures are not.
RETRYABLE_CONTENT = {
    "invalid_json_response",
    "empty_response",
    "truncated_or_incomplete",
    "invalid_source_reference",
    "not_an_object",
    "schema_mismatch",
}
CONTENT_RETRY_DELAY = 0.6
