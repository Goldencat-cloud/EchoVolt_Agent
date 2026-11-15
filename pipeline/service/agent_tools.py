"""Tools exposed to the deep agent.

Everything the agent can see comes from the semantic layer: predefined analysis
methods over the mirror, the preloaded pandas frames in the sandbox, and the
curated evidence records. Raw tables are never exposed.
"""
from __future__ import annotations

import functools
import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any, Callable

from research import analysis_methods
import sandbox
import task_brief
from research import service
import report_gate
import report_publisher
import report_source
from research import catalog as research_catalog
from langchain_core.tools import tool

MAX_TOOL_ERRORS = 6
# E2E 2026-10-28：3 次常被"首轮全量错误 + 收尾漏网 1 个数字"耗尽，4 次可挽回近失型失败
MAX_SUBMIT_ATTEMPTS = 4
MAX_CODE_FAILURES = 3
MAX_WORKSTREAMS = 6
MAX_SUCCESSFUL_TOOL_CALLS = 18
MAX_PLAN_CHARS = 8000
PLAN_DIMENSIONS = {"aspect", "sentiment", "journey", "ownership", "product", "time", "other"}
METHOD_DIMENSIONS = research_catalog.METHOD_DIMENSIONS

def record_tool_error(context: dict[str, Any]) -> dict[str, int]:
    """统一错误预算记账（本轮重构收口）：工具体与包装器共用同一入口。

    此前工具体内散布 13 处手工 `context["tool_errors"] += 1`，包装器再兜底
    补记一次（`if unchanged` 防双计）。现在工具体一律调用本函数；包装器的
    异常路径与"error 返回但未记账"兜底逻辑保持不变，计数语义与重构前一致。
    """
    context["tool_errors"] = context.get("tool_errors", 0) + 1
    return {"tool_errors": context["tool_errors"],
            "error_budget_left": max(0, MAX_TOOL_ERRORS - context["tool_errors"])}


# ---- 8.8 沙箱错误提示映射与预算回传（D13 配套）----

def _budget_snapshot(context: dict[str, Any]) -> dict[str, Any]:
    """Remaining calls/errors budget with an 80% warning (attached to responses)."""
    calls_left = max(0, MAX_SUCCESSFUL_TOOL_CALLS - context.get("successful_tool_calls", 0))
    errors_left = max(0, MAX_TOOL_ERRORS - context.get("tool_errors", 0))
    snapshot: dict[str, Any] = {"successful_calls_left": calls_left,
                                "error_budget_left": errors_left}
    if calls_left <= MAX_SUCCESSFUL_TOOL_CALLS * 0.2:
        snapshot["budget_warning"] = "调用预算已消耗 80%：优先聚合既有结果并提交报告。"
    return snapshot


def _semantic_columns() -> dict[str, list[str]]:
    """Actual column names of the semantic views (KeyError repair hint)."""
    from semantic.adapters import compat_views as db_mirror
    con = db_mirror.connect()
    try:
        return {name: [row[1] for row in con.execute(f"PRAGMA table_info({view})")]
                for name, view in task_brief._FRAME_VIEWS.items()}
    finally:
        con.close()


def _semantic_column_stats() -> list[str]:
    """Non-null counts and distinct values of key columns (empty-result hint)."""
    from semantic.adapters import compat_views as db_mirror
    targets = (("claims.aspect", "semantic_claim_fact", "aspect"),
               ("claims.date", "semantic_claim_fact", "date"),
               ("claims.sentiment", "semantic_claim_fact", "sentiment"),
               ("metrics.aspect", "semantic_aspect_metric", "aspect"))
    con = db_mirror.connect()
    try:
        return [f"{label} 非空 {n} / 去重 {d}"
                for label, table, col in targets
                for n, d in [con.execute(
                    f"SELECT COUNT({col}), COUNT(DISTINCT {col}) FROM {table}").fetchone()]]
    finally:
        con.close()


def _sandbox_error_hint(outcome: dict[str, Any]) -> str | None:
    """Map a sandbox failure to an actionable repair hint (8.8)."""
    error = str(outcome.get("error") or "")
    if "KeyError" in error:
        listing = "；".join(f"{name}: {', '.join(cols)}"
                           for name, cols in _semantic_columns().items())
        return f"列名不存在（{error}）。实际可用列——{listing}"
    if "AttributeError" in error:
        return ("属性/方法名可能有误。DataFrame 常用：groupby / sort_values / "
                "value_counts / merge / pivot_table / head / describe；"
                "列引用用字典式 frames.metrics['列名']。")
    if "执行超时" in error:
        return ("执行超时：先过滤再聚合、避免全表排序与循环，"
                "把计算拆成多次小调用。")
    return None


def _is_empty_result(result: Any) -> bool:
    if result is None:
        return True
    if isinstance(result, (list, dict, str)) and not result:
        return True
    if isinstance(result, str) and result.strip().startswith("Empty DataFrame"):
        return True
    return False


MAX_CHART_CHARS = 20_000


def _planned_aspect(stream: dict[str, Any]) -> str | None:
    """计划工作项的议题。

    语义计划把议题写在 `params.filters.aspect`（工作项 aspect 恒为 null）；
    旧计划写在 `aspect`。凡是"按计划授权某议题"的判断都走这里，避免同一个
    语义在两处各写一遍、只修一处（E2E 2026-11-03 曾因此三次报告被拒）。
    """
    if stream.get("aspect"):
        return stream["aspect"]
    filters = (stream.get("params") or {}).get("filters") or {}
    return filters.get("aspect") if isinstance(filters, dict) else None


