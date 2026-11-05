"""竖向泳道（时序图）版「工作流编排」：24 步全量，按 POST outline 确认拆两页。

页1  第 1–14 步（提交 → 澄清 → 计划 → 大纲确认）
页2  第 15–24 步（恢复执行 → 逐项分析 → 报告 → 门禁 → 交付）

画布即 PPT 实际尺寸（13.33 x 7.5 英寸），插入铺满整页，字号不需要二次缩放。
用法：python docs/workflow-seq.py   （需要 matplotlib）
"""
from __future__ import annotations

import re
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Arc, Circle, FancyBboxPatch, Rectangle

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "sans-serif"]
plt.rcParams["axes.unicode_minus"] = False

W, H = 13.33, 7.5
NAVY = "#2F5597"
DARK = "#2B2B2B"
LIFE = "#C9CDE6"
FRAME = "#C9B8E8"
FRAME_TAG = "#E6DDF7"
TEXT = "#1F2937"
MUTED = "#5B6472"
LANE_BG = "#EDEDF9"

ACTORS = ["用户 / 前端", "API 层", "任务状态", "Agent + LLM", "工具与语义层", "门禁与发布"]
XS = [1.05 + i * 2.07 for i in range(6)]
BOX_TOP, BOX_BOTTOM = 7.38, 6.94
X_LEFT, X_RIGHT = 0.16, 12.78


def wrap(text: str, limit: float = 16, max_lines: int = 2) -> str:
    if "\n" in text:
        return text
    tokens = re.findall(r"[A-Za-z0-9_\-/{}.]+|\s+|.", text)
    lines, current, width = [], "", 0.0
    for token in tokens:
        step = sum(1.0 if ord(c) > 127 else 0.55 for c in token)
        if width + step > limit and current.strip():
            lines.append(current.rstrip())
            current, width = "", 0.0
            if token.isspace():
                continue
        current += token
        width += step
    if current.strip():
        lines.append(current.rstrip())
    if len(lines) > max_lines:
        lines = lines[:max_lines - 1] + ["".join(lines[max_lines - 1:]).lstrip()]
    return "\n".join(lines)


def draw_page(path, events, step, font, frames, legend_note):
    fig = plt.figure(figsize=(W, H), dpi=220)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, W)
    ax.set_ylim(0, H)
    ax.axis("off")

    # 参与者框 + 生命线
    for index, name in enumerate(ACTORS):
        ax.add_patch(FancyBboxPatch((XS[index] - 0.92, BOX_BOTTOM),
                                    1.84, BOX_TOP - BOX_BOTTOM,
                                    boxstyle="round,pad=0.01,rounding_size=0.05",
                                    facecolor=LANE_BG, edgecolor="#C9CDE6",
                                    lw=0.8, zorder=3))
        ax.text(XS[index], (BOX_TOP + BOX_BOTTOM) / 2, name, ha="center",
                va="center", fontsize=9.6, color="#3B3B5C", zorder=4)
        ax.plot([XS[index], XS[index]], [BOX_BOTTOM - 0.02, 0.72],
                color=LIFE, lw=0.9, ls=(0, (7, 3)), zorder=1)

    ys = [6.55 - step * i for i in range(len(events))]

    # 组合片段虚线框（loop / opt / alt）
    for label, x0, x1, y_top, y_bottom in frames:
        ax.add_patch(Rectangle((x0, y_bottom), x1 - x0, y_top - y_bottom,
                               facecolor="none", edgecolor=FRAME, lw=0.9,
                               ls=(0, (4, 2.5)), zorder=2))
        ax.add_patch(FancyBboxPatch((x0, y_top - 0.20), 0.44, 0.20,
                                    boxstyle="square,pad=0",
                                    facecolor=FRAME_TAG, edgecolor=FRAME,
                                    lw=0.8, zorder=3))
        ax.text(x0 + 0.22, y_top - 0.10, label, ha="center", va="center",
                fontsize=7.6, color="#4B3F72", zorder=4)

    for index, (n, src, dst, text, dashed) in enumerate(events):
        if isinstance(src, int):
            x1, x2 = XS[src], XS[dst]
        else:                                   # 自循环：src 为列序号
            x1 = x2 = XS[src]
        y = ys[index]
        color = "#4A4A4A" if dashed else DARK
        style = (0, (3.6, 2.2)) if dashed else "solid"

        if x1 == x2:                            # 自循环
            ax.add_patch(Arc((x1 + 0.10, y - 0.055), 0.30, 0.20, theta1=200,
                             theta2=350, color=color, lw=0.95, zorder=5))
            ax.annotate("", xy=(x1 + 0.245, y - 0.005), xytext=(x1 + 0.245, y - 0.075),
                        arrowprops={"arrowstyle": "-|>", "color": color, "lw": 0.9,
                                    "mutation_scale": 7}, zorder=6)
            ax.text(x1 + 0.30, y + 0.02, wrap(text, 13, 2), ha="left", va="bottom",
                    fontsize=font, color=TEXT, linespacing=1.4, zorder=6)
        else:
            sign = 1 if x2 > x1 else -1
            ax.annotate("", xy=(x2, y), xytext=(x1 + sign * 0.26, y),
                        arrowprops={"arrowstyle": "-|>", "color": color, "lw": 1.0,
                                    "ls": style, "mutation_scale": 8,
                                    "shrinkA": 0, "shrinkB": 0}, zorder=5)
            ax.text((x1 + x2) / 2, y + 0.10, wrap(text), ha="center", va="bottom",
                    fontsize=font, color=TEXT, linespacing=1.4, zorder=6)

        ax.add_patch(Circle((x1 + 0.10, y), 0.105, facecolor=DARK,
                            edgecolor="white", lw=0.8, zorder=7))
        ax.text(x1 + 0.10, y, str(n), ha="center", va="center", color="white",
                fontsize=6.8, zorder=8)

    # 图例
    ax.plot([1.10, 1.62], [0.32, 0.32], color=DARK, lw=1.0)
    ax.text(1.68, 0.32, "同步调用", fontsize=8.2, va="center", color=TEXT)
    ax.plot([2.55, 3.07], [0.32, 0.32], color="#4A4A4A", lw=1.0, ls=(0, (3.6, 2.2)))
    ax.text(3.13, 0.32, "返回 / 异步推送", fontsize=8.2, va="center", color=TEXT)
    ax.plot([4.30, 4.60], [0.32, 0.32], color=FRAME, lw=1.0, ls=(0, (4, 2.5)))
    ax.text(4.66, 0.32, "组合片段（loop / opt / alt）", fontsize=8.2, va="center",
            color=TEXT)
    ax.text(X_RIGHT, 0.32, legend_note, fontsize=8.2, va="center", ha="right",
            color=MUTED)

    fig.savefig(path, dpi=220, facecolor="white")
    plt.close(fig)
    print(f"saved: {path}")


