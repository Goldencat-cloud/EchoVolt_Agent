"""横向泳道版「工作流编排」图：24 步全量，分两页（16:9，可直接铺满 PPT）。

原纵向时序图 24 步 / 6 泳道，单页横向时每步只有 0.48 英寸，中文标签必须压到
5pt 才能看清——因此按原图断点（第 13–14 步，大纲确认）拆两页：
  页1  规划：第 1–14 步
  页2  执行 + 交付：第 15–24 步

画布即 PPT 实际尺寸（13.33 x 7.5 英寸），插入铺满整页，字号不需要二次缩放。
用法：python docs/workflow-lanes.py   （需要 matplotlib）
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
GREY = "#8A8A8A"
WIRE = "#B4C6DE"
LANE_A = "#F4F7FC"
LANE_B = "#FFFFFF"
TEXT = "#1F2937"
MUTED = "#5B6472"
ACCENT = "#C55A11"

LANES = [
    ("用户 / 前端", 6.55),
    ("API 层", 5.55),
    ("任务状态", 4.55),
    ("Agent + LLM", 3.55),
    ("工具与语义层", 2.55),
    ("门禁与发布", 1.55),
]
Y = dict(LANES)
LANE_H = 1.00
X0 = 1.16


def wrap(text: str, limit: float = 9.5, max_lines: int = 3) -> str:
    """按显示宽度断行（中文 1.0、ASCII 0.55），英文词不拆，最多 max_lines 行。

    文本里已含换行时原样使用——长标签的断点由编排者指定，避免断在词中间。
    """
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


def draw_page(path, events, x_start, pitch, bands, font, notes, legend_note,
              wrap_limit=9.5):
    fig = plt.figure(figsize=(W, H), dpi=220)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, W)
    ax.set_ylim(0, H)
    ax.axis("off")

    x_end = x_start + pitch * (len(events) - 1) + 0.34

    for i, (_, y) in enumerate(LANES):
        ax.add_patch(Rectangle((X0, y - LANE_H / 2), x_end - X0, LANE_H,
                               facecolor=LANE_A if i % 2 == 0 else LANE_B,
                               edgecolor="none", zorder=0))
        ax.plot([X0, x_end], [y + LANE_H / 2] * 2, color="#E3E9F2", lw=0.6, zorder=1)

    for name, y in LANES:
        ax.add_patch(FancyBboxPatch((0.08, y - 0.27), 0.96, 0.54,
                                    boxstyle="round,pad=0.02,rounding_size=0.05",
                                    facecolor=NAVY, edgecolor="none", zorder=3))
        ax.text(0.56, y, name, ha="center", va="center", color="white",
                fontsize=7.4, zorder=4)

    for x0, x1, label in bands:
        ax.add_patch(Rectangle((x0, 7.20), x1 - x0, 0.28, facecolor="#E8EEF7",
                               edgecolor="none", zorder=2))
        ax.text((x0 + x1) / 2, 7.34, label, ha="center", va="center",
                fontsize=8.0, color=NAVY, zorder=3)

    for index, (n, src, dst, text, dashed) in enumerate(events):
        x = x_start + pitch * index
        y1, y2 = Y[src], Y[dst]
        color = GREY if dashed else NAVY
        style = (0, (3.6, 2.0)) if dashed else "solid"

        if src == dst:
            ax.add_patch(Arc((x, y1 + 0.15), 0.32, 0.26, theta1=5, theta2=200,
                             color=NAVY, lw=0.9, zorder=5))
            ax.annotate("", xy=(x - 0.152, y1 + 0.11), xytext=(x - 0.168, y1 + 0.185),
                        arrowprops={"arrowstyle": "-|>", "color": NAVY, "lw": 0.85,
                                    "mutation_scale": 6}, zorder=6)
            ax.add_patch(Circle((x - 0.32, y1), 0.083, facecolor=NAVY,
                                edgecolor="white", lw=0.7, zorder=7))
            ax.text(x - 0.32, y1, str(n), ha="center", va="center", color="white",
                    fontsize=5.4, zorder=8)
            ax.text(x - 0.20, y1 + 0.40, wrap(text, 8.0, 2), ha="left", va="bottom",
                    fontsize=font, color=TEXT, linespacing=1.42, zorder=6)
            continue

        ax.plot([x - 0.32, x], [y1, y1], color=color, lw=1.0, ls=style, zorder=5)
        ax.plot([x, x], [y1, y2], color=WIRE, lw=0.75, ls=style, zorder=4)
        step = 0.16 if y2 > y1 else -0.16
        ax.annotate("", xy=(x, y2), xytext=(x, y2 - step),
                    arrowprops={"arrowstyle": "-|>", "color": color, "lw": 0.95,
                                "mutation_scale": 7}, zorder=6)

        ax.add_patch(Circle((x - 0.32, y1), 0.083, facecolor=NAVY,
                            edgecolor="white", lw=0.7, zorder=7))
        ax.text(x - 0.32, y1, str(n), ha="center", va="center", color="white",
                fontsize=5.4, zorder=8)

        ax.text(x - 0.20, y1 + 0.12, wrap(text, wrap_limit, 3), ha="left", va="bottom",
                fontsize=font, color=TEXT, linespacing=1.42, zorder=6)

    # ---- 底部要点 ----
    ax.plot([1.16, x_end], [1.02, 1.02], color="#E3E9F2", lw=0.7)
    for i, (title, body) in enumerate(notes):
        nx = 1.22 + i * 2.95
        ax.add_patch(Rectangle((nx, 0.76), 0.055, 0.055, facecolor=ACCENT,
                               edgecolor="none"))
        ax.text(nx + 0.12, 0.785, title, fontsize=6.6, color=TEXT, va="center")
        ax.text(nx, 0.62, body, fontsize=5.7, color=MUTED, va="top", linespacing=1.45)

    ax.plot([1.22, 1.60], [0.24, 0.24], color=NAVY, lw=1.0)
    ax.text(1.66, 0.24, "同步调用", fontsize=6.0, va="center", color=TEXT)
    ax.plot([2.40, 2.78], [0.24, 0.24], color=GREY, lw=1.0, ls=(0, (3.6, 2.0)))
    ax.text(2.84, 0.24, "返回 / 异步推送", fontsize=6.0, va="center", color=TEXT)
    ax.plot([4.02, 4.40], [0.24, 0.24], color=WIRE, lw=0.9)
    ax.text(4.46, 0.24, "泳道间跳转", fontsize=6.0, va="center", color=TEXT)
    ax.text(x_end, 0.24, legend_note, fontsize=6.0, va="center", ha="right",
            color=MUTED)

    fig.savefig(path, dpi=220, facecolor="white")
    plt.close(fig)
    print(f"saved: {path}")


PAGE1 = [
    (1, "用户 / 前端", "API 层", "POST 发起深度分析", False),
    (2, "API 层", "任务状态", "建任务，返回\n202 job_id", False),
    (3, "用户 / 前端", "API 层", "[loop 轮询任务状态]\nGET /job/{id}", True),
    (4, "任务状态", "任务状态", "后台做前置评估", False),
    (5, "任务状态", "用户 / 前端", "[opt 信息不足]\n澄清中 · 问题", True),
    (6, "用户 / 前端", "任务状态", "提交答复", False),
    (7, "任务状态", "API 层", "重新评估后放行", False),
    (8, "API 层", "Agent + LLM", "启动 Agent，\n注入任务简报与基线", False),
    (9, "Agent + LLM", "Agent + LLM", "读技能、预览议题数据", False),
    (10, "Agent + LLM", "工具与语义层", "提交分析计划", False),
    (11, "工具与语义层", "Agent + LLM", "计划校验通过", True),
    (12, "Agent + LLM", "任务状态", "停在待大纲审查", True),
    (13, "任务状态", "用户 / 前端", "子问题大纲\n+ plan_json", True),
    (14, "用户 / 前端", "API 层", "POST outline\n确认", False),
]

PAGE2 = [
    (15, "API 层", "Agent + LLM", "恢复执行", False),
    (16, "Agent + LLM", "工具与语义层", "[loop 计划逐项执行]\n语义聚合、取负面证据", False),
    (17, "工具与语义层", "Agent + LLM", "行集、口径、claim_id", True),
    (18, "Agent + LLM", "门禁与发布", "提交报告", False),
    (19, "门禁与发布", "Agent + LLM", "门禁校验", True),
    (20, "门禁与发布", "Agent + LLM", "[alt 未通过]\n拒绝原因", True),
    (21, "Agent + LLM", "门禁与发布", "修订后重提", False),
    (22, "门禁与发布", "门禁与发布", "落盘 pending_review", False),
    (23, "门禁与发布", "任务状态", "done + 结果字段", True),
    (24, "任务状态", "用户 / 前端", "done + 报告", True),
]

HERE = Path(__file__).resolve().parent

draw_page(
    HERE / "workflow-lanes-1.png", PAGE1, x_start=1.60, pitch=0.82,
    bands=[(X0, 12.60, "规划：提交 → 澄清 → 计划 → 大纲确认（第 1–14 步）")],
    font=6.2,
    notes=[
        ("异步受理", "POST 立即返回 202 job_id，前端轮询，不占连接"),
        ("澄清分支", "信息不足时停在澄清中，用户答复后重新评估"),
        ("计划先行", "先提交分析计划，服务端校验方法/维度/口径后才执行"),
        ("人工闸门", "第 12–14 步：停在待大纲审查，POST outline 确认才恢复"),
    ],
    legend_note="编号 1–14 与原时序图一致",
)

draw_page(
    HERE / "workflow-lanes-2.png", PAGE2, x_start=1.60, pitch=1.15,
    bands=[(X0, 4.30, "执行（第 15–17 步）"),
           (4.30, 12.29, "交付：报告 → 门禁 → 落盘（第 18–24 步）")],
    font=6.9,
    notes=[
        ("预算约束", "18 次调用 / 6 次错误 / 4 次提交，超限强制收口"),
        ("执行留痕", "每项返回行集、口径与 claim_id，作为报告溯源"),
        ("发布门禁", "9 项校验：结构、版本、品牌、claim_id、数字来源"),
        ("可恢复", "未通过只返回修订要求，中间结果不丢，重提续跑"),
    ],
    legend_note="编号 15–24 与原时序图一致",
    wrap_limit=12.0,
)
