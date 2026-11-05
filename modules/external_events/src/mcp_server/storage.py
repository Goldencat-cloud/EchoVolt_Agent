"""产物落盘（task 2.5）：完整事件集的唯一出口。JSON 与可读 txt 同步产出。"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT_DIR = Path(os.getenv("TIMELINE_OUTPUT_DIR") or (_ROOT / "outputs" / "research"))

_TYPE_CN = {"product": "产品", "competitor": "竞品", "policy": "政策",
            "tech": "技术", "public_opinion": "舆情", "other": "其他"}


def _sanitize(s: str) -> str:
    return re.sub(r'[\\/:*?"<>|\s]+', "_", s).strip("_") or "unknown"


def output_path(brand: str, product: str, out_dir: Path | None = None) -> Path:
    d = Path(out_dir) if out_dir else DEFAULT_OUT_DIR
    return d / f"{_sanitize(brand)}_{_sanitize(product)}_timeline.json"


def _render_txt(timeline: dict) -> str:
    meta = timeline["meta"]
    ev = sorted(timeline["events"],
                key=lambda e: (e["event_date"] is None, e["event_date"] or ""))
    tw = meta.get("time_window")
    lines = [
        f"{meta['brand']}{meta['product']} 产品事件时间线（条级去噪 + 权威性核查）",
        (f"时间窗: {tw['from']} ~ {tw['to']}" if tw else "时间窗: 未限定")
        + f"  |  事件 {len(ev)} 个(由 {sum(len(e['sources']) for e in ev)} 条报道聚合)"
        + f"  |  LLM: {'启用' if meta.get('llm_used') else '降级'}"
        + f"  |  生成: {meta['generated_at'][:16]}",
        f"过滤: {meta['filter_stats']}",
        "=" * 60,
    ]
    for i, e in enumerate(ev, 1):
        d = e["event_date"] or "日期未知"
        mc, auth = e["media_coverage"], e["authority"]
        tag = f"{_TYPE_CN.get(e['event_type'], e['event_type'])}/{e['subtype']}"
        star = "*" if mc["level"] == "high" else ("**" if mc["level"] == "medium" else "")
        lines.append(f"\n{i:03d}. [{d}] {tag} | 覆盖{mc['source_count']}家 "
                     f"{star}{mc['level']}{star} | 权威分{auth}")
        lines.append(f"    {e['title']}")
        lines.append(f"    {e['summary']}")
        if mc["source_count"] >= 3:
            doms = "、".join(dict.fromkeys(s["source_domain"] for s in e["sources"]))
            lines.append(f"    来源: {doms[:90]}")
    return "\n".join(lines)


def save_timeline(timeline: dict, out_dir: Path | None = None) -> str:
    """写 JSON 与同步的 txt 可读版，返回 JSON 路径字符串。重复调用覆盖同名文件。"""
    path = output_path(timeline["meta"]["brand"], timeline["meta"]["product"], out_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(timeline, f, ensure_ascii=False, indent=2)
    path.with_suffix(".txt").write_text(_render_txt(timeline), encoding="utf-8")
    return str(path)


def summary(timeline: dict, path: str) -> dict:
    """工具返回值：仅摘要，完整事件列表只存在于落盘文件。"""
    return {
        "status": timeline["meta"]["status"],
        "event_count": len(timeline["events"]),
        "output_path": path,
        "time_window": timeline["meta"]["time_window"],
        "note": "完整时间线已落盘（同名 .txt 为可读版），请读文件获取事件列表",
    }
