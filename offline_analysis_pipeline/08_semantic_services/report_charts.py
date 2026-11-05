"""Deterministic SVG chart rendering for published deep-agent reports (auto-034).

Agents declare a per-workstream visualization intent (auto-031 plan schema v2)
and python_analyze results may carry a gate-validated ``chart`` dict — but until
now nothing rendered either, so published reports showed tables only. This
module renders stdlib-only SVG charts from the SAME verified numbers
(provenance.json), never new data: no chart is drawn without a matching
verified step. Rendering failures skip that chart (with no placeholder), keeping
publication independent of chart quality.

渲染类型：``bar`` / ``line`` / ``pie`` 出 SVG；``table`` 由正文表格承载，不生成图片
（计划仍接受该声明，用于表达"以表格呈现"的意图）。

字段匹配：x/y 声明与行字段比较时忽略大小写、下划线与驼峰差异——
``negativeShare`` 与 ``negative_share`` 等价，语义层指标名可直接用于 y。
"""
from __future__ import annotations

import html
import math
import re
from typing import Any

MAX_POINTS = 16
BAR_W, LABEL_W = 400, 200
_LINE_W, _LINE_H = 680, 220
_COLOR = "#2f6fb3"
_TEXT = "#12233d"


def _fmt(value: float) -> str:
    """0–1 的占比按百分数展示，其余按数值展示（一位小数）。"""
    if 0 <= value <= 1:
        return f"{value * 100:.1f}%"
    return f"{value:.1f}"


def _esc(text: str) -> str:
    return html.escape(str(text), quote=True)


def _norm(key: Any) -> str:
    """字段名归一：忽略大小写、下划线与驼峰差异（negativeShare ≡ negative_share）。"""
    return re.sub(r"[^a-z0-9]", "", str(key).lower())


def _pick_key(candidates: list[Any], rows: list[dict[str, Any]]) -> str | None:
    """按候选顺序找第一个真实存在的行字段，比较用归一化形式。"""
    present = {_norm(k): k for row in rows if isinstance(row, dict) for k in row}
    for candidate in candidates:
        if not candidate:
            continue
        actual = present.get(_norm(candidate))
        if actual is not None:
            return actual
    return None


_X_FALLBACKS = ["aspect", "month", "time_month", "key", "product_label",
                "claim_type", "sentiment", "journey", "ownership", "experience"]
# 语义层指标（驼峰）与快照视图列（下划线）都要认
_Y_FALLBACKS = ["negative_share", "negativeShare", "curatedNegativeShare",
                "productNegativeShare", "n", "negative", "claims", "productClaims",
                "posts", "productPosts", "negative_posts", "negativePosts"]


def _points_from_rows(rows: list[dict[str, Any]], viz: dict[str, Any]) -> list[tuple[str, float]]:
    if not isinstance(rows, list):
        return []
    x_key = _pick_key([viz.get("x"), *_X_FALLBACKS], rows)
    y_key = _pick_key([viz.get("y"), *_Y_FALLBACKS], rows)
    if not x_key or not y_key:
        return []
    points: list[tuple[str, float]] = []
    for row in rows:
        try:
            points.append((str(row.get(x_key)), float(row.get(y_key))))
        except (TypeError, ValueError):
            continue
    return points[:MAX_POINTS]


def _points_from_chart(chart: dict[str, Any]) -> list[tuple[str, float]]:
    points: list[tuple[str, float]] = []
    for item in (chart or {}).get("data") or []:
        if not isinstance(item, dict):
            continue
        try:
            points.append((str(item.get("x")), float(item.get("y"))))
        except (TypeError, ValueError):
            continue
    return points[:MAX_POINTS]


