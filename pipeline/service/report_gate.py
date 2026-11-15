"""Deterministic pre-review checks for deep-agent reports."""
from __future__ import annotations

import re
import json
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any

import config

CLAIM_ID_RE = re.compile(r"(?<![0-9a-f])[0-9a-f]{20}(?![0-9a-f])", re.IGNORECASE)
CLAIM_CITATION_RE = re.compile(r"claim_id[:：]\s*[0-9a-f]{20}", re.IGNORECASE)
NUMBER_RE = re.compile(r"(?<![0-9A-Za-z_])[+-]?\d+(?:,\d{3})*(?:\.\d+)?%?(?![0-9A-Za-z_])")
# D12 报告分层（Owner 2026-10-28 修订）：核心三段必填；对比矩阵/归因分析按计划
# 类型给出建议（warning），不再阻断提交——章节是否必要由问题本身决定。
CORE_SECTIONS = ("结论摘要", "证据与归组", "限制与不确定性")
COMPARE_SECTIONS = ("对比矩阵",)
TREND_SECTIONS = ("归因分析",)
# 内部词禁词（D12 风格层）：用户可见文本不得出现内部实现词；
# claim_id 引用格式（claim_id: <20hex>）除外。
INTERNAL_TERMS = ("workstream", "语义层", "semantic_", "frames.", "verified_steps",
                  "白名单方法", "run_analysis_method", "python_analyze", "submit_report")
# D7 P1-3：限制章节"无数据"类同义表述——任一出现即视为空结果已解释。
EMPTY_RESULT_MARKERS = ("空", "无数据", "未返回", "不支持", "未覆盖")


def _required_sections(plan: dict[str, Any] | None) -> tuple[str, ...]:
    """Core sections only; type-injected sections are advisory (see _advisory_sections)."""
    return CORE_SECTIONS


def _advisory_sections(plan: dict[str, Any] | None) -> tuple[str, ...]:
    """对比型→对比矩阵, 趋势型→归因分析：按计划类型提示，不阻断提交。"""
    sections: list[str] = []
    workstreams = (plan or {}).get("workstreams") or []
    methods = {str(w.get("method") or "") for w in workstreams}
    dimensions = {str(w.get("dimension") or "") for w in workstreams}
    for w in workstreams:  # auto-032：原语工作项的维度在 params.group_by 中
        params = w.get("params") or {}
        dimensions.update(str(g) for g in (params.get("group_by") or []) if isinstance(g, str))
    if methods & {"co_mention_products"} or "product" in dimensions:
        sections += list(COMPARE_SECTIONS)
    if methods & {"negative_claims_by_month"} or "time" in dimensions:
        sections += list(TREND_SECTIONS)
    return tuple(sections)


def _limitations_section(markdown: str) -> str:
    match = re.search(r"##\s*限制与不确定性(.*?)(?=\n##\s|\Z)", markdown or "", re.S)
    return match.group(1) if match else ""


def _banned_internal_terms(text: str) -> list[str]:
    cleaned = CLAIM_CITATION_RE.sub(" ", text)
    return [term for term in INTERNAL_TERMS if term in cleaned]


