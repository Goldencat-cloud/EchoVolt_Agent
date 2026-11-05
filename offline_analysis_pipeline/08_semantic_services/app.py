"""AutoInsight MVP Web service.

Serves the static frontend plus read-only query APIs. Statistical numbers
and evidence always come from the deterministic tools in service.py; the
LLM (when configured) only organizes an explanation over those tool
results. Report Q&A answers over the latest team-approved published report.
`/api/question` sends every turn to one contextual agent, which chooses
whether to answer directly or use read-only research tools. Secrets are read
from the process environment only.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import os
import re
import sys
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from research import service
import config
import report_source
import report_publisher
import terminology

WEB = Path(__file__).with_name("web")
# auto-023 designed report (single-file HTML, charts embedded as base64).
LEGACY_REPORT = Path(__file__).resolve().parents[1] / "06_reporting" / "agent-kb" / "output" / "report.html"
# auto-030：/api/ask 的 report_ref.content 允许整份报告（60K 字符，中文 UTF-8 可达 ~180KB）
MAX_BODY = 512 * 1024
MAX_QUESTION = 500
SESSION_MAX_TURNS = 20
MAX_SESSIONS = 100
# E2E 实测（2026-10-28）：一次深度分析 = 1 启动 + 最多 2 澄清答复 + 1-2 审查动作，
# 10/60s 会被单个正常会话耗尽并殃及后续启动，提到 20/60s。
RATE_LIMIT_REQUESTS = 20
RATE_WINDOW_SECONDS = 60.0
SEVEN_SRC = Path(__file__).resolve().parents[1] / "07_qa_agent" / "src"

SESSIONS: dict[str, dict] = {}
_RATE: dict[str, list[float]] = {}
ANCHOR_IN_TEXT = re.compile(r"\[([A-Z][A-Z0-9]*)\]")


def _load_env(path: Path | None = None) -> None:
    """Shim kept for compatibility: configuration loading lives in config.py."""
    config.load_env(path)


_load_env()

def model_configured() -> bool:
    return config.model_configured()





def _rate_limited(ip: str) -> bool:
    now = time.monotonic()
    stamps = [t for t in _RATE.get(ip, []) if now - t < RATE_WINDOW_SECONDS]
    if len(stamps) >= RATE_LIMIT_REQUESTS:
        _RATE[ip] = stamps
        return True
    stamps.append(now)
    _RATE[ip] = stamps
    return False


# ---------------------------------------------------------------------------
# Core request handlers (framework-free so tests and the HTTP layer share them)
# ---------------------------------------------------------------------------
def agent_report_start(question: str, request_id: str,
                       brief: dict | None = None,
                       session_id: str | None = None) -> tuple[int, dict]:
    """Start a deep-analysis job; progress is polled via GET /api/agent/report/{id}."""
    import jobs
    import report_session
    if not config.model_configured():
        return 503, {"error": "model_unconfigured",
                     "message": "深度分析暂时不可用（未完成配置）。",
                     "request_id": request_id}
    jobs.cleanup()
    report_session._sweep()
    job_id = jobs.create_job(question, brief, session_id)
    if job_id is None:
        if session_id and jobs.pending_exists_for(session_id):
            return 409, {"error": "pending_review_exists",
                         "message": "您已有一个等待澄清或大纲审查的任务，请先完成后再发起新的深度分析。",
                         "request_id": request_id}
        return 429, {"error": "deep_analysis_busy",
                     "message": "当前深度分析任务已满，请稍后重试。",
                     "request_id": request_id}
    report_session.start_job(job_id, question, brief)
    return 202, {"job_id": job_id, "status": "running",
                 "status_url": f"/api/agent/report/{job_id}", "request_id": request_id}


def agent_report_clarify(job_id: str, data: dict, request_id: str) -> tuple[int, dict]:
    """Clarification answer (4.3/D10): only valid while 澄清中; re-assessment
    runs in background — the client polls the status endpoint for the outcome
    (new questions, or 数据探索中 when sufficiency is reached)."""
    import jobs
    import report_session
    job = jobs.get_job(job_id)
    if job is None:
        return 404, {"error": "job_not_found", "request_id": request_id}
    if job.get("status") != "clarifying":
        return 409, {"error": "clarify_not_awaiting",
                     "message": "当前没有等待答复的澄清问题。",
                     "status": job.get("status"), "request_id": request_id}
    answer = data.get("answer")
    if not isinstance(answer, str) or not answer.strip() or len(answer) > 2_000:
        return 400, {"error": "invalid_clarify_answer",
                     "message": "answer 须为 1..2000 字的答复文本。",
                     "request_id": request_id}
    field = data.get("field")
    entry = {"answer": answer.strip(),
             "field": field if isinstance(field, str) and field else "other",
             "asked": job.get("clarify_questions") or []}
    report_session.submit_clarification(job_id, entry)
    return 202, {"job_id": job_id, "status": "processing",
                 "status_url": f"/api/agent/report/{job_id}", "request_id": request_id}


def agent_report_outline(job_id: str, data: dict, request_id: str) -> tuple[int, dict]:
    """Outline review decision (4.4/D9): confirm | edit | regenerate.

    confirm→approve；edit 以提交的 plan_json 为准重过工具校验器；
    regenerate→reject（带反馈重出草案，上限 REGENERATE_LIMIT 次）。
    门禁未通过（非待审状态）时引擎不会恢复执行。
    """
    import jobs
    import report_session
    job = jobs.get_job(job_id)
    if job is None:
        return 404, {"error": "job_not_found", "request_id": request_id}
    if job.get("status") != "awaiting_review":
        return 409, {"error": "outline_not_awaiting_review",
                     "message": "当前没有等待审查的大纲。",
                     "status": job.get("status"), "request_id": request_id}
    action = data.get("action")
    if action == "confirm":
        decision: dict = {"type": "approve"}
    elif action == "edit":
        plan_json = data.get("plan_json")
        if not isinstance(plan_json, str) or not 2 <= len(plan_json) <= report_session.PLAN_MAX_CHARS:
            return 400, {"error": "invalid_outline",
                         "message": f"plan_json 须为 2..{report_session.PLAN_MAX_CHARS} 字符的 JSON 字符串。",
                         "request_id": request_id}
        # 单一权威：语法/结构判据只在 agent_tools 一处维护，端点不再自建。
        import agent_tools
        problems = agent_tools.plan_shape_problems(plan_json)
        if problems:
            return 400, {"error": "invalid_outline",
                         "message": "plan_json 未通过校验：" + "；".join(problems[:3]),
                         "request_id": request_id}
        decision = {"type": "edit",
                    "edited_action": {"name": "submit_analysis_plan",
                                      "args": {"plan_json": plan_json}}}
    elif action == "regenerate":
        if int(job.get("regenerates", 0)) >= report_session.REGENERATE_LIMIT:
            return 429, {"error": "regenerate_limit_reached",
                         "message": "重新生成次数已达上限，请编辑大纲或取消任务。",
                         "limit": report_session.REGENERATE_LIMIT,
                         "request_id": request_id}
        feedback = data.get("feedback")
        message = feedback if isinstance(feedback, str) and feedback.strip() \
            else "大纲未获认可，请重新起草分析计划。"
        decision = {"type": "reject", "message": message[:500]}
    else:
        return 400, {"error": "invalid_outline_action",
                     "message": "action 必须是 confirm / edit / regenerate。",
                     "request_id": request_id}
    # 8.10/D12：confirm/edit 可携带可选交付规格（重点/受众），注入执行上下文
    delivery_spec: dict | None = None
    focus, audience = data.get("focus"), data.get("audience")
    if isinstance(focus, str) and focus.strip() or isinstance(audience, str) and audience.strip():
        delivery_spec = {"focus": (focus or "").strip()[:200] or None,
                         "audience": (audience or "").strip()[:200] or None}
        jobs.record_delivery_spec(job_id, delivery_spec)
    # 原子占用：避免并发审查请求触发两次 resume
    if not jobs.claim_for_resume(job_id, "编写分析代码中"):
        return 409, {"error": "outline_not_awaiting_review",
                     "message": "大纲审查状态已变化，请刷新后重试。",
                     "request_id": request_id}
    # 计数在占用成功后自增，避免并发请求白增 regenerate 次数
    if action == "regenerate":
        jobs.record_regenerate(job_id)
    if not report_session.resume_job(job_id, decision, delivery_spec):
        return 500, {"error": "report_session_lost",
                     "message": "任务状态丢失（可能服务已重启），请重新发起深度分析。",
                     "request_id": request_id}
    return 202, {"job_id": job_id, "status": "running",
                 "status_url": f"/api/agent/report/{job_id}", "request_id": request_id}


def agent_report_status(job_id: str, request_id: str) -> tuple[int, dict]:
    import jobs
    job = jobs.get_job(job_id)
    if job is None:
        return 404, {"error": "job_not_found", "request_id": request_id}
    return 200, {**job, "request_id": request_id}


def ask_core(question: str, request_id: str,
             report_ref: dict | None = None) -> tuple[int, dict]:
    """Report Q&A over the official report (auto-023) or an uploaded "mine" report."""
    try:
        ref = _normalize_report_ref(report_ref)
    except ValueError as exc:
        return 400, {"error": "invalid_report_ref",
                     "message": str(exc), "request_id": request_id}
    if ref["kind"] == "mine":
        sections = report_source.sections_from_markdown(ref["content"])
        if not sections:
            return 400, {"error": "invalid_report_content",
                         "message": "引用的报告内容无法解析出章节，请检查后重试。",
                         "request_id": request_id}
        report_id = ref["report_id"] or "mine"
    else:
        sections = report_source.load_sections()
        if not sections:
            return 503, {"error": "qa_unavailable",
                         "message": "报告问答暂时不可用。右侧研究报告仍可阅读，也可以直接提问查反馈数据。",
                         "request_id": request_id}
        report_id = ref["report_id"] or "official"
    if not model_configured():
        return 503, {"error": "model_unconfigured",
                     "message": "报告问答暂时不可用（未完成配置）。右侧研究报告仍可阅读，也可以直接提问查反馈数据。",
                     "request_id": request_id}
    try:
        answer, citations = _call_report_qa(question, report_source.build_context(sections),
                                            sections)
    except Exception:
        return 503, {"error": "qa_model_failed",
                     "message": "问答模型调用失败，不输出任何生成内容。",
                     "request_id": request_id}
    if citations.get("unknown"):
        return 503, {"error": "citation_invalid",
                     "message": "回答包含无法核验的引用锚点，已拒绝输出；请重试或换个问法。",
                     "request_id": request_id}
    citations["refs"] = [{"anchor": s["id"], "report_id": report_id,
                          "report_kind": ref["kind"]}
                         for s in citations.get("sections", [])]
    return 200, {"answer": answer, "citations": citations,
                 "data_version": service.snapshot_version(),
                 "warnings": ["temporary_snapshot_placeholder"],
                 "request_id": request_id}


MAX_REPORT_CONTEXT_CHARS = 60_000
DEEP_ANALYSIS_GUIDANCE = (
    "这个诉求需要对语义数据做代码级分析并产出正式报告，对话内我完成不了。"
    "请点击输入框上方的「深度分析」按钮发起：它会先和你确认研究主题，"
    "生成分析大纲供你审查，审查通过后在沙箱中执行分析并产出报告。")


def _normalize_report_ref(report_ref: object) -> dict[str, str]:
    """Validate the /api/ask report reference; raises ValueError on bad input."""
    if report_ref is None:
        return {"kind": "official", "report_id": "", "content": ""}
    if not isinstance(report_ref, dict):
        raise ValueError("report_ref 须为对象。")
    kind = report_ref.get("kind", "official")
    if kind not in ("official", "mine"):
        raise ValueError("report_ref.kind 仅支持 official 或 mine。")
    report_id = str(report_ref.get("report_id") or "")[:64]
    content = report_ref.get("content")
    if kind == "mine":
        if not isinstance(content, str) or not content.strip():
            raise ValueError("引用「我的报告」时须随请求提供报告内容 content。")
        if len(content) > MAX_REPORT_CONTEXT_CHARS:
            raise ValueError(f"报告内容超过 {MAX_REPORT_CONTEXT_CHARS} 字符的上下文预算，"
                             "请缩小引用范围或改用深度分析。")
    return {"kind": kind, "report_id": report_id,
            "content": content if kind == "mine" else ""}


def _chat_endpoint() -> str:
    base = os.environ["AI_BASE_URL"].rstrip("/")
    return base if base.endswith("/chat/completions") else base + "/chat/completions"


def question_core(question: str, session_id: str | None, request_id: str) -> tuple[int, dict]:
    """Run every turn through one contextual agent, which can choose tools as needed."""
    if not model_configured():
        return _present(503, {
            "error": "model_unconfigured",
            "message": "智能对话暂不可用；请检查模型配置后重试。",
            "request_id": request_id})
    session = SESSIONS.get(session_id) if session_id else None
    if session and session.get("turns", 0) >= SESSION_MAX_TURNS:
        return _present(429, {"error": "session_turn_limit",
                              "message": "本会话已达最大轮数，请开始新会话。",
                              "request_id": request_id})
    try:
        import agent_engine
        result = agent_engine.run_agent_conversation(
            question, history=(session or {}).get("history", []), session=session)
    except Exception as exc:
        print(json.dumps({"request_id": request_id, "event": "agent_failure",
                          "error_type": type(exc).__name__}, ensure_ascii=False))
        return _present(503, {
            "error": "agent_unavailable",
            "message": "暂时连不上对话模型。你的问题已保留；模型服务恢复后可以重试。",
            "request_id": request_id})
    if not isinstance(result, dict) or not isinstance(result.get("answer"), str) \
            or not result["answer"].strip():
        return _present(503, {"error": "agent_empty_response",
                              "message": "这次没有生成可用回答，请稍后重试。",
                              "request_id": request_id})
    if result.get("report_md") or result.get("report_generated") or result.get("submission"):
        # D8 行为级兜底：对话 Agent 不产出报告；相关工具已按 auto-030 收回，
        # 此分支仅在异常回归时触发，统一替换为深度分析引导。
        return _present(200, {
            "answer": DEEP_ANALYSIS_GUIDANCE, "response_type": "conversation",
            "stats": [], "evidence": [], "applied_filters": {},
            "citations": {"cited": [], "valid": [], "unknown": [],
                          "sections": [], "refs": []},
            "warnings": ["deep_analysis_guided"], "request_id": request_id})
    citations = result.get("citations")
    if isinstance(citations, dict):
        citations["refs"] = [{"anchor": s.get("id", ""), "report_id": "official",
                              "report_kind": "official"}
                             for s in citations.get("sections", [])]
    if session_id:
        if session_id not in SESSIONS and len(SESSIONS) >= MAX_SESSIONS:
            SESSIONS.pop(next(iter(SESSIONS)))
        record = SESSIONS.setdefault(session_id, {"filters": {}, "turns": 0, "history": []})
        record["history"] = [*(record.get("history", [])),
                              {"role": "user", "content": question},
                              {"role": "assistant", "content": result["answer"]}][-12:]
        record["turns"] = record.get("turns", 0) + 1
        record["last_question"] = question
        record["last_result"] = {key: result.get(key) for key in (
            "stats", "evidence", "data_version", "warnings")}
        if result.get("applied_filters"):
            record["filters"] = result["applied_filters"]
    return _present(200, {**result, "response_type": "conversation",
                          "request_id": request_id})


def _present(status: int, payload: dict) -> tuple[int, dict]:
    """User-facing presentation: neutral version token + temporary-sample flag."""
    if isinstance(payload, dict):
        if payload.get("source_mode") == "live_transaction":
            payload["data_version"] = "实时数据"
            payload["temporary_sample"] = False
        else:
            payload["data_version"] = service.display_version()
            payload["temporary_sample"] = service.temporary_sample()
    return status, payload


class Handler(BaseHTTPRequestHandler):
    server_version = "AutoInsight/0.3"

    def log_message(self, fmt: str, *args: object) -> None:
        # Access logs stay free of query strings and bodies (they carry user input).
        print(json.dumps({"request_id": getattr(self, "request_id", ""), "method": self.command,
                          "path": urlparse(self.path).path, "status": getattr(self, "_status", 0)}))

    def _json(self, status: int, payload: dict) -> None:
        self._status = status
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    # ---------------- GET ----------------
    def do_GET(self) -> None:
        self.request_id = uuid.uuid4().hex[:12]
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        try:
            if parsed.path == "/api/health":
                result = service.health()
                return self._json(200 if result["status"] == "ok" else 503, result)
            if parsed.path == "/api/stats":
                return self._json(200, service.query_stats(_one(params, "aspect")))
            if parsed.path == "/api/claims":
                return self._json(200, service.query_claims(
                    aspect=_one(params, "aspect"), sentiment=_one(params, "sentiment"),
                    journey=_one(params, "journey"), ownership=_one(params, "ownership"),
                    limit=int(_one(params, "limit", "5")), offset=int(_one(params, "offset", "0"))))
            if parsed.path == "/api/reports/published/latest":
                published = report_publisher.latest_published()
                if published is None:
                    return self._json(404, {"error": "published_report_missing",
                                            "request_id": self.request_id})
                return self._json(200, {"report": published["meta"],
                                        "markdown": published["markdown"],
                                        "request_id": self.request_id})
            if parsed.path.startswith("/api/agent/report/"):
                job_id = parsed.path.removeprefix("/api/agent/report/")
                if Path(job_id).name != job_id or not job_id:
                    return self._json(400, {"error": "invalid_job_id", "request_id": self.request_id})
                status_code, payload = agent_report_status(job_id, self.request_id)
                return self._json(status_code, payload)
            if parsed.path == "/api/suggestions":
                return self._json(200, _suggestions_payload())
            if parsed.path == "/api/analysis/options":
                import task_brief
                return self._json(200, {**task_brief.form_options(),
                                        "request_id": self.request_id})
            if parsed.path == "/report/full":
                return self._legacy_report()
            if parsed.path == "/api/ask":
                return self._json(405, {"error": "method_not_allowed", "request_id": self.request_id})
            if parsed.path == "/" or parsed.path.startswith("/static/"):
                return self._static(self.path)
            return self._json(404, {"error": "not_found", "request_id": self.request_id})
        except (ValueError, TypeError):
            return self._json(400, {"error": "invalid_query",
                                    "message": "筛选条件或分页参数不合法。", "request_id": self.request_id})
        except Exception:
            return self._json(500, {"error": "internal_error",
                                    "message": "查询暂时不可用。", "request_id": self.request_id})

    def _legacy_report(self) -> None:
        published_html = report_publisher.render_published_html()
        if published_html:
            html = published_html
            label = "研究报告 · 已审核发布"
        elif not LEGACY_REPORT.is_file():
            return self._json(404, {"error": "report_missing",
                                    "message": "设计版报告文件不存在。", "request_id": self.request_id})
        else:
            html = LEGACY_REPORT.read_text(encoding="utf-8")
            label = "研究报告 · 演示样本"
        # Runtime brand skin: published and legacy reports use the same system.
        if "/static/report-skin.css" not in html:
            skin = '<link rel="stylesheet" href="/static/report-skin.css">'
            html = html.replace("</head>", skin + "</head>", 1)
        version = service.display_version()
        if service.temporary_sample():
            version += " · 临时样本"
        banner = ('<div class="ai-banner"><b>AutoInsight · 新能源洞察工作台</b>'
                  f'<span>{label}</span>'
                  f'<span class="ai-chip">数据版本：{version}</span></div>')
        if '<div class="ai-banner"' not in html:
            html = html.replace("<body>", "<body>" + banner, 1)
        body = html.encode("utf-8")
        self._status = 200
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _static(self, path: str) -> None:
        parsed = urlparse(path)
        name = "index.html" if parsed.path == "/" else parsed.path.removeprefix("/static/")
        if Path(name).name != name:
            return self._json(404, {"error": "not_found"})
        target = WEB / name
        if not target.is_file():
            return self._json(404, {"error": "not_found"})
        body = target.read_bytes()
        self._status = 200
        content_type = {
            ".html": "text/html; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".js": "application/javascript; charset=utf-8",
            ".mjs": "application/javascript; charset=utf-8",
            ".json": "application/json; charset=utf-8",
            ".png": "image/png",
            ".svg": "image/svg+xml",
            ".ico": "image/x-icon",
        }.get(target.suffix, "application/octet-stream")
        # 版本化资源（?v=）内容不变可长缓存；未版本化资源用 ETag 协商（7.3）
        cache_control = ("public, max-age=31536000, immutable" if parsed.query
                         else "no-cache")
        etag = f'"{hashlib.sha256(body).hexdigest()[:16]}"'
        if self.headers.get("If-None-Match") == etag:
            self._status = 304
            self.send_response(304)
            self.send_header("ETag", etag)
            self.send_header("Cache-Control", cache_control)
            self.end_headers()
            return
        # 文本类资源按客户端能力 gzip 传输（7.3）
        accepts_gzip = "gzip" in (self.headers.get("Accept-Encoding") or "")
        compressible = target.suffix in {".html", ".css", ".js", ".mjs", ".json"}
        gzipped = accepts_gzip and compressible and len(body) > 512
        if gzipped:
            body = gzip.compress(body, 6)
        self.send_response(200)
        if gzipped:
            self.send_header("Content-Encoding", "gzip")
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", cache_control)
        self.send_header("ETag", etag)
        self.send_header("Vary", "Accept-Encoding")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    # ---------------- POST ----------------
    def do_POST(self) -> None:
        self.request_id = uuid.uuid4().hex[:12]
        sub_action = None  # (job_id, "outline"|"clarify")
        for action in ("outline", "clarify"):
            if self.path.startswith("/api/agent/report/") and self.path.endswith(f"/{action}"):
                candidate = self.path.removeprefix("/api/agent/report/").removesuffix(f"/{action}")
                if Path(candidate).name != candidate or not candidate:
                    return self._json(400, {"error": "invalid_job_id", "request_id": self.request_id})
                sub_action = (candidate, action)
                break
        if sub_action is None and \
                self.path not in ("/api/ask", "/api/question", "/api/agent/report"):
            return self._json(404, {"error": "not_found", "request_id": self.request_id})
        ip = self.client_address[0]
        if _rate_limited(ip):
            return self._json(429, {"error": "rate_limited",
                                    "message": "请求过于频繁，请稍后再试。", "request_id": self.request_id})
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if size > MAX_BODY:
                return self._json(413, {"error": "request_too_large",
                                        "message": "请求体过大。", "request_id": self.request_id})
            data = json.loads(self.rfile.read(size) or b"{}")
            if not isinstance(data, dict):
                return self._json(400, {"error": "invalid_body", "request_id": self.request_id})
            if sub_action is not None:
                job_id, action = sub_action
                handler = agent_report_outline if action == "outline" else agent_report_clarify
                status, payload = handler(job_id, data, self.request_id)
                return self._json(status, payload)
            question = data.get("question")
            if not isinstance(question, str) or not question.strip() or len(question) > MAX_QUESTION:
                return self._json(400, {"error": "invalid_question",
                                        "message": f"请输入 1 到 {MAX_QUESTION} 字的问题。",
                                        "request_id": self.request_id})
            session_id = data.get("session_id")
            if session_id is not None and (not isinstance(session_id, str) or not session_id or len(session_id) > 64):
                return self._json(400, {"error": "invalid_session",
                                        "message": "session_id 须为 1–64 字符。", "request_id": self.request_id})
            if self.path == "/api/ask":
                status, payload = ask_core(question.strip(), self.request_id,
                                           data.get("report_ref"))
            elif self.path == "/api/agent/report":
                import task_brief
                clean_brief, rejection = task_brief.validate_brief(data.get("brief"))
                if rejection is not None:
                    return self._json(400, {**rejection, "request_id": self.request_id})
                status, payload = agent_report_start(question.strip(), self.request_id,
                                                     brief=clean_brief,
                                                     session_id=session_id)
            else:
                status, payload = question_core(question.strip(), session_id, self.request_id)
            return self._json(status, payload)
        except (ValueError, TypeError, json.JSONDecodeError):
            return self._json(400, {"error": "invalid_request",
                                    "message": "请求格式不合法。", "request_id": self.request_id})
        except Exception:
            return self._json(500, {"error": "internal_error",
                                    "message": "服务暂时不可用，请稍后重试或直接阅读静态报告。",
                                    "request_id": self.request_id})





def _call_report_qa(question: str, context: str,
                    sections: list | None = None) -> tuple[str, dict]:
    """Q&A over the given report; citations map to its section ids."""
    import urllib.request
    allowed = [s["id"] for s in (sections if sections is not None
                                 else report_source.load_sections()) if s["id"]]
    id_rule = ("3) 引用依据时在句末用方括号标注章节 ID；只能使用上下文中出现的 ID："
               + ", ".join(allowed)
               + "。清单之外的 ID 一律不得出现；")
    messages = [
        {"role": "system",
         "content": "你是 AutoInsight 研究报告的问答助手。严格规则："
                    "1) 只依据下方报告内容回答，不得引入报告之外的事实或推测；"
                    "2) 回答中的数字必须逐字来自报告；"
                    + id_rule +
                    "4) 报告未覆盖的问题要明确说明不可回答，并指出可回答的范围；"
                    "5) 用中文回答，先给结论再给依据。"},
        {"role": "user",
         "content": f"报告内容：\n\n{context}\n\n---\n\n用户问题：{question}"}]
    body = json.dumps({"model": os.environ["AI_MODEL"], "messages": messages,
                       "temperature": 0, "max_tokens": 900}).encode()
    request = urllib.request.Request(
        _chat_endpoint(), data=body,
        headers={"Authorization": "Bearer " + os.environ["AI_API_KEY"],
                 "Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=45) as response:
        payload = json.loads(response.read())
    raw = payload["choices"][0]["message"]["content"]
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("empty report QA response")
    # auto-030：校验必须针对本次回答所依据的 sections（mine 上传内容有独立编号）
    citations = report_source.parse_citations(raw, sections)
    footer = f"\n\n---\n数据版本：{service.snapshot_version()}（报告问答，引用章节可点击跳转）。"
    return raw + footer, citations


def _suggestions_payload() -> dict:
    """Dynamic starter questions: derived from the displayed report sections and
    the snapshot's own aspect ranking (no hand-written seeds)."""
    suggestions: list[dict[str, str]] = []
    labels = report_source.section_labels()
    for anchor, kind in (("F1", "report"), ("s-method", "report"), ("s-rec", "report")):
        title = labels.get(anchor)
        if title:
            suggestions.append({"text": f"报告里关于「{title}」的结论是什么？", "kind": kind})
    try:
        stats = service.query_stats()
        top = sorted(stats["data"], key=lambda r: r["negativeShare"], reverse=True)[:3]
        for row in top:
            suggestions.append({"text": f"「{row['aspect']}」的负向声量和证据是什么？", "kind": "data"})
    except (OSError, KeyError, ValueError):
        pass
    return {"suggestions": suggestions, "data_version": service.snapshot_version()}


def _one(params: dict[str, list[str]], key: str, default: str | None = None) -> str | None:
    values = params.get(key)
    return values[0] if values else default


if __name__ == "__main__":
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "8000"))
    print(f"AutoInsight listening on http://{host}:{port}")
    ThreadingHTTPServer((host, port), Handler).serve_forever()
