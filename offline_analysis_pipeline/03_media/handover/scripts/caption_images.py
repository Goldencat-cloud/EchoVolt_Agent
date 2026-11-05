"""批量图片描述推理（vLLM + Qwen3.5-4B-AWQ-4bit，在 WSL2 内运行）。

功能（specs/image-captioning）：
- 两档分辨率预设（visual token 预算 min_pixels/max_pixels）
- 固定中文客观描述 prompt，单图输入，temperature=0.1
- 断点续跑：跳过产物表中已有成功描述的 image_id（默认重跑处理缺失+失败项）
- --retry-errors：只重试失败表中的图片
- 按批追加写盘 outputs/image_captions.csv / image_captions_errors.csv

用法（WSL2 内）：
  /root/vllm-env/bin/python backend/scripts/caption_images.py --preset low-vram --limit 10
  /root/vllm-env/bin/python backend/scripts/caption_images.py --preset low-vram
"""

from __future__ import annotations

import argparse
import base64
import csv
import io
import json
import mimetypes
import os
import re
import sys
import time
from datetime import datetime, timezone

# WSL 缺 nvcc：开 expandable_segments 反碎片化，避免权重加载期 OOM
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from caption_store import (  # noqa: E402
    CAPTION_COLUMNS,
    ERROR_COLUMNS,
    load_failure_ids,
    load_success_ids,
    prune_resolved_errors,
    read_table,
    upsert_rows,
)

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 优先用 WSL 本地副本（从 9P 共享盘拷入可大幅加快启动），缺失时回退到 9P 路径
_LOCAL_MODEL = "/root/models/Qwen3.5-4B-AWQ-4bit"
DEFAULT_MODEL = _LOCAL_MODEL if os.path.isdir(_LOCAL_MODEL) else "/mnt/d/models/Qwen3.5-4B-AWQ-4bit"
DEFAULT_TODO = "/mnt/d/Desktop/Competitions/comments_for_decisions/outputs/caption_todo.csv"
DEFAULT_CAPTIONS = "/mnt/d/Desktop/Competitions/comments_for_decisions/outputs/image_captions.csv"
DEFAULT_ERRORS = "/mnt/d/Desktop/Competitions/comments_for_decisions/outputs/image_captions_errors.csv"

MODEL_TAG = "cyankiwi/Qwen3.5-4B-AWQ-4bit"

# ADR-2：分辨率档位。Qwen3.5 视觉网格 = patch 16 × merge 2 = 32 的整数倍，
# n*32*32 为 visual token 预算
PRESETS: dict[str, dict] = {
    "low-vram": {"max_pixels": 128 * 32 * 32, "min_pixels": 16 * 32 * 32},
    "high-detail": {"max_pixels": 256 * 32 * 32, "min_pixels": 16 * 32 * 32},
}

PROMPT = (
    "根据这张图片，只填写下面 JSON 里的中文占位内容，并只输出这个 JSON 本身，"
    "不要输出任何解释、分析或多余文字，不要使用 markdown 代码块：\n"
    "{\"subject\":\"<画面主体，不超过15字>\","
    "\"scene\":\"<场景，不超过15字>\","
    "\"details\":\"<可见关键细节，不超过60字>\"}\n"
    "现在请直接输出填写好的 JSON："
)

BATCH_SIZE = 200


def extract_json(text: str) -> str:
    """从模型输出中稳健地提取合法 JSON 字符串（去 <think> 块、截取首个 {...}）。

    返回紧凑 JSON 字符串；若无法解析则返回原文（截断空白），保证下游可存储。
    """
    cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
    candidates = [cleaned]
    m = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
    if m:
        candidates.append(m.group(0))
    for cand in candidates:
        try:
            obj = json.loads(cand)
            if isinstance(obj, dict):
                return json.dumps(obj, ensure_ascii=False)
        except (json.JSONDecodeError, ValueError):
            continue
    return cleaned