def _bar_svg(title: str, points: list[tuple[str, float]]) -> str:
    row_h = 28
    width = LABEL_W + BAR_W + 70
    height = 36 + row_h * len(points) + 8
    vmax = max((abs(y) for _, y in points), default=1.0) or 1.0
    # viewBox 必须与坐标系统一：前端 max-width:100% 缩放视口时内容等比缩放，
    # 否则窄容器直接裁掉右侧数值标签（Owner 2026-10-28 反馈的溢出）
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" '
             f'height="{height}" viewBox="0 0 {width} {height}" '
             f'role="img" aria-label="{_esc(title)}">']
    parts.append(f"<text x=\"0\" y=\"16\" font-size=\"13\" fill=\"{_TEXT}\""
                 f">{_esc(title)}</text>")
    for index, (label, value) in enumerate(points):
        y = 30 + index * row_h
        width = max(2, int(BAR_W * abs(value) / vmax))
        parts.append(f'<text x="0" y="{y + 13}" font-size="12" fill="{_TEXT}">'
                     f"{_esc(label[:14])}</text>")
        parts.append(f'<rect x="{LABEL_W}" y="{y}" width="{width}" height="18" '
                     f'fill="{_COLOR}"></rect>')
        parts.append(f'<text x="{LABEL_W + width + 6}" y="{y + 13}" font-size="11" '
                     f'fill="{_TEXT}">{_esc(_fmt(value))}</text>')
    parts.append("</svg>")
    return "".join(parts)


def _line_svg(title: str, points: list[tuple[str, float]]) -> str:
    if len(points) == 1:
        return _bar_svg(title, points)
    pad_x, pad_y = 46, 30
    vmax = max((y for _, y in points), default=1.0) or 1.0
    vmin = min(0.0, min(y for _, y in points))
    span = (vmax - vmin) or 1.0
    step_x = (_LINE_W - 2 * pad_x) / (len(points) - 1)
    coords: list[tuple[float, float]] = []
    for index, (_, value) in enumerate(points):
        x = pad_x + index * step_x
        y = pad_y + (_LINE_H - 2 * pad_y) * (1 - (value - vmin) / span)
        coords.append((x, y))
    skip = max(1, (len(points) + 11) // 12)
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{_LINE_W}" '
             f'height="{_LINE_H + 26}" viewBox="0 0 {_LINE_W} {_LINE_H + 26}" '
             f'role="img" aria-label="{_esc(title)}">']
    parts.append(f"<text x=\"0\" y=\"16\" font-size=\"13\" fill=\"{_TEXT}\""
                 f">{_esc(title)}</text>")
    parts.append("<polyline fill=\"none\" stroke=\"" + _COLOR + "\" stroke-width=\"2\" "
                 "points=\"" + " ".join(f"{x:.1f},{y:.1f}" for x, y in coords) + "\"/>")
    for index, ((x, y), (label, value)) in enumerate(zip(coords, points)):
        parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3" fill="{_COLOR}"></circle>')
        if index % skip == 0:
            parts.append(f'<text x="{x:.1f}" y="{_LINE_H - 6}" font-size="10" '
                         f'text-anchor="middle" fill="{_TEXT}">{_esc(label[:7])}</text>')
    parts.append(f'<text x="{_LINE_W - pad_x}" y="{pad_y - 8}" font-size="10" '
                 f'text-anchor="end" fill="{_TEXT}">{_esc(_fmt(vmax))}</text>')
    parts.append("</svg>")
    return "".join(parts)


_PIE_COLORS = ("#2f6fb3", "#5b9bd5", "#a5c8e8", "#e8a33d",
               "#c0504d", "#9bbb59", "#8064a2", "#4bacc6")
_PIE_MAX_SLICES = 8


