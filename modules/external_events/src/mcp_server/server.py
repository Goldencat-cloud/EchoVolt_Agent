"""FastMCP server（task 2.4）：暴露 product_timeline_research，默认 stdio。

返回契约：摘要（status/事件数/落盘路径），完整时间线只落盘（用户决策）。
"""
from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from . import core, storage
from .volcengine import VolcengineConfigError

mcp = FastMCP("product-timeline-research")


@mcp.tool()
def product_timeline_research(
    brand: str,
    product: str,
    aspects: list[str] | None = None,
    time_from: str | None = None,
    time_to: str | None = None,
    domain_hint: str | None = None,
    official_domains: list[str] | None = None,
) -> dict:
    """对【品牌+产品】做跨领域深度调研，产出聚合事件集并落盘。

    Args:
        brand: 品牌名（如 "小米"）
        product: 产品名（如 "SU7"）
        aspects: 研究主题子集，可选 product/competitor/policy/tech/public，缺省全部
        time_from: 时间窗起点 YYYY-MM-DD，可选
        time_to: 时间窗终点 YYYY-MM-DD，可选
        domain_hint: 领域提示（如 "汽车"/"手机"），可选，用于增强检索
        official_domains: 品牌官方域名列表（自动定为 T1），可选

    Returns:
        摘要 dict：status / event_count / output_path。完整事件集在 output_path 文件中。
    """
    try:
        timeline = core.run(brand=brand, product=product, aspects=aspects,
                            time_from=time_from, time_to=time_to,
                            domain_hint=domain_hint, official_domains=official_domains)
    except VolcengineConfigError as e:
        return {"status": "config_error", "error": str(e)}
    except ValueError as e:
        return {"status": "input_error", "error": str(e)}
    path = storage.save_timeline(timeline)
    return storage.summary(timeline, path)