def _evidence_authorised(stream: dict[str, Any], aspect: str | None) -> bool:
    """该工作项是否允许就某议题取证。

    工作项限定了议题（`params.filters.aspect`）时，只能取该议题的证据；没有限定
    （例如按拥有状态切分、议题不固定）时，不限制议题——否则"要引文但没锁定议题"
    的工作项永远取不到证据，报告会以"分析项未完成"被反复退回（E2E 2026-11-04）。
    """
    if not stream.get("requires_evidence"):
        return False
    planned = _planned_aspect(stream)
    return planned is None or planned == aspect


def plan_problems(plan_json: str) -> list[str]:
    """草案的确定性预检：只回答"这份草案能不能过"，不改任何状态。

    用途是**不打扰人审**：草案连参数校验都过不去时，批准它只会让工具返回错误、
    模型重写、再暂停一次（E2E 2026-11-03 一次运行里出现 4 次空转确认）。
    这里宁可漏判（返回空），也不误判——真正的权威校验仍在 submit_analysis_plan。
    """
    try:
        plan = json.loads(plan_json)
    except (TypeError, json.JSONDecodeError):
        return ["plan_json 不是合法 JSON"]
    if not isinstance(plan, dict):
        return ["草案必须是对象"]
    streams = plan.get("workstreams")
    if not isinstance(streams, list) or not streams:
        return ["workstreams 必须是非空数组"]
    problems: list[str] = []
    if len(streams) > MAX_WORKSTREAMS:
        problems.append(f"workstream 数超过上限 {MAX_WORKSTREAMS}")
    for stream in streams[:MAX_WORKSTREAMS]:
        if not isinstance(stream, dict):
            problems.append("workstream 必须是对象")
            continue
        if stream.get("method") != analysis_methods.SEMANTIC_METHOD:
            problems.append(f"{stream.get('id')}: method 只能是 semantic_aggregate")
            continue
        _, errors = analysis_methods.validate_params(
            analysis_methods.SEMANTIC_METHOD, stream.get("params") or {})
        if errors:
            problems.append(f"{stream.get('id')}: {errors[0]}")
    return problems