def to_wsl_path(win_path: str) -> str:
    """D:\\a\\b -> /mnt/d/a/b"""
    p = win_path.replace("\\", "/")
    if len(p) >= 2 and p[1] == ":":
        return f"/mnt/{p[0].lower()}{p[2:]}"
    return p


def resized_pixel_count(width: int, height: int, preset: dict) -> int:
    """按 Qwen3.5 smart_resize 规则计算缩放后的像素面积（factor=32）。"""
    factor = 32
    h_bar = max(factor, round(height / factor) * factor)
    w_bar = max(factor, round(width / factor) * factor)
    if h_bar * w_bar > preset["max_pixels"]:
        scale = (preset["max_pixels"] / (h_bar * w_bar)) ** 0.5
        h_bar = max(factor, round(height * scale / factor) * factor)
        w_bar = max(factor, round(width * scale / factor) * factor)
    elif h_bar * w_bar < preset["min_pixels"]:
        scale = (preset["min_pixels"] / (h_bar * w_bar)) ** 0.5
        h_bar = round(height * scale / factor) * factor
        w_bar = round(width * scale / factor) * factor
    return h_bar * w_bar


def image_to_data_url(path: str, preset: dict) -> tuple[str, int]:
    """返回 (data_url, 缩放后像素面积)。用 PIL 读取尺寸并按档位预算计算 pixels_used。"""
    from PIL import Image

    with Image.open(path) as im:
        width, height = im.size
    pixels = resized_pixel_count(width, height, preset)
    mime = mimetypes.guess_type(path)[0] or "image/jpeg"
    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    return f"data:{mime};base64,{b64}", pixels


def build_message(local_path: str, preset: dict) -> tuple[list[dict], int]:
    url, pixels = image_to_data_url(local_path, preset)
    message = [
        {
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": url}},
                {"type": "text", "text": PROMPT},
            ],
        }
    ]
    return message, pixels


def select_targets(todo_path: str, captions_path: str, errors_path: str, retry_errors: bool,
                   limit: int | None) -> list[dict]:
    """断点续跑选集：默认处理(待描述-已成功)；--retry-errors 只重试失败表。"""
    done = load_success_ids(captions_path)
    failed = load_failure_ids(errors_path)
    todo = read_table(todo_path)
    if retry_errors:
        return [r for r in todo if r["image_id"] in failed and r["image_id"] not in done]
    targets = [r for r in todo if r["image_id"] not in done]  # 缺失 + 失败项都重跑
    if limit:
        targets = targets[:limit]
    return targets


