"""仅绑定本机的事件聚合网页与后台任务 API。"""
from __future__ import annotations

import argparse
import json
import os
import threading
import uuid
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from . import core, storage
from .volcengine import VolcengineConfigError

ROOT = Path(__file__).resolve().parents[2]
WEB_ROOT = ROOT / "web"
JOB_ROOT = ROOT / ".local" / "web-jobs"


def validate_input(data):
    if not isinstance(data, dict):
        raise ValueError("请求必须是JSON对象")
    for name in ("brand", "product"):
        if not isinstance(data.get(name), str) or not 1 <= len(data[name].strip()) <= 30:
            raise ValueError("品牌与产品须为1至30字")
    start, end = data.get("time_from"), data.get("time_to")
    from datetime import date
    if not start or not end or date.fromisoformat(start) > date.fromisoformat(end):
        raise ValueError("请填写有效的起止日期")
    if (date.fromisoformat(end) - date.fromisoformat(start)).days > 366 * 10:
        raise ValueError("单次时间窗不能超过10年")
    aspects = data.get("aspects")
    if not isinstance(aspects, list) or not aspects or any(a not in core.ASPECTS for a in aspects):
        raise ValueError("请选择有效的研究主题")
    domains = data.get("official_domains", [])
    if not isinstance(domains, list) or len(domains) > 20 or any(
        not isinstance(d, str) or not d or any(c in d for c in '/|: ') for d in domains):
        raise ValueError("官方域名须为最多20个完整域名，不带协议与路径")
    hint = data.get("domain_hint", "")
    if not isinstance(hint, str) or len(hint) > 20:
        raise ValueError("领域提示最多20字")
    values = {"brand": data["brand"].strip(), "product": data["product"].strip(),
              "time_from": start, "time_to": end, "aspects": list(dict.fromkeys(aspects)),
              "official_domains": domains, "domain_hint": hint or None}
    queries = core.build_queries(values["brand"], values["product"], values["aspects"], start, end, hint)
    if any(len(q["query"]) > 100 for q in queries):
        raise ValueError("生成的搜索词超过100字，请缩短输入")
    return values, len(queries)


class Jobs:
    def __init__(self, root=JOB_ROOT):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.jobs = {}
        for file in self.root.glob("*/job.json"):
            try:
                job = json.loads(file.read_text(encoding="utf-8"))
                if job["status"] in ("running", "queued"):
                    job.update(status="interrupted", phase="服务重启，任务中断；请重新启动调研")
                self.jobs[job["id"]] = job
            except (ValueError, KeyError):
                continue

    def save(self, job):
        folder = self.root / job["id"]
        folder.mkdir(exist_ok=True)
        temporary = folder / "job.tmp"
        temporary.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(folder / "job.json")

    def start(self, data):
        values, count = validate_input(data)
        with self.lock:
            if any(j["status"] in ("running", "queued") for j in self.jobs.values()):
                raise RuntimeError("已有调研运行中，请等待完成，避免重复消耗配额")
            job = {"id": uuid.uuid4().hex, "status": "queued", "phase": "等待开始",
                   "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                   "input": values, "query_count": count, "completed_queries": 0}
            self.jobs[job["id"]] = job
            self.save(job)
            threading.Thread(target=self.run, args=(job["id"],), daemon=True).start()
            return dict(job)

    def run(self, job_id):
        with self.lock:
            job = self.jobs[job_id]
            job.update(status="running", phase="搜索与过滤")
            self.save(job)
        def progress(phase, completed, total):
            with self.lock:
                job.update(phase=phase, completed_queries=completed, query_count=total)
                self.save(job)
        try:
            timeline = core.run(**job["input"], progress_callback=progress)
            output = storage.save_timeline(timeline, self.root / job_id)
            with self.lock:
                job.update(status="completed", phase="完成", summary=storage.summary(timeline, output),
                           llm_used=timeline["meta"]["llm_used"])
        except (VolcengineConfigError, ValueError) as exc:
            with self.lock:
                job.update(status="failed", phase="失败", error=str(exc))
        except Exception:
            with self.lock:
                job.update(status="failed", phase="失败", error="任务执行失败，请检查本地服务日志与配置")
        finally:
            with self.lock:
                job["finished_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
                self.save(job)

    def snapshot(self, job_id=None):
        with self.lock:
            value = self.jobs.get(job_id) if job_id else sorted(self.jobs.values(), key=lambda j: j["created_at"], reverse=True)
            return json.loads(json.dumps(value))


def handler(jobs):
    class Handler(BaseHTTPRequestHandler):
        def send(self, status, body, content_type="application/json; charset=utf-8", attachment=None):
            if not isinstance(body, bytes):
                body = json.dumps(body, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            if attachment:
                self.send_header("Content-Disposition", f'attachment; filename="timeline.{attachment}"')
            self.end_headers()
            self.wfile.write(body)

        def local_request(self):
            if self.headers.get("Host") not in (f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"):
                return False
            origin = self.headers.get("Origin")
            return not origin or origin in (f"http://127.0.0.1:{self.server.server_port}", f"http://localhost:{self.server.server_port}")

        def do_GET(self):
            if not self.local_request():
                return self.send(403, {"error": "只接受本机同源请求"})
            path = urlparse(self.path).path
            if path == "/":
                return self.send(200, (WEB_ROOT / "index.html").read_bytes(), "text/html; charset=utf-8")
            if path == "/api/config":
                return self.send(200, {"search": bool(os.getenv("VOLCENGINE_SEARCH_API_KEY") or os.getenv("ASK_ECHO_SEARCH_INFINITY_API_KEY")),
                    "llm": all(os.getenv(k) for k in ("OPENAI_API_KEY", "OPENAI_BASE_URL", "AGENT_MODEL")),
                    "embedding": all(os.getenv(k) for k in ("EMBEDDING_API_KEY", "EMBEDDING_BASE_URL", "EMBEDDING_MODEL"))})
            if path == "/api/jobs":
                return self.send(200, jobs.snapshot())
            parts = path.strip("/").split("/")
            if len(parts) in (3, 4) and parts[:2] == ["api", "jobs"]:
                job = jobs.snapshot(parts[2])
                if not job:
                    return self.send(404, {"error": "任务不存在"})
                if len(parts) == 3:
                    return self.send(200, job)
                if parts[3] in ("result", "json", "txt") and job.get("summary"):
                    suffix = ".txt" if parts[3] == "txt" else ".json"
                    file = Path(job["summary"]["output_path"]).with_suffix(suffix)
                    return self.send(200, file.read_bytes(), "text/plain; charset=utf-8" if suffix == ".txt" else "application/json; charset=utf-8",
                                     parts[3] if parts[3] in ("json", "txt") else None)
            self.send(404, {"error": "路径不存在"})

        def do_POST(self):
            if not self.local_request():
                return self.send(403, {"error": "只接受本机同源请求"})
            if self.path != "/api/jobs":
                return self.send(404, {"error": "路径不存在"})
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 16384 or not self.headers.get("Content-Type", "").startswith("application/json"):
                    raise ValueError("请发送小于16KB的JSON请求")
                self.send(202, jobs.start(json.loads(self.rfile.read(length))))
            except (ValueError, TypeError) as exc:
                self.send(400, {"error": str(exc)})
            except RuntimeError as exc:
                self.send(409, {"error": str(exc)})
    return Handler


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8879)
    args = parser.parse_args()
    ThreadingHTTPServer(("127.0.0.1", args.port), handler(Jobs())).serve_forever()
