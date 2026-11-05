"""Persist deep-agent reports and publish only after a recorded human review.

Review and publication are deliberately offline CLI operations. The public API
can read published reports but cannot approve or publish them.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import report_gate
from research import service

HERE = Path(__file__).resolve().parent
REPORTS_DIR = HERE / "reports" / "agent"
LATEST_FILE = REPORTS_DIR / "published-latest.json"
REPORT_ID_RE = re.compile(r"^[0-9a-f]{12}$")
LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://[^\s)]+)\)")


def _inline_markdown(text: str) -> str:
    parts: list[str] = []
    cursor = 0
    for match in LINK_RE.finditer(text):
        parts.append(escape(text[cursor:match.start()]))
        label, url = match.groups()
        if urlparse(url).scheme in {"http", "https"}:
            parts.append(f'<a href="{escape(url, quote=True)}" rel="noopener noreferrer">'
                         f"{escape(label)}</a>")
        else:
            parts.append(escape(match.group(0)))
        cursor = match.end()
    parts.append(escape(text[cursor:]))
    return "".join(parts).replace("**", "")


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=".tmp-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def _json_write(path: Path, value: dict[str, Any]) -> None:
    _atomic_write(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def _report_dir(report_id: str) -> Path:
    if not REPORT_ID_RE.fullmatch(report_id):
        raise ValueError("invalid report id")
    return REPORTS_DIR / report_id


def _evidence_appendix(evidence_claim_ids: set[str]) -> tuple[str, list[dict[str, Any]], str]:
    """auto-033 1.2：依据实际引用的证据标识生成证据附录（人读 md + 机器读 json）。

    确定性生成，独立于 report.md（不参与 gate 数字溯源，也不污染报告问答
    语料）；查询失败不阻塞提交本体，人读附录只给简明提示，完整异常随
    evidence.json 留痕。
    """
    try:
        out = service.evidence_details(sorted(evidence_claim_ids))
        details, error = out["details"], ""
    except Exception as exc:  # 附录生成失败不影响提交，但必须留痕
        details, error = [], f"{type(exc).__name__}: {exc}"
    lines = ["# 证据附录", "",
             "> 本附录依据正文引用的 claim_id 自动生成，与冻结数据一致；"
             "引文为截断索引，全文见原帖。", ""]
    if error:
        lines += ["附录生成失败，请查 provenance.json 或联系维护者。", ""]
    elif not details:
        lines += ["（本报告未引用观点证据）", ""]
    for item in details:
        if not item.get("found"):
            lines.append(f"- `{item['claim_id']}`：未在精选观点池中找到，"
                         "请查 provenance.json 或联系报告作者核实")
            continue
        lines.append(f"- `{item['claim_id']}`（{item.get('aspect') or '—'}｜"
                     f"{item.get('sentiment') or '—'}｜{item.get('ownership') or '—'}｜"
                     f"{item.get('experience') or '—'}｜集合 {item.get('source_set') or '—'}）")
        lines.append(f"  原帖：{item.get('url') or '—'} · {item.get('date') or '—'}")
        title = str(item.get("title") or "").strip()
        if title:
            lines.append(f"  标题：{title[:60]}{'…' if len(title) > 60 else ''}")
        quote = str(item.get("quote") or "").strip().replace("\n", " ")
        if quote:
            lines.append(f"  引文：{quote}")
    lines.append("")
    return "\n".join(lines), details, error


def save_submission(report_id: str, markdown: str, verified_steps: list[dict[str, Any]],
                    metadata: dict[str, Any], evidence_claim_ids: set[str],
                    *, live_evidence: dict[str, Any] | None = None) -> Path:
    directory = _report_dir(report_id)
    if directory.exists():
        existing = json.loads((directory / "meta.json").read_text(encoding="utf-8"))
        if existing.get("status") != "pending_review":
            raise ValueError("report id already exists outside pending-review state")
    _atomic_write(directory / "report.md", markdown)
    _json_write(directory / "provenance.json", {"verified_steps": verified_steps,
                                                "evidence_claim_ids": sorted(evidence_claim_ids),
                                                **({"live_evidence": live_evidence} if live_evidence is not None else {})})
    _json_write(directory / "meta.json", {**metadata, "report_id": report_id,
                                           "status": "pending_review",
                                           "created_by": "deep-analysis-agent"})
    if live_evidence is None:
        appendix_md, appendix_json, appendix_error = _evidence_appendix(evidence_claim_ids)
    else:
        appendix_json = [live_evidence[item] for item in sorted(evidence_claim_ids) if item in live_evidence]
        appendix_error = "" if len(appendix_json) == len(evidence_claim_ids) else "实时证据缺失"
        lines = ["# 证据附录", "", "匹配仅表示引文与对应输入块一致；图片描述不等同于帖子原文。", ""]
        for item in appendix_json:
            lines.append(f"- `{item['claim_id']}` {item.get('title') or ''} {item.get('url') or ''}")
            for quote in item.get("evidence", []):
                lines.append(f"  - 来源 {quote.get('source_type')}: {quote.get('quote') or ''}")
        appendix_md = "\n".join(lines) + "\n"
    _atomic_write(directory / "evidence.md", appendix_md)
    _json_write(directory / "evidence.json",
                {"evidence": appendix_json, "error": appendix_error,
                 "data_version": metadata.get("data_version", "")})
    return directory


def publish_after_outline(report_id: str, *, outline_approved: bool) -> dict[str, Any]:
    """Publish a live report after an actual outline decision and a gate recheck."""
    if not outline_approved:
        raise ValueError("outline approval required")
    directory, meta, provenance, markdown = _load(report_id)
    if meta.get("status") != "pending_review" or meta.get("source_mode") != "live_transaction":
        raise ValueError("not a pending live report")
    decision = meta.get("outline_decision") or {}
    if not decision.get("decided_at") or not decision.get("types") or any(
            item not in {"approve", "edit"} for item in decision["types"]):
        raise ValueError("outline decision record required")
    ids = set(provenance.get("evidence_claim_ids", []))
    if ids != set((provenance.get("live_evidence") or {}).keys()):
        raise ValueError("live evidence registry is incomplete")
    gate = report_gate.validate_submission(
        title=meta.get("title", ""), markdown=markdown, key_findings=meta.get("key_findings"),
        plan=meta.get("analysis_plan"), data_version=meta.get("data_version", ""),
        evidence_claim_ids=ids, verified_steps=provenance.get("verified_steps", []),
        live_evidence=provenance.get("live_evidence") or {},
        time_window=meta.get("time_window"))
    if not gate["ok"]:
        raise ValueError("publication gate failed: " + "; ".join(gate["errors"]))
    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    meta.update({"status": "published", "published_at": timestamp,
                 "publication_basis": "human_outline_approval_and_automated_gate"})
    _json_write(directory / "meta.json", meta)
    _json_write(LATEST_FILE, {"report_id": report_id, "published_at": timestamp,
                              "data_version": meta["data_version"]})
    return meta


def _load(report_id: str) -> tuple[Path, dict[str, Any], dict[str, Any], str]:
    directory = _report_dir(report_id)
    meta = json.loads((directory / "meta.json").read_text(encoding="utf-8"))
    provenance = json.loads((directory / "provenance.json").read_text(encoding="utf-8"))
    markdown = (directory / "report.md").read_text(encoding="utf-8")
    return directory, meta, provenance, markdown


REVIEW_CHECKLIST_DIMENSIONS = ("可读性", "逻辑性", "全面性", "深度", "可解释性")


def _validate_checklist(checklist: Any) -> dict[str, str]:
    """auto-033 2.1：五维人审结论形状校验；由人填写，系统只验形状不生成。"""
    if checklist is None:
        return {}
    dimensions_hint = "/".join(REVIEW_CHECKLIST_DIMENSIONS)
    if not isinstance(checklist, dict):
        raise ValueError(f"--checklist 须为 JSON 对象，键只能是：{dimensions_hint}，"
                         "值为非空文字结论")
    unknown = [key for key in checklist if key not in REVIEW_CHECKLIST_DIMENSIONS]
    if unknown:
        raise ValueError("--checklist 含非法键：" + ", ".join(map(str, unknown))
                         + f"；键只能是：{dimensions_hint}")
    invalid = [key for key, value in checklist.items()
               if not isinstance(value, str) or not value.strip()]
    if invalid:
        raise ValueError("--checklist 各维结论须为非空文字：" + ", ".join(map(str, invalid)))
    return {key: value.strip() for key, value in checklist.items()}


def review_and_publish(report_id: str, *, reviewer: str, reviewed_commit: str,
                       verdict: str, note: str = "",
                       checklist: dict[str, str] | None = None) -> dict[str, Any]:
    """Record a human verdict; an approval publishes only after gate recheck.

    ``checklist``（可选，auto-033 2.1）：五维结构化人审结论，由审核人填写，
    形状校验通过后与 verdict 一并入档；不提供时行为与既有流程一致。
    """
    reviewer = reviewer.strip()
    reviewed_commit = reviewed_commit.strip()
    if not reviewer or not re.fullmatch(r"[0-9a-fA-F]{7,40}", reviewed_commit):
        raise ValueError("reviewer and a 7–40 character commit SHA are required")
    if verdict not in {"approved", "rejected"}:
        raise ValueError("verdict must be approved or rejected")
    checked = _validate_checklist(checklist)
    directory, meta, provenance, markdown = _load(report_id)
    if meta.get("status") != "pending_review":
        raise ValueError(f"report is not pending review (status={meta.get('status')})")
    if verdict == "approved":
        if meta.get("data_version") != service.snapshot_version():
            raise ValueError("report data version no longer matches the active snapshot")
        if meta.get("snapshot_hash") != service.snapshot_hash():
            raise ValueError("report snapshot hash no longer matches the active snapshot")
        gate = report_gate.validate_submission(
            title=meta.get("title", ""), markdown=markdown,
            key_findings=meta.get("key_findings"),
            data_version=service.snapshot_version(),
            evidence_claim_ids=set(provenance.get("evidence_claim_ids", [])),
            verified_steps=provenance.get("verified_steps", []))
        if not gate["ok"]:
            raise ValueError("publication gate failed: " + "; ".join(gate["errors"]))
    review = {"reviewer": reviewer, "reviewed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "reviewed_commit": reviewed_commit, "verdict": verdict, "note": note.strip()}
    if checked:
        review["checklist"] = checked
    meta["review"] = review
    meta["status"] = "published" if verdict == "approved" else "rejected"
    _json_write(directory / "meta.json", meta)
    if verdict == "approved":
        _json_write(LATEST_FILE, {"report_id": report_id, "published_at": review["reviewed_at"],
                                  "data_version": meta["data_version"]})
    return meta


def latest_published() -> dict[str, Any] | None:
    if not LATEST_FILE.is_file():
        return None
    pointer = json.loads(LATEST_FILE.read_text(encoding="utf-8"))
    try:
        directory, meta, _provenance, markdown = _load(pointer["report_id"])
    except (OSError, ValueError, KeyError, json.JSONDecodeError):
        return None
    if meta.get("source_mode") == "live_transaction":
        return {"meta": meta, "markdown": markdown, "provenance": _provenance} if meta.get("status") == "published" else None
    if (meta.get("status") != "published"
            or meta.get("data_version") != service.snapshot_version()
            or meta.get("snapshot_hash") != service.snapshot_hash()):
        return None
    return {"meta": meta, "markdown": markdown, "provenance": _provenance}


def published_report(report_id: str) -> dict[str, Any] | None:
    """Return a report only when its recorded review has published it."""
    try:
        _directory, meta, _provenance, markdown = _load(report_id)
    except (OSError, ValueError, KeyError, json.JSONDecodeError):
        return None
    if meta.get("source_mode") == "live_transaction":
        return {"meta": meta, "markdown": markdown} if meta.get("status") == "published" else None
    if (meta.get("status") != "published"
            or meta.get("data_version") != service.snapshot_version()
            or meta.get("snapshot_hash") != service.snapshot_hash()):
        return None
    return {"meta": meta, "markdown": markdown}


def _insert_charts(body: list[str], meta: dict[str, Any], provenance: dict[str, Any]) -> None:
    """auto-034：把已验证数据渲染的 SVG 锚进对应章节；找不到锚点则入文末图表附录。"""
    import report_charts
    orphans: list[str] = []
    for chart in report_charts.charts_for(meta, provenance):
        anchor = str(chart.get("anchor") or "")[:16]
        figure = (f'<figure class="report-chart">{chart["svg"]}'
                  f"<figcaption>数据来源：已验证分析步骤（与正文数字同源）</figcaption></figure>")
        hit = next((i for i, element in enumerate(body)
                    if anchor and anchor in element), None)
        if hit is None:
            orphans.append(figure)
        else:
            body.insert(hit + 1, figure)
    if orphans:
        body.append("<h2>图表</h2>")
        body.extend(orphans)


_CITE_RE = re.compile(r"[（(]\s*claim_id[:：]\s*([0-9a-fA-F]{16,32})\s*[）)]")


def _decorate_citations(body: list[str], provenance: dict[str, Any]) -> None:
    """auto-034 2.14：发布视图与前端同构——正文 claim_id 折叠为 [n] 角标，
    文末附可展开证据清单（含原帖链接）。report.md 原文不变，仅呈现层转换。"""
    index: dict[str, dict[str, Any]] = {}
    try:
        ids = (provenance or {}).get("evidence_claim_ids") or []
        if ids and (provenance or {}).get("live_evidence") is not None:
            index = (provenance or {}).get("live_evidence") or {}
        elif ids:
            details = service.evidence_details(sorted(ids))["details"]
            index = {d["claim_id"]: d for d in details if d.get("found")}
    except Exception:
        index = {}
    used: list[str] = []

    def _sub(m: re.Match[str]) -> str:
        claim_id = m.group(1).lower()
        if claim_id not in used:
            used.append(claim_id)
        return f'<sup class="cite-ref">[{used.index(claim_id) + 1}]</sup>'

    body[:] = [_CITE_RE.sub(_sub, element) for element in body]
    if not used:
        return
    items = []
    for i, claim_id in enumerate(used, 1):
        meta = index.get(claim_id) or {}
        desc = " · ".join(str(meta[k]) for k in ("title", "date") if meta.get(k))
        link = (f' · <a href="{escape(meta["url"])}" target="_blank" rel="noopener">原帖</a>'
                if meta.get("url") else "")
        items.append(f'<li value="{i}"><code>{escape(claim_id)}</code>'
                     f"{(' — ' + escape(desc)) if desc else ''}{link}</li>")
    body.append('<details class="evidence-footnotes">'
                f"<summary>证据引用编号（{len(used)} 条，展开查看原帖）</summary>"
                f"<ol>{''.join(items)}</ol></details>")


def render_published_html() -> str | None:
    """Render the latest approved report as a small, escaped HTML document."""
    published = latest_published()
    if not published:
        return None
    meta = published["meta"]
    body: list[str] = []
    in_list = False
    for raw_line in published["markdown"].splitlines():
        line = raw_line.strip()
        if not line:
            if in_list:
                body.append("</ul>")
                in_list = False
            continue
        if line.startswith("|"):
            if in_list:
                body.append("</ul>")
                in_list = False
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            if all(re.fullmatch(r":?-{3,}:?", cell.replace(" ", "")) for cell in cells):
                continue
            body.append("<div class=\"table-wrap\"><table><tr>" +
                        "".join(f"<td>{_inline_markdown(cell)}</td>" for cell in cells) +
                        "</tr></table></div>")
            continue
        if line.startswith("#"):
            if in_list:
                body.append("</ul>")
                in_list = False
            level = min(len(line) - len(line.lstrip("#")), 3)
            body.append(f"<h{level}>{_inline_markdown(line[level:].strip())}</h{level}>")
            continue
        if re.match(r"^[-*]\s+", line):
            if not in_list:
                body.append("<ul>")
                in_list = True
            body.append("<li>" + _inline_markdown(re.sub(r"^[-*]\s+", "", line)) + "</li>")
            continue
        if in_list:
            body.append("</ul>")
            in_list = False
        body.append("<p>" + _inline_markdown(line) + "</p>")
    if in_list:
        body.append("</ul>")
    _insert_charts(body, meta, published.get("provenance") or {})
    _decorate_citations(body, published.get("provenance") or {})
    review = meta.get("review") or {}
    title = escape(str(meta.get("title", "AutoInsight 深度分析报告")))
    reviewer = escape(str(review.get("reviewer", "")))
    reviewed_at = escape(str(review.get("reviewed_at", "")))
    version = escape(str(meta.get("data_version", "unknown")))
    publication = ("大纲经人工确认，报告通过自动门禁发布" if meta.get("source_mode") == "live_transaction"
                   else f"已审核发布 · 审核人 {reviewer} · {reviewed_at}")
    return ("<!doctype html><html lang=\"zh-CN\"><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
            f"<title>{title}</title><style>body{{font:16px/1.7 system-ui,sans-serif;"
            "max-width:900px;margin:2rem auto;padding:0 1rem;color:#17191c;background:#ffffff}"
            "h1,h2,h3{line-height:1.3;color:#12233d}"
            "table{border-collapse:collapse}td{border:1px solid #e6e6e2;"
            "padding:.4rem .7rem}.table-wrap{overflow-x:auto}"
            "figure.report-chart{margin:1.2rem 0}figure.report-chart svg{max-width:100%;"
            "height:auto}figcaption{color:#71767c;font-size:12px;margin-top:.3rem}"
            "header p{color:#71767c;font-size:12px}</style><body>"
            f"<header><h1>{title}</h1><p>{publication} · 数据来源 {version}</p></header><main>{''.join(body)}</main>"
            "</body></html>")


def main() -> int:
    parser = argparse.ArgumentParser(description="审核并发布深度 Agent 报告")
    parser.add_argument("report_id", help="待审报告 ID")
    parser.add_argument("--reviewer", required=True, help="非作者审核人姓名或团队标识")
    parser.add_argument("--reviewed-commit", required=True, help="审核所依据的代码提交 SHA")
    parser.add_argument("--verdict", required=True, choices=("approved", "rejected"))
    parser.add_argument("--note", default="", help="审核意见")
    parser.add_argument("--checklist", default="",
                        help="五维结构化评审结论 JSON（键：可读性/逻辑性/全面性/深度/可解释性）")
    args = parser.parse_args()
    checklist = None
    if args.checklist.strip():
        try:
            checklist = json.loads(args.checklist)
        except json.JSONDecodeError as exc:
            parser.error(f"--checklist 不是合法 JSON：{exc}")
    result = review_and_publish(args.report_id, reviewer=args.reviewer,
                                reviewed_commit=args.reviewed_commit,
                                verdict=args.verdict, note=args.note,
                                checklist=checklist)
    print(json.dumps({"report_id": args.report_id, "status": result["status"],
                      "review": result["review"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