def validate_submission(*, title: str, markdown: str, key_findings: Any,
                        data_version: str, evidence_claim_ids: set[str],
                        verified_steps: list[dict[str, Any]],
                        plan: dict[str, Any] | None = None,
                        live_evidence: dict[str, Any] | None = None,
                        time_window: tuple[str, str] | list[str] | None = None) -> dict[str, Any]:
    """Check required report structure, evidence references, and executed steps.

    These checks establish provenance and completeness, not analytical quality;
    human review remains required before publication.
    """
    errors: list[str] = []
    warnings: list[str] = []
    if not isinstance(title, str) or not title.strip() or len(title) > 160:
        errors.append("标题为空或超过 160 个字符")
    if not isinstance(markdown, str) or not markdown.strip():
        errors.append("报告正文为空")
        markdown = ""
    elif len(markdown) > config.REPORT_MAX_CHARS:
        errors.append(f"报告正文超过 {config.REPORT_MAX_CHARS} 个字符（当前 {len(markdown)}）")
    if time_window is not None and (len(time_window) != 2 or
                                    not all(isinstance(item, str) and item in markdown for item in time_window)):
        errors.append("报告须明确写出本次时间范围的起止日期")
    for section in _required_sections(plan):
        # D7 P3-8：行首匹配（标题或行首出现），正文提及不再充当章节在场证据。
        # 允许章节标题带序号（「## 一、结论摘要」「### 2.1 结论摘要」）：
        # 序号是排版习惯，不该成为内容缺失的判定依据。
        if not re.search(rf"(?m)^\s*(?:#{{1,6}}\s*|\*\*)?\s*"
                         rf"(?:(?:[一二三四五六七八九十]+|\d+(?:\.\d+)*)\s*[、.．)）]\s*)?"
                         rf"{re.escape(section)}", markdown):
            errors.append(f"缺少章节：{section}")
    for section in _advisory_sections(plan):
        if section not in markdown:
            warnings.append(f"建议补充章节：{section}（按计划类型提示，不阻断提交）")
    # D7 P2-7：下限随工作项数收缩，单子问题分析不强迫凑数。
    n_streams = len((plan or {}).get("workstreams") or [])
    findings_lower = min(3, max(1, n_streams)) if n_streams else 3
    if not isinstance(key_findings, list) or not findings_lower <= len(key_findings) <= 5:
        errors.append(f"关键结论必须为 {findings_lower}–5 条的 JSON 数组")
    elif any(not isinstance(item, str) or not item.strip() for item in key_findings):
        errors.append("关键结论必须全部为非空字符串")
    if not data_version or data_version == "unknown":
        errors.append("当前数据版本未知")
    elif data_version.lower() not in markdown.lower():
        errors.append(f"正文必须明确写出当前数据版本（{data_version}），"
                      f"如在页脚写「数据版本：{data_version}」")
    # 品牌范围声明（D11，与数据版本检查同模式）：单主体阶段，报告口径必须
    # 显式声明分析主体（小米/SU7），说明其余品牌仅为帖子共现对比信息。
    if not _has_brand_scope_declaration(markdown):
        errors.append("正文缺少品牌范围声明：须包含「分析主体」或「品牌范围」字样"
                      f"并写明 {config.SUBJECT_BRAND}/{config.SUBJECT_SERIES}"
                      "（其余品牌仅为共现对比信息）")

    # D7 P2-4：快照 hash 等合法 hex 不是 claim 引用——token 前 30 字符含
    # hash/哈希/指纹 上下文时跳过。
    cited_ids = set()
    for match in CLAIM_ID_RE.finditer(markdown):
        lookback = markdown[max(0, match.start() - 30):match.start()].lower()
        if any(word in lookback for word in ("hash", "哈希", "指纹")):
            continue
        cited_ids.add(match.group(0).lower())
    unknown_ids = sorted(cited_ids - {str(item).lower() for item in evidence_claim_ids})
    if unknown_ids:
        errors.append("报告引用了本次工具未返回的 claim_id：" + ", ".join(unknown_ids))
    if live_evidence is not None:
        for match in re.finditer(r"「([^」]+)」\s*[（(]\s*claim_id[:：]\s*([0-9a-f]{20})", markdown, re.I):
            quote, claim_id = match.group(1), match.group(2).lower()
            record = live_evidence.get(claim_id) or {}
            if not any(item.get("matched") is True and item.get("quote") == quote
                       for item in record.get("evidence", [])):
                errors.append(f"报告引文与已匹配证据不一致：{claim_id}")
    if "claim_id" in markdown and not cited_ids:
        errors.append("报告提到 claim_id 但没有可核验的 20 位证据标识")
    # D7 P1-1：纯量化计划（无推导需证据工作项）不强制观点引用，降级提示。
    plan_needs_evidence = _plan_requires_evidence(plan)
    if not cited_ids:
        if plan_needs_evidence:
            errors.append("报告至少需要引用一条本次查询返回的观点证据")
        else:
            warnings.append("报告未引用观点证据（计划为纯量化分析）；如需引文佐证请补充取证")
    analysis_steps = [step for step in verified_steps
                      if step.get("kind") in {"method", "python"}]
    if not analysis_steps:
        errors.append("没有成功且可追溯的统计分析步骤")
    for index, step in enumerate(verified_steps, start=1):
        verdict = step.get("verification")
        if step.get("kind") == "method" and (not verdict or not verdict.get("ok")):
            errors.append(f"分析步骤 {index} 未通过确定性校验")
        if step.get("kind") == "python" and not (step.get("result") or {}).get("ok"):
            errors.append(f"代码步骤 {index} 未成功执行")
    # D12 空结果规则：执行过且为空的 workstream，须在限制章节解释后方可提交。
    for step in verified_steps:
        verdict = step.get("verification") or {}
        if step.get("kind") == "method" and verdict.get("empty_result"):
            aspect = str(step.get("aspect") or "")
            method = str(step.get("method") or "")
            limits = _limitations_section(markdown)
            # D7 P1-3：议题名或任一无数据表述即视为已解释；全表空结果（无议题名）
            # 以"限制章节非空且含方法名"判定——不存在任何表述都无法通过的路径。
            explained = bool(aspect) and aspect in limits
            if not explained:
                explained = any(marker in limits for marker in EMPTY_RESULT_MARKERS)
            if not explained and not aspect:
                explained = bool(limits.strip()) and method in limits
            if not explained:
                errors.append(f"议题「{aspect}」执行结果为空，须在限制与不确定性章节"
                              "说明后才能提交")
    banned = _banned_internal_terms(title + "\n" + markdown + "\n"
                                    + "\n".join(key_findings
                                                if isinstance(key_findings, list) else []))
    if banned:
        errors.append("报告包含内部实现词（不得出现在用户可见文本）：" + ", ".join(banned))
    # Provenance evidence includes both tool/code results and precomputed
    # baseline rows (kind=baseline carries "rows" instead of "result").
    # D7 P1-2：可比来源仅取结果数据（行/代码输出/图表/证据记录），
    # SQL 文本、耗时、行数与参数回显等元数字不计入。
    evidence_payload = []
    for step in verified_steps:
        kind = step.get("kind")
        result = step.get("result")
        if kind == "method" and isinstance(result, dict):
            evidence_payload.append({"rows": result.get("rows")})
        elif kind == "python" and isinstance(result, dict):
            evidence_payload.append({"result": result.get("result"),
                                     "chart": result.get("chart")})
        elif result is not None:
            evidence_payload.append(result)
        else:
            evidence_payload.append({"rows": step.get("rows")})
    evidence = json.dumps(evidence_payload, ensure_ascii=False, default=str) + " " + data_version
    report_text = CLAIM_ID_RE.sub(
        " ", title + "\n" + markdown + "\n" +
        "\n".join(key_findings if isinstance(key_findings, list) else []))
    # 版本令牌是有意写进正文的来源信息；先整段移除，避免日期清洗后残留
    # 「semantic-2026-11-03.4」里的 ".4" 被当成无来源数字。
    if data_version:
        report_text = report_text.replace(data_version, " ")
    # Source URLs can contain numeric path segments unrelated to report claims.
    report_text = re.sub(r"https?://\S+", " ", report_text)
    # Markdown 小节编号是结构不是统计数字：先去标题标记，再去行首多段编号
    # （「### 2.1 标题」「2.1.3 标题」→ 2.1/2.1.3 曾被溯源误判，E2E 2026-10-28）
    report_text = re.sub(r"(?m)^#{1,6}\s*", " ", report_text)
    report_text = re.sub(r"(?m)^\s*\d+(?:\.\d+)+[.)、]?\s+", " ", report_text)
    report_text = re.sub(r"(?m)^\s*\d+[.)、]\s+", " ", report_text)
    # 年份与日期不是统计数字（E2E 2026-10-28：2023/12/24 被误判为未溯源数字）
    report_text = re.sub(r"\d{4}-\d{2}(?:-\d{2})?", " ", report_text)
    report_text = re.sub(r"\b(?:19|20)\d{2}\s*年", " ", report_text)
    report_text = re.sub(r"(?<![0-9.])(?:19|20)\d{2}(?![0-9.%])", " ", report_text)
    # 叙述性日期与序数不是统计数字（D7 P1-2）：N月N日、第N位/名/次、近 N 月。
    report_text = re.sub(r"\d{1,2}\s*月(?:\s*\d{1,2}\s*[日号])?", " ", report_text)
    report_text = re.sub(r"第\s*\d+", " ", report_text)
    report_text = re.sub(r"近\s*\d{1,2}\s*月", " ", report_text)
    report_numbers = NUMBER_RE.findall(report_text)
    source_numbers = set(NUMBER_RE.findall(evidence))
    source_values = [value for value in (_as_float(item) for item in source_numbers)
                     if value is not None]
    numeric_errors: list[str] = []
    for token in report_numbers:
        if any(_matches_number(token, item) for item in source_numbers):
            continue
        # 差值/和/比值：两个已核验数字算出来的值同样可溯源。
        if _matches_derived(token, source_values):
            continue
        numeric_errors.append(token)
    if numeric_errors:
        errors.append("报告包含未在分析工具结果中找到的数字：" + ", ".join(numeric_errors[:20])
                      + "。修正：只引用已验证步骤结果中的数字（报告中的占比可按源数值"
                        "四舍五入到一位小数），或先补充相应分析步骤")
    return {"ok": not errors, "errors": errors, "warnings": warnings,
            "checks": ["required_sections", "data_version", "brand_scope_declaration",
                       "claim_ids", "verified_analysis_steps", "empty_result_explained",
                       "internal_terms", "key_findings", "numeric_provenance"]}