PAGE1 = [
    (1, 0, 1, "POST 发起深度分析", False),
    (2, 1, 2, "建任务，返回 202 job_id", False),
    (3, 0, 1, "GET /api/agent/report/job_id", False),
    (4, 2, 2, "后台做澄清评估", False),
    (5, 2, 0, "澄清中 · 问题", True),
    (6, 0, 2, "提交答复", False),
    (7, 2, 1, "重新评估后放行", False),
    (8, 1, 3, "启动 Agent，注入任务简报与基线", False),
    (9, 3, 3, "读技能、预览议题数据", False),
    (10, 3, 4, "提交分析计划", False),
    (11, 4, 3, "计划校验通过", True),
    (12, 3, 2, "停在待大纲审查", True),
    (13, 2, 0, "子问题大纲 + plan_json", True),
    (14, 0, 1, "POST outline 确认", False),
]

PAGE2 = [
    (15, 1, 3, "恢复执行", False),
    (16, 3, 4, "语义聚合、取负面证据", False),
    (17, 4, 3, "行集、口径、claim_id", True),
    (18, 3, 5, "提交报告", False),
    (19, 5, 3, "门禁校验", True),
    (20, 5, 3, "拒绝原因", True),
    (21, 3, 5, "修订后重提", False),
    (22, 5, 5, "落盘 pending_review", False),
    (23, 5, 2, "done + 结果字段", True),
    (24, 2, 0, "done + 报告", True),
]

HERE = Path(__file__).resolve().parent

draw_page(
    HERE / "workflow-seq-1.png", PAGE1, step=0.44, font=9.4,
    frames=[
        ("loop", 0.55, 5.35, 6.10, 4.02),      # 轮询任务状态：第 3–7 步
        ("opt", 0.55, 5.35, 5.32, 4.02),       # 信息不足：第 5–7 步
    ],
    legend_note="编号 1–14 与纵向时序图一致",
)

draw_page(
    HERE / "workflow-seq-2.png", PAGE2, step=0.60, font=10.2,
    frames=[
        ("loop", 6.50, 9.82, 6.40, 5.15),      # 计划逐项执行：第 16–17 步
        ("alt", 6.50, 11.95, 4.56, 2.98),      # 门禁未通过：第 19–21 步
    ],
    legend_note="编号 15–24 与纵向时序图一致",
)