def _pie_svg(title: str, points: list[tuple[str, float]]) -> str:
    """扇形按占比绘制；单一片段退化为整圆，图例标出百分比。"""
    points = points[:_PIE_MAX_SLICES]
    total = sum(abs(value) for _, value in points)
    if total <= 0:
        return _bar_svg(title, points)
    radius, cx, cy = 96, 116, 128
    width, height = 560, 268
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" '
             f'height="{height}" viewBox="0 0 {width} {height}" '
             f'role="img" aria-label="{_esc(title)}">']
    parts.append(f"<text x=\"0\" y=\"16\" font-size=\"13\" fill=\"{_TEXT}\""
                 f">{_esc(title)}</text>")
    angle = -math.pi / 2  # 从 12 点方向开始
    for index, (label, value) in enumerate(points):
        frac = abs(value) / total
        color = _PIE_COLORS[index % len(_PIE_COLORS)]
        end = angle + frac * 2 * math.pi
        if frac >= 0.9999:
            parts.append(f'<circle cx="{cx}" cy="{cy}" r="{radius}" fill="{color}"></circle>')
        else:
            x1, y1 = cx + radius * math.cos(angle), cy + radius * math.sin(angle)
            x2, y2 = cx + radius * math.cos(end), cy + radius * math.sin(end)
            large = 1 if frac > 0.5 else 0
            parts.append(f'<path d="M {cx},{cy} L {x1:.1f},{y1:.1f} '
                         f'A {radius},{radius} 0 {large},1 {x2:.1f},{y2:.1f} Z" '
                         f'fill="{color}"></path>')
        legend_y = 34 + index * 24
        parts.append(f'<rect x="250" y="{legend_y - 10}" width="12" height="12" '
                     f'fill="{color}"></rect>')
        parts.append(f'<text x="270" y="{legend_y}" font-size="12" fill="{_TEXT}">'
                     f"{_esc(label[:16])}  {frac * 100:.1f}%</text>")
        angle = end
    parts.append("</svg>")
    return "".join(parts)


def _match_step(stream: dict[str, Any], steps: list[dict[str, Any]]) -> dict[str, Any] | None:
    """找该工作项对应的已验证步骤：方法名+议题（+声明参数）一致。

    带 params 的方法（聚合原语、语义聚合）必须按参数精确匹配——否则多个
    同方法的工作项会一起命中第一条步骤，画出同一份数据的两张图。
    """
    stream_params = stream.get("params")
    for step in steps:
        if step.get("kind") not in {"method", "baseline"}:
            continue
        if step.get("method") != stream.get("method"):
            continue
        if (step.get("aspect") or None) != (stream.get("aspect") or None):
            continue
        if stream_params is not None \
                and (step.get("params") or None) != (stream_params or None):
            continue
        return step
    return None


def _step_rows(step: dict[str, Any]) -> list[dict[str, Any]]:
    if step.get("kind") == "baseline":
        rows = step.get("rows")
    else:
        rows = (step.get("result") or {}).get("rows")
    return rows if isinstance(rows, list) else []


def charts_for(meta: dict[str, Any], provenance: dict[str, Any]) -> list[dict[str, Any]]:
    """按计划的 visualization 意图，从已验证步骤渲染图表（无数据则跳过）。"""
    streams = ((meta.get("analysis_plan") or {}).get("workstreams")) or []
    steps = provenance.get("verified_steps") or []
    python_charts: list[dict[str, Any]] = []
    for step in steps:
        chart = (step.get("result") or {}).get("chart") if step.get("kind") == "python" else None
        if isinstance(chart, dict) and chart.get("title"):
            python_charts.append(chart)
    charts: list[dict[str, Any]] = []
    for stream in streams:
        viz = stream.get("visualization") if isinstance(stream, dict) else None
        # table 由正文表格承载，不生成图片（保持一致，避免"声明了却没东西"）
        if not isinstance(viz, dict) or viz.get("type") not in {"bar", "line", "pie"}:
            continue
        title = str(viz.get("title") or stream.get("question") or "").strip()
        points: list[tuple[str, float]] = []
        # 数据源优先级 1：python 步骤的 gate 校验 chart（标题+类型匹配，含自定义统计）
        matched = next((c for c in python_charts
                        if c.get("type") == viz.get("type") and c.get("title") == title), None)
        if matched:
            points = _points_from_chart(matched)
        # 数据源优先级 2：方法步骤的已验证 rows（x/y 键按意图+常见字段映射）
        if not points:
            step = _match_step(stream, steps)
            if step is not None:
                points = _points_from_rows(_step_rows(step), viz)
        if not points:
            continue
        kind = viz.get("type")
        if kind == "line":
            svg = _line_svg(title, points)
        elif kind == "pie":
            svg = _pie_svg(title, points)
        else:
            svg = _bar_svg(title, points)
        anchor = title or str(stream.get("aspect") or "")
        charts.append({"title": title, "anchor": anchor, "svg": svg})
    return charts