_DECLARATION_MARKERS = ("分析主体", "品牌范围")


def _plan_requires_evidence(plan: dict[str, Any] | None) -> bool:
    """计划是否需要引文证据。

    `requires_evidence` 是显式声明；`top_negative_claims` 是 auto-039 之前的
    旧方法名，仅为读取历史计划保留（新计划只会有 `semantic_aggregate`）。
    """
    for stream in (plan or {}).get("workstreams") or []:
        if not isinstance(stream, dict):
            continue
        if stream.get("requires_evidence") or stream.get("method") == "top_negative_claims":
            return True
    return False


def _has_brand_scope_declaration(markdown: str) -> bool:
    """Deterministic brand-scope declaration check (D11)."""
    subject_present = (config.SUBJECT_BRAND in markdown
                       or config.SUBJECT_SERIES in markdown)
    return subject_present and any(marker in markdown for marker in _DECLARATION_MARKERS)


def _as_float(token: str) -> float | None:
    try:
        return float(token.rstrip("%").replace(",", ""))
    except (TypeError, ValueError):
        return None


def _matches_derived(report_token: str, sources: list[float]) -> bool:
    """派生数字：两个已核验数字之差/和/比值同样可溯源。

    「低 2.4 个百分点」「约为 2.7 倍」这类比较是报告常态，只认单个源数值会逼
    模型绕开比较或用文字含糊带过（E2E 2026-11-03 曾两次因此被驳回）。操作数
    都可核验，派生值就可核验——但仍须落在展示舍入容差内，避免任意凑数。
    """
    if not sources:
        return False
    target = _as_float(report_token)
    if target is None or abs(target) < 1:
        # 0–1 尺度的比例值不做派生：报告不会写"占比差 0.037"，放行只会
        # 让舍入错误（0.24 vs 0.203125）蒙混过关。
        return False
    values: list[float] = []
    for value in sources[:300]:
        values.extend((value, value * 100.0, value / 100.0))
    # 容差随量级走：0–1 的比例值用 0.005（半个百分点），计数/百分点用 0.05。
    # 一律用 0.05 会让 0.24 被 0.203125+0.04 这类组合放行。
    tolerance = 0.005 if abs(target) < 1 else max(0.05, abs(target) * 0.001)
    for left in values:
        for right in values:
            if right == 0:
                continue
            if (abs(left - right - target) <= tolerance
                    or abs(left + right - target) <= tolerance
                    or abs(left / right - target) <= tolerance):
                return True
    return False


def _matches_number(report_token: str, source_token: str) -> bool:
    try:
        report_value = Decimal(report_token.rstrip("%").replace(",", ""))
        source_value = Decimal(source_token.rstrip("%").replace(",", ""))
    except InvalidOperation:
        return False
    if report_value == source_value:
        return True
    # 百分数按源数值换算并允许展示舍入（E2E 2026-10-28：20.3% vs 0.203125 需通过）
    tolerance = Decimal("0.0005")  # 0.05 个百分点
    if report_token.endswith("%"):
        return abs(report_value / Decimal(100) - source_value) <= tolerance
    if source_token.endswith("%"):
        return abs(source_value / Decimal(100) - report_value) <= tolerance
    # D7 P1-2：展示舍入——报告带小数点的数值须等于源数值按报告小数位数
    # 四舍五入后的结果；整数计数保持逐字一致。
    if "." in report_token:
        decimals = len(report_token.split(".")[1])
        rounded = source_value.quantize(Decimal(1).scaleb(-decimals), rounding=ROUND_HALF_UP)
        return report_value == rounded
    return False
