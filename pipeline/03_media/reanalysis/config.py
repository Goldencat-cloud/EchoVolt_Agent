# -*- coding: utf-8 -*-
"""AUTO-007 configuration: paths, parameters, budgets, fingerprints.

The experiment re-analyzes the 798 baseline ``image_type=irrelevant`` images with
local post text context, using the SAME model/config as AUTO-006. All inputs are
read-only; bulky runtime outputs go to a dedicated non-committed directory.
"""
from pathlib import Path

CHANGE_ID = "auto-007-irrelevant-context-reanalysis"
EXP_DIR = Path(__file__).resolve().parent.parent  # pipeline/03_media
WORKSPACE = EXP_DIR.parent                        # pipeline/
PROMPT_FILE = EXP_DIR / "prompts" / "enhanced_prompt.txt"
SCHEMA_FILE = EXP_DIR / "schema" / "enhanced_result.schema.json"

# ---- read-only inputs ----------------------------------------------------- #
BASELINE = WORKSPACE / "03_media/auto006/results_final.jsonl.gz"
CSV003 = EXP_DIR / "source_metadata" / "003_A4_图片下载_图片清单.csv"
CSV002 = EXP_DIR / "source_metadata" / "002_A3_深度清洗_全量_带噪声标注.csv"
IMG_ROOT = WORKSPACE / "images"
QC_REVIEWS_JSON = WORKSPACE / "03_media/reference/human-irrelevant-removal-review-20261010-n100-s20261010.json"

# ---- credentials (local reuse; never printed/persisted) -------------------- #
SETTINGS = WORKSPACE / "local-config/settings.json"
ENV_FILE = WORKSPACE / "local-config/.env"

# ---- runtime outputs (bulky; non-committed) -------------------------------- #
OUT_DIR = WORKSPACE / "data/runtime/auto007"

# ---- parameters (SAME as AUTO-006 baseline; any deviation is recorded) ----- #
PARAMS = {
    "image_max_edge": 1280,
    "max_tokens": 2048,
    "temperature": 0.0,
    "enable_thinking": False,
    "timeout": 180,
}
MAX_RETRIES = 3
DEFAULT_CONCURRENCY = 4

# ---- context budgets (text tokens; trial parameters) ----------------------- #
INITIAL_TEXT_TOKEN_BUDGET = 1500
EXPANSION_NEW_TOKEN_BUDGET = 1500
TOTAL_TEXT_TOKEN_BUDGET = 3000

# context-selection algorithm version (part of the resume fingerprint)
CONTEXT_VERSION = "ctx-v1"

# ---- limits / retry policy (mirror AUTO-006) ------------------------------- #
MAX_PIXELS = 25_000_000
MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_RESPONSE_BYTES = 2_097_152
TRANSIENT_HTTP = {408, 429, 500, 502, 503, 504}
BACKOFF_BASE = 1.5
BACKOFF_FACTOR = 2.0
BACKOFF_CAP = 20.0
TRANSPORT_CODES = {"request_timeout", "connection_error", "connection_reset", "transport_or_json_error"}
# The model does NOT emit image_id here (the program injects it), so
# image_id_mismatch is intentionally absent.
RETRYABLE_CONTENT = {
    "invalid_json_response",
    "schema_mismatch",
    "empty_response",
    "truncated_or_incomplete",
    "not_an_object",
}
CONTENT_RETRY_DELAY = 0.6
