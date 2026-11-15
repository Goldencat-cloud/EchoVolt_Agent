"""HTTP 协议层：路由、请求验证、限流、静态资源与已发布报告的服务。

本轮重构从 app.py 拆出。本层只做协议工作：
- GET 路由（健康/统计/claims/发布报告/任务状态/建议问题/静态资源/报告页）；
- POST 路由（问答/对话/深度分析任务与澄清/大纲审查）；
- 请求体大小与字段校验、IP 限流、JSON 编码与安全头。

业务逻辑一律委托 orchestrator（经模块属性晚绑定调用，测试可 patch）。
"""
from __future__ import annotations

import gzip
import hashlib
import json
import time
import uuid
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from research import service
import report_publisher
import orchestrator

WEB = Path(__file__).with_name("web")
# auto-023 designed report (single-file HTML, charts embedded as base64).
LEGACY_REPORT = Path(__file__).resolve().parents[1] / "06_reporting" / "agent-kb" / "output" / "report.html"
MAX_BODY = 512 * 1024
# E2E 实测（2026-10-28）：一次深度分析 = 1 启动 + 最多 2 澄清答复 + 1-2 审查动作，
# 10/60s 会被单个正常会话耗尽并殃及后续启动，提到 20/60s。
RATE_LIMIT_REQUESTS = 20
RATE_WINDOW_SECONDS = 60.0

_RATE: dict[str, list[float]] = {}


def _rate_limited(ip: str) -> bool:
    now = time.monotonic()
    stamps = [t for t in _RATE.get(ip, []) if now - t < RATE_WINDOW_SECONDS]
    if len(stamps) >= RATE_LIMIT_REQUESTS:
        _RATE[ip] = stamps
        return True
    stamps.append(now)
    _RATE[ip] = stamps
    return False


def _one(params: dict[str, list[str]], key: str, default: str | None = None) -> str | None:
    values = params.get(key)
    return values[0] if values else default


class Handler(BaseHTTPRequestHandler):
    server_version = "AutoInsight/0.4"

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
                status_code, payload = orchestrator.agent_report_status(job_id, self.request_id)
                return self._json(status_code, payload)
            if parsed.path == "/api/suggestions":
                return self._json(200, orchestrator._suggestions_payload())
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
            html, label = published_html, "研究报告 · 已审核发布"
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
                handler = orchestrator.agent_report_outline if action == "outline" \
                    else orchestrator.agent_report_clarify
                status, payload = handler(job_id, data, self.request_id)
                return self._json(status, payload)
            question = data.get("question")
            if not isinstance(question, str) or not question.strip() or len(question) > orchestrator.MAX_QUESTION:
                return self._json(400, {"error": "invalid_question",
                                        "message": f"请输入 1 到 {orchestrator.MAX_QUESTION} 字的问题。",
                                        "request_id": self.request_id})
            session_id = data.get("session_id")
            if session_id is not None and (not isinstance(session_id, str) or not session_id or len(session_id) > 64):
                return self._json(400, {"error": "invalid_session",
                                        "message": "session_id 须为 1–64 字符。", "request_id": self.request_id})
            if self.path == "/api/ask":
                status, payload = orchestrator.ask_core(question.strip(), self.request_id,
                                                        data.get("report_ref"))
            elif self.path == "/api/agent/report":
                import task_brief
                clean_brief, rejection = task_brief.validate_brief(data.get("brief"))
                if rejection is not None:
                    return self._json(400, {**rejection, "request_id": self.request_id})
                status, payload = orchestrator.agent_report_start(question.strip(), self.request_id,
                                                                  brief=clean_brief,
                                                                  session_id=session_id)
            else:
                status, payload = orchestrator.question_core(question.strip(), session_id, self.request_id)
            return self._json(status, payload)
        except (ValueError, TypeError, json.JSONDecodeError):
            return self._json(400, {"error": "invalid_request",
                                    "message": "请求格式不合法。", "request_id": self.request_id})
        except Exception:
            return self._json(500, {"error": "internal_error",
                                    "message": "服务暂时不可用，请稍后重试或直接阅读静态报告。",
                                    "request_id": self.request_id})