def record_error(errors_path: str, image_id: str, post_id: str, error_type: str,
                 detail: str) -> None:
    prev = {r["image_id"]: r for r in read_table(errors_path)}
    attempts = int(prev.get(image_id, {}).get("attempts") or 0) + 1
    upsert_rows(errors_path, ERROR_COLUMNS, [{
        "image_id": image_id, "post_id": post_id, "error_type": error_type,
        "detail": detail[:500], "attempts": attempts,
    }])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preset", choices=sorted(PRESETS), default="low-vram")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--todo", default=DEFAULT_TODO)
    parser.add_argument("--captions-out", default=DEFAULT_CAPTIONS)
    parser.add_argument("--errors-out", default=DEFAULT_ERRORS)
    parser.add_argument("--batch-size", type=int, default=BATCH_SIZE)
    parser.add_argument("--limit", type=int, default=None, help="只处理前 N 张（冒烟/压测用）")
    parser.add_argument("--retry-errors", action="store_true",
                        help="只重试失败表中的图片")
    parser.add_argument("--max-num-seqs", type=int, default=4)
    parser.add_argument("--enforce-eager", action="store_true",
                        help="关闭 CUDA graph/inductor 编译（WSL 缺 nvcc 时必须）")
    parser.add_argument("--guided-json", action="store_true",
                        help="用 vLLM 结构化输出强制 JSON（8GB 下额外占显存，默认关闭）")
    parser.add_argument("--max-model-len", type=int, default=2048,
                        help="序列预算：low-vram 单图约 120 视觉token+prompt+输出，2048 足够")
    args = parser.parse_args()

    from vllm import LLM, SamplingParams

    # 可选：用 vLLM 结构化输出强制 JSON（8GB 下额外占显存，默认关闭）
    guided = None
    if args.guided_json:
        try:
            from vllm.sampling_params import StructuredOutputsParams
            guided = StructuredOutputsParams(json={
                "type": "object",
                "properties": {
                    "subject": {"type": "string"},
                    "scene": {"type": "string"},
                    "details": {"type": "string"},
                },
                "required": ["subject", "scene", "details"],
            })
        except Exception:  # noqa: BLE001 老版本无该 API 时降级
            guided = None

    preset = PRESETS[args.preset]
    targets = select_targets(args.todo, args.captions_out, args.errors_out,
                             args.retry_errors, args.limit)
    print(f"[caption] preset={args.preset} max_pixels={preset['max_pixels']} "
          f"targets={len(targets)}", flush=True)
    if not targets:
        print("[caption] nothing to do", flush=True)
        return

    llm = LLM(
        model=args.model,
        max_model_len=args.max_model_len,
        # WSL 下 Windows 桌面常驻占约 1GB，实际空闲约 6.87/7.96GiB；权重 3.78GB 余量充足
        gpu_memory_utilization=0.85,
        max_num_seqs=args.max_num_seqs,
        enforce_eager=args.enforce_eager,
        mm_processor_kwargs=preset,
        limit_mm_per_prompt={"image": 1},
    )
    params = (SamplingParams(temperature=0.1, max_tokens=400, structured_outputs=guided)
              if guided is not None
              else SamplingParams(temperature=0.1, max_tokens=400))

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    n_ok = n_err = 0
    for start in range(0, len(targets), args.batch_size):
        batch = targets[start:start + args.batch_size]
        messages, metas = [], []
        for row in batch:
            wsl_path = to_wsl_path(row["local_path"])
            try:
                message, pixels = build_message(wsl_path, preset)
                messages.append(message)
                metas.append({**row, "pixels_used": pixels})
            except (OSError, ValueError) as exc:
                record_error(args.errors_out, row["image_id"], row["post_id"],
                             "decode_error", str(exc))
                n_err += 1

        t0 = time.monotonic()
        try:
            outputs = llm.chat(messages, params)
        except Exception as exc:  # noqa: BLE001 整批失败：逐条记录，不中断任务
            print(f"[caption] batch failed: {exc}", flush=True)
            for row in metas:
                record_error(args.errors_out, row["image_id"], row["post_id"],
                             "inference_error", repr(exc))
                n_err += 1
            continue

        caption_rows: list[dict] = []
        for row, out in zip(metas, outputs):
            text = (out.outputs[0].text or "").strip() if out.outputs else ""
            if text:
                caption = extract_json(text)
                caption_rows.append({
                    "image_id": row["image_id"],
                    "post_id": row["post_id"],
                    "caption": caption,
                    "pixels_used": row["pixels_used"],
                    "model": MODEL_TAG,
                    "resolution_preset": args.preset,
                    "created_at": now,
                })
                n_ok += 1
            else:
                record_error(args.errors_out, row["image_id"], row["post_id"],
                             "inference_error", "empty output")
                n_err += 1
        if caption_rows:
            upsert_rows(args.captions_out, CAPTION_COLUMNS, caption_rows)
        prune_resolved_errors(args.errors_out, load_success_ids(args.captions_out))
        print(f"[caption] batch {start // args.batch_size + 1}: "
              f"{len(batch)} imgs in {time.monotonic() - t0:.1f}s "
              f"(ok={n_ok} err={n_err})", flush=True)

    print(f"[caption] DONE ok={n_ok} err={n_err}", flush=True)


if __name__ == "__main__":
    main()
