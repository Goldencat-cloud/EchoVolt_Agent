"""显存压测：按候选分辨率档位对抽样图片运行，报告峰值显存与吞吐（任务 4.1）。

抽样规则：按图片尺寸（小/中/大）分层各取 34 张，共约 100 张。
输出：outputs/vram_benchmark.md（含每档位峰值显存 GB / 平均单图耗时 s / 读取+预处理耗时 / 可用性结论）。

用法（WSL2 内）：
  /root/vllm-env/bin/python -u backend/scripts/benchmark_vram.py --preset low-vram
  /root/vllm-env/bin/python -u backend/scripts/benchmark_vram.py --preset high-detail
"""

from __future__ import annotations

import argparse
import csv
import os
import random
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from caption_images import (  # noqa: E402
    DEFAULT_MODEL,
    DEFAULT_TODO,
    PRESETS,
    build_message,
    to_wsl_path,
)

ROOT = "/mnt/d/Desktop/Competitions/comments_for_decisions"
OUT_MD = f"{ROOT}/outputs/vram_benchmark.md"
SAMPLE_PER_STRATUM = 34


def stratified_sample(todo_path: str, n: int) -> list[dict]:
    from PIL import Image

    rows = read_csv(todo_path)
    sized: list[tuple[int, dict]] = []
    for row in rows:
        path = to_wsl_path(row["local_path"])
        with Image.open(path) as im:
            sized.append((im.width * im.height, row))
    sized.sort(key=lambda t: t[0])
    tiers = [sized[: len(sized) // 3], sized[len(sized) // 3: 2 * len(sized) // 3],
             sized[2 * len(sized) // 3:]]
    rng = random.Random(42)
    sample: list[dict] = []
    for tier in tiers:
        rng.shuffle(tier)
        sample.extend(r for _, r in tier[:n])
    return sample


def read_csv(path: str) -> list[dict]:
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preset", choices=sorted(PRESETS), required=True)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--todo", default=DEFAULT_TODO)
    parser.add_argument("--sample", type=int, default=SAMPLE_PER_STRATUM,
                        help="每层抽样数（3 层）")
    args = parser.parse_args()

    import torch
    from vllm import LLM, SamplingParams

    preset = PRESETS[args.preset]
    sample = stratified_sample(args.todo, args.sample)
    print(f"[bench] preset={args.preset} sample={len(sample)}", flush=True)

    messages = []
    t0 = time.monotonic()
    for row in sample:
        messages.append(build_message(to_wsl_path(row["local_path"]), preset)[0])
    io_preprocess_s = time.monotonic() - t0

    llm = LLM(
        model=args.model, max_model_len=4096, gpu_memory_utilization=0.90,
        max_num_seqs=4, mm_processor_kwargs=preset, limit_mm_per_prompt={"image": 1},
    )
    torch.cuda.reset_peak_memory_stats()
    params = SamplingParams(temperature=0.1, max_tokens=256)

    try:
        t1 = time.monotonic()
        outputs = llm.chat(messages, params)
        infer_s = time.monotonic() - t1
        peak_gb = torch.cuda.max_memory_allocated() / 1024**3
        n_captioned = sum(1 for o in outputs if o.outputs and o.outputs[0].text.strip())
        result = {
            "preset": args.preset,
            "max_pixels": preset["max_pixels"],
            "n": len(sample),
            "peak_gb": round(peak_gb, 2),
            "avg_s_per_img": round(infer_s / len(sample), 2),
            "io_preprocess_s": round(io_preprocess_s, 2),
            "n_captioned": n_captioned,
            "ok": "yes",
            "note": "",
        }
    except Exception as exc:  # noqa: BLE001
        result = {
            "preset": args.preset, "max_pixels": preset["max_pixels"], "n": len(sample),
            "peak_gb": "-", "avg_s_per_img": "-", "io_preprocess_s": round(io_preprocess_s, 2),
            "n_captioned": 0, "ok": "NO(OOM/failed)", "note": repr(exc)[:200],
        }
    print(f"[bench] {result}", flush=True)
    append_benchmark_md(result)


def append_benchmark_md(result: dict) -> None:
    """向 outputs/vram_benchmark.md 追加本次压测结果表行。"""
    header = (
        "# 显存压测报告\n\n"
        "| preset | max_pixels | n | peak_vram(GB) | avg_s/img | io+preprocess(s) | captioned | 可用 | note |\n"
        "|---|---|---|---|---|---|---|---|---|\n"
    )
    line = ("| {preset} | {max_pixels} | {n} | {peak_gb} | {avg_s_per_img} | "
            "{io_preprocess_s} | {n_captioned} | {ok} | {note} |\n").format(**result)
    if os.path.exists(OUT_MD):
        with open(OUT_MD, "a", encoding="utf-8") as f:
            f.write(line)
    else:
        with open(OUT_MD, "w", encoding="utf-8") as f:
            f.write(header + line)


if __name__ == "__main__":
    main()