def _validate_chart(outcome: dict[str, Any]) -> dict[str, Any]:
    """auto-031 3.1：python_analyze 的 chart 键校验——非法/超限降级（丢弃并
    加 warning），不使整个分析结果失败。"""
    chart = outcome.get("chart")
    if chart is None:
        return outcome
    valid = (isinstance(chart, dict)
             and chart.get("type") in task_brief.VISUALIZATION_TYPES
             and isinstance(chart.get("title"), str) and bool(chart.get("title")))
    encoded = None
    if valid:
        try:
            encoded = json.dumps(chart, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            valid = False
        else:
            if len(encoded) > MAX_CHART_CHARS:
                valid = False
    if not valid:
        outcome = {k: v for k, v in outcome.items() if k != "chart"}
        outcome = {**outcome,
                   "warnings": list(outcome.get("warnings") or []) + ["chart_invalid_dropped"]}
    return outcome


def _empty_result_hint() -> str:
    return ("结果为空。关键列数据概览（非空计数 / 去重值数）——"
            + "；".join(_semantic_column_stats())
            + "。请检查过滤条件取值是否来自数据目录中的枚举。")


def _claim_ids(value: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "claim_id" and item:
                found.add(str(item))
            else:
                found.update(_claim_ids(item))
    elif isinstance(value, (list, tuple)):
        for item in value:
            found.update(_claim_ids(item))
    return found


def _hit_snippet(text: str, terms: list[str], radius: int = 70) -> str:
    """围绕首个命中词截取一段原文，供前端展示"为什么命中"。"""
    body = str(text or "").strip()
    if not body:
        return ""
    center = -1
    for term in terms:
        if not term:
            continue
        idx = body.lower().find(term.lower())
        if idx >= 0 and (center < 0 or idx < center):
            center = idx
    if center < 0:
        return body[:radius * 2] + ("…" if len(body) > radius * 2 else "")
    start = max(0, center - radius)
    end = min(len(body), center + radius)
    snippet = body[start:end].strip()
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(body) else ""
    return f"{prefix}{snippet}{suffix}"


def build_tools(context: dict[str, Any]) -> list[Callable]:
    """Build the tool set bound to a per-run context (captures submissions).

    Tool errors are returned to the model as messages so it can self-correct;
    a raised exception would kill the whole agent graph.
    """

    context.setdefault("tool_errors", 0)
    context.setdefault("successful_tool_calls", 0)
    context.setdefault("submissions", [])

    def guarded(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> str:
            if (context.get("successful_tool_calls", 0) >= MAX_SUCCESSFUL_TOOL_CALLS
                    and func.__name__ not in {"submit_report"}):
                return json.dumps({"error": "tool_call_budget_exhausted",
                                   "message": "分析调用次数已达上限；请基于已验证结果提交，或说明证据不足。"},
                                  ensure_ascii=False)
            if (context.get("tool_errors", 0) >= MAX_TOOL_ERRORS
                    and func.__name__ not in {"submit_report"}):
                return json.dumps({"error": "tool_error_budget_exhausted",
                                   "message": "工具错误预算已用尽；只能提交已有证据支持的结果。"},
                                  ensure_ascii=False)
            try:
                errors_before = context.get("tool_errors", 0)
                result = func(*args, **kwargs)
                try:
                    payload = json.loads(result)
                except (TypeError, json.JSONDecodeError):
                    payload = {}
                # 失败判定看 error 的真值而非键是否存在：python_analyze 的成功响应
                # 原样带出沙箱 outcome 的 "error": null，按键判定会把每次成功代码
                # 调用误记为工具错误，白耗错误预算并提前触发 budget_exhausted。
                failed = isinstance(payload, dict) and bool(payload.get("error"))
                if failed and func.__name__ == "submit_report":
                    # D7 P2-6：门禁拒绝/计划未完成由 submit_attempts 与
                    # gate_rejections 记账，既不占错误预算，也不是一次成功调用
                    # （先前落到 else 分支会给提交预算凭空 +1）。
                    pass
                elif failed:
                    # Count every rejected call, including repeated ordering or
                    # duplicate-plan errors that do not raise exceptions.
                    if context.get("tool_errors", 0) == errors_before:
                        context["tool_errors"] = errors_before + 1
                else:
                    context["successful_tool_calls"] = context.get("successful_tool_calls", 0) + 1
                return result
            except Exception as exc:
                stats = record_tool_error(context)
                budget_left = stats["error_budget_left"]
                return json.dumps({"error": f"{type(exc).__name__}: {exc}",
                                   "hint": "修正参数或代码后重试",
                                   "error_budget_left": budget_left,
                                   **({"force_stop": "错误预算已用尽：不要再重试同类调用，"
                                                      "基于已有结果提交报告，或如实说明数据不支持。"}
                                     if budget_left == 0 else {})},
                                  ensure_ascii=False)
        return wrapper

    @tool
    @guarded
    def semantic_overview(aspects: str = "") -> str:
        """何时使用（计划阶段专用）：① 任务简报已附数据目录，通常无需调用；
        ② 起草计划前想预览某些议题的数据支撑时，传 aspects 参数调用一次——
        返回各议题的精选证据样本量、按月计数分布与代表性观点（带 claim_id）。
        参数 aspects：议题名的 JSON 数组字符串，如 '["充电与补能","可靠性与故障"]'；
        必须是任务简报议题清单中的精确名称，非法名称报错。
        边界：预览用于判断问题是否值得问/样本是否支撑（<5 条须标注支撑不足或剔除），
        不产生可引用结论；执行阶段的取证走白名单方法/证据工具。重复调用浪费预算。
        不传 aspects 时返回：各数据框的列、行数、示例行与口径说明（简报缺失时用）。"""
        if aspects.strip():
            try:
                names = json.loads(aspects)
            except (TypeError, json.JSONDecodeError):
                return json.dumps({"error": "invalid_aspects_param",
                                   "message": "aspects 须为议题名 JSON 数组字符串。",
                                   "example": '["充电与补能"]'}, ensure_ascii=False)
            if not isinstance(names, list) or not all(isinstance(n, str) for n in names):
                return json.dumps({"error": "invalid_aspects_param",
                                   "message": "aspects 须为字符串数组。"}, ensure_ascii=False)
            if not names:
                return json.dumps({"error": "invalid_aspects_param",
                                   "message": "aspects 不能为空数组。"}, ensure_ascii=False)
            return json.dumps(service.aspects_preview(names), ensure_ascii=False, default=str)
        info = sandbox.semantic_frames_info()
        info["usage"] = {
            "metrics": "全量口径：每议题的 claims/posts/negative/negative_posts/negative_share",
            "claims": "精选观点事实表（core/potential 子集）：aspect/sentiment/journey/ownership/experience 等",
            "evidence": "精选观点证据：quote/title/url/date（可引用，附 claim_id）",
            "post_scope": "帖子→产品范围映射（不含内容）",
        }
        return json.dumps(info, ensure_ascii=False, default=str)

    @tool
    @guarded
    def submit_analysis_plan(plan_json: str) -> str:
        """何时使用：接到分析任务后、执行任何 run_analysis_method / get_negative_evidence
        之前必须先调用本工具；整个运行只调用一次，计划获批后不可更改。

        参数 plan_json：完整分析草案 JSON 字符串（≤8000 字符），结构：
        {"coverage":"一句话说明如何覆盖问题","use_python":false,"workstreams":[...]}
        每个 workstream：{"id":"w1","question":"子问题","aspect":"...或 null",
        "method":"白名单方法名",
        "visualization": 可选 {"type":"bar|line|pie|table","x":"列","y":"列","title":"标题"}}
        method 只接受 "semantic_aggregate"（语义层聚合）：aspect 须为 null，必须提供 params
        {"metrics":["指标名",...],"dimensions":["维度名",...],"filters":{},"time":{},
         "order":[{"field":"...","dir":"asc|desc"}],"limit":n,"population":"口径名"}；
        指标/维度/口径名以任务简报或语义目录为准，越界会整单拒绝。执行时调用
        run_semantic_aggregate，参数与计划完全一致。其口径为模型口径，与快照口径
        不同源，报告引用处须写明"模型口径"，不得与快照数字混用。

        说明：dimension 由服务端从 params.dimensions 推导，无需填写；requires_evidence
        须显式声明（true 表示这一项需要引文佐证，执行时必须取得带 claim_id 的证据并在
        报告中引用）。语义层只有一个聚合方法，无法从方法名推导证据需求。

        完整示例（覆盖"各议题负面占比排序 + 该议题负面说法的月度走势"）：
        {"coverage":"先取各议题负面观点占比排序，再对最高的议题取月度走势",
         "use_python":false,"workstreams":[
          {"id":"w1","question":"各议题负面观点占比排序","aspect":null,
           "method":"semantic_aggregate",
           "params":{"metrics":["negativeShare","claims"],"dimensions":["aspect"],
                     "order":[{"field":"negativeShare","dir":"desc"}],"limit":16}},
          {"id":"w2","question":"可靠性与故障负面说法的月度走势","aspect":null,
           "method":"semantic_aggregate",
           "params":{"metrics":["curatedNegative"],"dimensions":["time_month"],
                     "filters":{"aspect":"可靠性与故障"},
                     "order":[{"field":"time_month","dir":"asc"}],"limit":60}}]}

        边界（违反任一条即整单拒绝并消耗 1 次错误预算，总共 6 次，请一次性改对）：
        - method 只能是 semantic_aggregate，不能自造或简写；
        - 议题过滤写在 params.filters 里（如 {"aspect":"可靠性与故障"}），工作项的 aspect 必须为 null；
        - 同一查询内所有指标必须同口径。curated 口径只有 curatedClaims / curatedNegative /
          curatedNegativeShare；其余（claims、negative、negativeShare、posts、negativePosts、
          product*）都是 experience 口径。跨口径的组合（如"精选负面条数"配"全量负面占比"）
          必须拆成两个 workstream，各自在 params 里写出 population；
        - 指标名、维度名与口径名以任务简报或语义目录为准；越界会整单拒绝并给出可用值；
        - 1–6 个 workstream；id 唯一且非空；method/params 组合不重复；question ≤500 字。

        返回：成功为 {"accepted":true,"plan":...,"instruction":...}；被拒为
        {"error":"invalid_workstream_fields","workstream":"w2","message":"具体哪个字段错、允许值是什么"}。
        被拒时按 message 修正全部字段后重新提交完整草案。"""
        if context.get("plan") is not None:
            return json.dumps({"error": "analysis_plan_already_submitted"}, ensure_ascii=False)
        if not isinstance(plan_json, str) or len(plan_json) > MAX_PLAN_CHARS:
            record_tool_error(context)
            return json.dumps({"error": "analysis_plan_too_large"}, ensure_ascii=False)
        try:
            plan = json.loads(plan_json)
        except (TypeError, json.JSONDecodeError):
            record_tool_error(context)
            return json.dumps({"error": "invalid_analysis_plan_json"}, ensure_ascii=False)
        if not isinstance(plan, dict) or not isinstance(plan.get("workstreams"), list):
            record_tool_error(context)
            return json.dumps({"error": "invalid_analysis_plan_shape"}, ensure_ascii=False)
        streams = plan["workstreams"]
        if not 1 <= len(streams) <= MAX_WORKSTREAMS or not plan.get("coverage"):
            record_tool_error(context)
            return json.dumps({"error": "invalid_analysis_plan_size_or_coverage",
                               "max_workstreams": MAX_WORKSTREAMS}, ensure_ascii=False)
        known_aspects = set(analysis_methods.aspects())
        ids: set[str] = set()
        method_aspects: set[tuple[str, str | None]] = set()
        normalized = []

        def reject(workstream_id: str, message: str, **extra: Any) -> str:
            record_tool_error(context)
            return json.dumps({"error": "invalid_workstream_fields",
                               "workstream": workstream_id, "message": message, **extra},
                              ensure_ascii=False)

        for stream in streams:
            if not isinstance(stream, dict):
                return reject("", "每个 workstream 必须是 JSON 对象。")
            stream_id = str(stream.get("id", "")).strip()
            method = str(stream.get("method", ""))
            aspect = stream.get("aspect")
            dimension = stream.get("dimension")
            if not stream_id or stream_id in ids:
                return reject(stream_id, "id 缺失、为空或与其他工作项重复。")
            if not stream.get("question") or len(str(stream.get("question", ""))) > 500:
                return reject(stream_id, "question 缺失或超过 500 字。")
            if method != analysis_methods.SEMANTIC_METHOD:
                return reject(stream_id, f"未知 method：{method}。当前只接受语义层聚合。",
                              allowed_methods=[analysis_methods.SEMANTIC_METHOD])
            # auto-042：method 已在上面收窄为 semantic_aggregate，这里不再有原语分支。
            clean_params: dict[str, Any] | None = None
            raw_params = stream.get("params")
            if not isinstance(raw_params, dict):
                return reject(stream_id,
                              "semantic_aggregate 工作项必须提供 params 对象"
                              "（metrics 必填，可选 dimensions/filters/time/order/limit/population）。")
            clean_params, param_errors = analysis_methods.validate_params(
                analysis_methods.SEMANTIC_METHOD, raw_params)
            if param_errors:
                return reject(stream_id, "semantic_aggregate 参数校验失败。",
                              details=param_errors)
            if aspect is not None:
                return reject(stream_id,
                              "semantic_aggregate 工作项的议题过滤放在 params.filters 中，"
                              "aspect 字段须为 null。")
            if dimension is not None and dimension not in METHOD_DIMENSIONS.get(method, set()):
                return reject(stream_id,
                              f"method {method} 只接受 dimension："
                              f"{sorted(METHOD_DIMENSIONS.get(method, set()))}。",
                              got=dimension)
            dedupe_key = f"{method}:{json.dumps(clean_params, sort_keys=True, ensure_ascii=False)}"
            if dedupe_key in method_aspects:
                return reject(stream_id, "同一 method/参数组合重复出现，请合并或改用其他组合。")
            if aspect is not None and aspect not in known_aspects:
                return reject(stream_id, f"未知 aspect：{aspect}。",
                              known_aspects=sorted(known_aspects))
            ids.add(stream_id)
            method_aspects.add(dedupe_key)
            # auto-031 2.1：可选 visualization 意图（type ∈ bar/line/pie/table）
            visualization = stream.get("visualization")
            viz_clean: dict[str, Any] | None = None
            if visualization is not None:
                if not isinstance(visualization, dict):
                    return reject(stream_id, "visualization 须为对象（type/x/y/title）。")
                vtype = visualization.get("type")
                if vtype not in task_brief.VISUALIZATION_TYPES:
                    return reject(stream_id,
                                  "visualization.type 必须是 "
                                  f"{'/'.join(sorted(task_brief.VISUALIZATION_TYPES))}。",
                                  got=vtype)
                viz_clean = {"type": vtype,
                             "x": str(visualization.get("x") or "")[:60] or None,
                             "y": str(visualization.get("y") or "")[:60] or None,
                             "title": str(visualization.get("title") or "")[:120] or None}
            # auto-032 计划瘦身：dimension/requires_evidence 由服务端推导
            #（旧计划含这两个字段时忽略，不拒绝）。
            if dimension is None:
                dims = (clean_params or {}).get("dimensions") or []
                dimension = ("product" if {"product", "product_label"} & set(dims)
                             else "time" if "time_month" in dims else "other")
            # 证据需求改为显式声明：语义层只有一个聚合方法，无法从方法名推导
            # "这一项要不要引文"。旧计划省略该字段时按不需要证据处理。
            derived_evidence = bool(stream.get("requires_evidence", False))
            normalized.append({"id": stream_id, "question": str(stream["question"]),
                               "dimension": dimension, "aspect": aspect, "method": method,
                               "requires_evidence": derived_evidence,
                               **({"params": clean_params} if clean_params is not None else {}),
                               **({"visualization": viz_clean} if viz_clean else {})})
        if not isinstance(plan.get("use_python", False), bool):
            record_tool_error(context)
            return json.dumps({"error": "invalid_use_python_type"}, ensure_ascii=False)
        context["plan"] = {"coverage": str(plan["coverage"]), "workstreams": normalized,
                            "use_python": plan.get("use_python", False)}
        instruction = "按每个 workstream 执行指定 method/aspect；完成后提交报告。"
        spec = context.get("delivery_spec")  # 8.10/D12：经批准后的工具结果注入（顺序合法）
        if isinstance(spec, dict):
            instruction += (f"交付规格：重点={spec.get('focus') or '未指定'}；"
                            f"受众={spec.get('audience') or '未指定'}——请在分析与报告中落实。")
        return json.dumps({"accepted": True, "plan": context["plan"],
                           "instruction": instruction},
                          ensure_ascii=False)

    def _plan_allows(method: str, aspect: str | None) -> bool:
        plan = context.get("plan")
        if plan is None:
            return bool(context.get("interactive"))
        return any(s["method"] == method and s["aspect"] == aspect
                   for s in plan["workstreams"])

    def _record_step(kind: str, result: dict[str, Any], **extra: Any) -> None:
        step = {"kind": kind, "result": result, **extra}
        step["claim_ids"] = sorted(_claim_ids(result))
        context.setdefault("verified_steps", []).append(step)
        context.setdefault("evidence_claim_ids", set()).update(step["claim_ids"])



    @tool
    @guarded
    def run_semantic_aggregate(params_json: str) -> str:
        """何时使用：分析计划中声明 method 为 semantic_aggregate 的工作项；参数必须与计划中
        该工作项的 params 完全一致（原样传参，不要增删字段）。

        参数 params_json：JSON 对象，metrics 必填。示例：
        {"metrics":["negativeShare","claims"],"dimensions":["aspect"],
         "filters":{"aspect":"可靠性与故障"},"time":{"start":"2026-01","end":"2026-06"},
         "order":[{"field":"negativeShare","dir":"desc"}],"limit":10,"population":"curated"}

        可用指标/维度/口径：见任务简报，或调用 semantic_overview 取目录（指标、维度、
        口径级与允许的切分维度）。一次可算多个指标与比率，比逐条调用更省预算。

        口径：模型口径（模型定义、构建期落库），与快照口径不同源；报告引用须写明
        "模型口径"。返回 rows + caliber + query_id + verification；verification 不通过
        的结果不可引用。"""
        from semantic.adapters import api as semantic_api

        try:
            params = json.loads(params_json or "{}")
        except (TypeError, json.JSONDecodeError):
            record_tool_error(context)
            return json.dumps({"error": "invalid_params_json"}, ensure_ascii=False)
        clean_params, param_errors = analysis_methods.validate_params(
            analysis_methods.SEMANTIC_METHOD, params)
        if param_errors:
            record_tool_error(context)
            return json.dumps({"error": "semantic_params_invalid", "details": param_errors},
                              ensure_ascii=False)
        plan = context.get("plan")
        if plan is None and not context.get("interactive"):
            record_tool_error(context)
            return json.dumps({"error": "analysis_plan_required"}, ensure_ascii=False)
        if plan is not None and not any(
                s["method"] == analysis_methods.SEMANTIC_METHOD
                and s.get("params") == clean_params for s in plan["workstreams"]):
            record_tool_error(context)
            return json.dumps({"error": "analysis_step_not_in_plan",
                               "message": "只能执行已批准草案中 semantic_aggregate 工作项"
                                          "声明的参数组合。"}, ensure_ascii=False)
        if not semantic_api.available():
            record_tool_error(context)
            return json.dumps({"error": "semantic_layer_unavailable",
                               "message": "当前链路没有语义层产物；请先构建语义库再重试。"},
                              ensure_ascii=False)
        try:
            result = analysis_methods.run(analysis_methods.SEMANTIC_METHOD, clean_params)
        except ValueError as exc:
            record_tool_error(context)
            return json.dumps({"error": "semantic_query_rejected", "details": str(exc)},
                              ensure_ascii=False)
        import verifier
        verdict = verifier.verify_step(result)
        if not verdict["ok"]:
            if verdict["errors"] and all("查询结果为空" in item for item in verdict["errors"]):
                empty_verdict = {**verdict, "ok": True, "empty_result": True}
                _record_step("method", result, method=analysis_methods.SEMANTIC_METHOD,
                             aspect=None, params=clean_params, verification=empty_verdict)
                return json.dumps({**result, "verification": empty_verdict,
                                   "hint": "结果为空：已登记为空结果；须在限制与不确定性"
                                           "章节说明，不得引用该结果的任何数字。"},
                                  ensure_ascii=False, default=str)
            record_tool_error(context)
            return json.dumps({"error": "analysis_verification_failed",
                               "verification": verdict,
                               "hint": "不要引用该结果；请更换查询或说明无法验证。"},
                              ensure_ascii=False)
        _record_step("method", result, method=analysis_methods.SEMANTIC_METHOD,
                     aspect=None, params=clean_params, verification=verdict)
        return json.dumps({**result, "verification": verdict}, ensure_ascii=False, default=str)

    @tool
    @guarded
    def python_analyze(code: str) -> str:
        """何时使用：仅当白名单方法无法完成必要分析、且计划中 use_python=true 时使用；
        用于白名单结果之外的交叉分组、补充统计，不替代工作项声明的白名单方法
        （每个 workstream 的声明方法仍是提交报告的完成条件）。

        参数 code：一段 pandas 代码字符串（≤10,000 字符）。pandas 已作为 pd 预载（禁止 import！）。
        数据框：frames.metrics / frames.claims / frames.evidence / frames.post_scope，
        meta（dict：数据版本等）。最后把关键结论赋给变量 result（DataFrame 或标量）。
        示例：result = frames.metrics.sort_values('negative_share', ascending=False).head(5)

        边界：不允许 import 与任何 I/O（读写文件、网络）；只读语义层数据；
        计划未设 use_python=true 时返回 python_not_authorized_by_plan；
        同一段失败代码最多重试 2 次，之后必须换方法。
        返回：{"ok":true,"result":...} 或 {"ok":false,"error":...}；仅 ok=true 的结果可进入报告。"""
        if (context.get("plan") is not None and not context["plan"].get("use_python")) \
                or (context.get("plan") is None and not context.get("interactive")):
            record_tool_error(context)
            return json.dumps({"error": "python_not_authorized_by_plan",
                               "message": "当前分析流程未授权代码分析。"}, ensure_ascii=False)
        progress = context.get("progress")
        if progress:
            progress("沙箱执行中")
        if len(code) > 10_000:
            record_tool_error(context)
            return json.dumps({"error": "analysis_code_too_large",
                               "message": "单次分析代码不能超过 10,000 个字符。"}, ensure_ascii=False)
        # loop guard: same failing code retried beyond budget is refused
        failures = context.setdefault("code_failures", {})
        code_hash = hashlib.sha256(code.encode()).hexdigest()[:12]
        outcome = sandbox.run_code(code)
        if not outcome.get("ok"):
            record_tool_error(context)
            failures[code_hash] = failures.get(code_hash, 0) + 1
            payload = {**outcome, **_budget_snapshot(context)}
            hint = _sandbox_error_hint(outcome)
            if hint:
                payload["hint"] = hint
            if failures[code_hash] >= MAX_CODE_FAILURES:
                return json.dumps({"error": "同一段代码已连续失败 3 次，重试预算用尽。",
                                   "hint": "换一种分析方法，或基于已有结果提交报告，"
                                           "并如实说明未能验证的部分。",
                                   **_budget_snapshot(context)},
                                  ensure_ascii=False)
            return json.dumps(payload, ensure_ascii=False, default=str)
        _record_step("python", _validate_chart(dict(outcome)), code_hash=code_hash, code=code)
        outcome = _validate_chart(outcome)
        if _is_empty_result(outcome.get("result")):
            outcome = {**outcome, "empty_result": True,
                       "hint": _empty_result_hint()}
        return json.dumps({**outcome, **_budget_snapshot(context)},
                          ensure_ascii=False, default=str)

    @tool
    @guarded
    def get_negative_evidence(aspect: str, limit: int = 8) -> str:
        """何时使用：报告需要引用负向观点原文时。

        参数：aspect 必须与计划中 requires_evidence=true 的工作项议题完全一致，如 aspect="空间与舒适性"；
        limit 可选（默认 8，最大 20）。
        边界：只覆盖 core/potential 精选子集，不代表全部用户声音；计划未授权该议题时返回
        evidence_not_in_plan，不会返回其他议题的证据。
        返回：JSON 数组，每条含 claim_id、quote、title、url、date 等字段；报告引用时必须附 claim_id。"""
        if context.get("plan") is None and not context.get("interactive"):
            record_tool_error(context)
            return json.dumps({"error": "evidence_not_in_plan"}, ensure_ascii=False)
        if context.get("plan") is not None and not any(
                _evidence_authorised(s, aspect)
                for s in context["plan"]["workstreams"]):
            record_tool_error(context)
            return json.dumps({"error": "evidence_not_in_plan"}, ensure_ascii=False)
        records = service.query_claims(aspect=aspect, sentiment="负面", limit=min(max(limit, 1), 20))
        _record_step("evidence", records, aspect=aspect)
        return json.dumps(records, ensure_ascii=False, default=str)

    @tool
    @guarded
    def submit_report(title: str, markdown: str, key_findings: str = "") -> str:
        """何时使用：计划中每个 workstream 都已执行（requires_evidence=true 的还取到了带
        claim_id 的证据）之后，提交最终报告。

        参数：
        - title：报告标题字符串；
        - markdown：完整 Markdown 正文（含口径说明与依据）；正文必须写出任务简报给出的
          当前数据版本（页脚写「数据版本：<版本号>」），且不得出现「语义层」「workstream」
          等内部实现词——两项均为发布门禁的硬检查，缺失即拒；
        - key_findings：关键结论的 JSON 数组（至多 5 条；下限为
          min(3, 工作项数)，单子问题分析可为 1 条），
          例如 key_findings='["可靠性与故障负向占比最高（0.42）","..."]'。

        边界：任一 workstream 未执行或缺证据时返回 analysis_plan_incomplete（附未完成项 id），
        此时不要提交，先补执行；每次提交都会经过发布门禁，未通过返回 report_gate_failed
        及修订要求；提交最多 3 次，超限返回 submit_attempt_limit。
        返回：成功为 {"accepted":true,"report_id":...}；被拒为 {"error":...,"gate":...}。"""
        progress = context.get("progress")
        if progress:
            progress("撰写报告中")
        context["submit_attempts"] = context.get("submit_attempts", 0) + 1
        plan = context.get("plan")
        if plan is None:
            return json.dumps({"error": "analysis_plan_required"}, ensure_ascii=False)
        incomplete = []
        for stream in plan["workstreams"]:
            # 与执行期校验同一条判据：方法 + 参数完全一致才算"这一项跑过了"。
            matching = [step for step in context.get("verified_steps", [])
                        if step.get("kind") == "method"
                        and step.get("method") == stream["method"]
                        and step.get("params") == stream.get("params")]
            has_required_evidence = any(
                step.get("claim_ids") and _evidence_authorised(stream, step.get("aspect"))
                for step in context.get("verified_steps", [])
                if step.get("kind") in {"method", "evidence"})
            if not matching or (stream["requires_evidence"] and not has_required_evidence):
                incomplete.append(stream["id"])
        if incomplete:
            return json.dumps({"error": "analysis_plan_incomplete",
                               "workstreams": incomplete,
                               "message": "完成草案中每项分析及要求的证据后再提交。"},
                              ensure_ascii=False)
        if context.get("accepted_submission"):
            return json.dumps({"error": "report_already_submitted",
                               "message": "本次运行已成功提交报告。"}, ensure_ascii=False)
        if context["submit_attempts"] > MAX_SUBMIT_ATTEMPTS:
            return json.dumps({"error": "submit_attempt_limit",
                               "message": "报告门禁修订次数已用尽。"}, ensure_ascii=False)
        try:
            findings = json.loads(key_findings)
        except (TypeError, json.JSONDecodeError):
            return json.dumps({"error": "invalid_key_findings",
                               "message": "key_findings 必须是 JSON 数组。"}, ensure_ascii=False)
        provenance = context.get("verified_steps", [])
        data_version = service.snapshot_version()
        gate = report_gate.validate_submission(
            title=title, markdown=markdown, key_findings=findings,
            plan=context.get("plan"),
            data_version=data_version,
            evidence_claim_ids=context.get("evidence_claim_ids", set()),
            verified_steps=provenance,
            live_evidence=None,
            time_window=None)
        if not gate["ok"]:
            context["gate_rejections"] = context.get("gate_rejections", 0) + 1
            return json.dumps({"error": "report_gate_failed", "gate": gate,
                               "attempt": context["submit_attempts"],
                               "attempts_left": MAX_SUBMIT_ATTEMPTS - context["submit_attempts"]},
                              ensure_ascii=False)
        snapshot_hash = service.snapshot_hash()
        report_id = hashlib.sha256(f"{title}:{markdown}:{snapshot_hash}".encode()).hexdigest()[:12]
        meta = {"report_id": report_id, "title": title,
                "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "data_version": service.snapshot_version(),
                "snapshot_hash": snapshot_hash,
                "key_findings": findings, "status": "pending_review",
                "gate": gate, "verified_steps": len(provenance),
                "analysis_plan": plan,
                "evidence_claim_ids": sorted(context.get("evidence_claim_ids", set()))}
        out_dir = report_publisher.save_submission(
            report_id, markdown, provenance, meta,
            context.get("evidence_claim_ids", set()))
        context["submissions"].append({**meta, "report_md": markdown, "dir": str(out_dir)})
        context["accepted_submission"] = True
        return json.dumps({"report_id": report_id, "status": "pending_review",
                           "saved": str(out_dir),
                           "next_step": "由非作者队友复核并通过 report_publisher.py 发布。"},
                          ensure_ascii=False)

    @tool
    @guarded
    def search_published_report(query: str, limit: int = 5) -> str:
        """按用户问题检索已发布报告的相关章节；返回章节编号、标题和原文片段供回答引用。"""
        sections = report_source.load_sections()
        if not sections:
            return json.dumps({"sections": [], "message": "当前没有可检索的已发布报告。"},
                              ensure_ascii=False)
        text = str(query or "").strip().lower()
        if not text or len(text) > 300:
            return json.dumps({"error": "invalid_report_query"}, ensure_ascii=False)
        stop = {"报告", "里面", "其中", "关于", "如何", "哪些", "什么", "建议", "结论", "用户", "这个", "那个", "一下"}
        terms: set[str] = set()
        for chunk in re.findall(r"[\u4e00-\u9fff]{2,}|[a-z0-9]+", text):
            if re.fullmatch(r"[\u4e00-\u9fff]+", chunk):
                terms.update(chunk[i:i + 2] for i in range(len(chunk) - 1))
                if len(chunk) <= 4:
                    terms.add(chunk)
            else:
                terms.add(chunk)
        terms = {term for term in terms if term not in stop and len(term) >= 2}
        ranked = []
        for section in sections:
            haystack = f"{section['title']}\n{section['text']}".lower()
            hits = [term for term in terms if term in haystack]
            if hits:
                ranked.append((len(hits), section, hits))
        ranked.sort(key=lambda item: (-item[0], item[1]["id"]))
        matches = [{"id": section["id"], "title": section["title"],
                    "text": section["text"][:5000], "matched_terms": hits,
                    "snippet": _hit_snippet(section["text"], hits)}
                   for _, section, hits in ranked[:max(1, min(int(limit), 8))]]
        seen = {hit.get("id") for hit in context.get("report_hits", [])}
        for item in matches:
            if item["id"] in seen:
                continue
            seen.add(item["id"])
            context["report_hits"].append(
                {"id": item["id"], "title": item["title"],
                 "snippet": item["snippet"], "matched_terms": item["matched_terms"]})
        return json.dumps({"sections": matches, "match_count": len(ranked)}, ensure_ascii=False)

    @tool
    @guarded
    def search_claims(query: str, aspect: str = "", sentiment: str = "", limit: int = 10) -> str:
        """何时使用：需要按结论/子问题的关键词召回相关观点时——不限于负面，可召回正面/中性做对照；
        与 get_negative_evidence（议题负面原文列表）互补：它按议题取列表，本工具按相关度排序。
        参数：query 必填（结论关键词，2-200 字）；aspect 必须是已批准计划中出现的议题（召回不得绕过大纲）；
        sentiment 可选过滤（正面/负面/中性/混合）；limit 默认 10，最大 20。
        边界：召回池为精选观点（core/potential，均已通过引文回挂校验），不代表全部用户声音；
        结果附 score 与 tier，引用时仍必须附 claim_id 并逐字引用 quote。
        返回：{"claims":[{claim_id, aspect, sentiment, tier, score, quote, ...}]}；无命中返回空数组与警告。"""
        plan = context.get("plan")
        normalized_aspect = aspect or None
        if plan is not None:
            allowed = {_planned_aspect(stream)
                       for stream in plan["workstreams"]} - {None}
            if normalized_aspect not in allowed:
                record_tool_error(context)
                return json.dumps({"error": "search_claims_aspect_not_in_plan",
                                   "allowed_aspects": sorted(a for a in allowed if a),
                                   "message": "aspect 必须是已批准计划中出现的议题。"},
                                  ensure_ascii=False)
        try:
            out = service.search_claims(query=query, aspect=normalized_aspect,
                                        sentiment=sentiment or None,
                                        limit=min(max(int(limit), 1), 20))
        except (ValueError, TypeError) as exc:
            record_tool_error(context)
            return json.dumps({"error": f"invalid_search_claims_params: {exc}"},
                              ensure_ascii=False)
        records = out.get("claims", [])
        _record_step("evidence", records,
                     aspect=normalized_aspect, recall_query=out.get("query"))
        return json.dumps(out, ensure_ascii=False, default=str)

    result_tools = [semantic_overview, submit_analysis_plan, run_semantic_aggregate,
                    python_analyze, get_negative_evidence, search_claims,
                    search_published_report, submit_report]
    return result_tools
