"""Four localhost-only JSON endpoints. No arbitrary file, URL or shell tools."""
from __future__ import annotations

import hmac
import json
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .contracts import IngestionError, canonical


def make_server(service, port=8876, token=""):
    class Handler(BaseHTTPRequestHandler):
        server_version = "AutoInsightIngestion/0.1"

        def log_message(self, *_):
            # Do not log user-supplied paths, headers or error bodies.
            pass

        def send_json(self, status, value):
            body = canonical(value).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def dispatch(self):
            if self.headers.get("Origin") or self.headers.get("Host", "").split(":")[0] not in {"127.0.0.1", "localhost"}:
                self.send_json(403, {"error_code": "browser_or_host_not_allowed"})
                return
            if token and not hmac.compare_digest(self.headers.get("Authorization", ""), "Bearer " + token):
                self.send_json(401, {"error_code": "unauthorized"})
                return
            try:
                if self.command == "POST" and self.path == "/v1/ingestion/jobs":
                    if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                        raise IngestionError("json_content_type_required")
                    length = int(self.headers.get("Content-Length", "0"))
                    if not 0 < length <= 16384:
                        raise IngestionError("invalid_body_length")
                    request = json.loads(self.rfile.read(length))
                    result = service.submit(self.headers.get("Idempotency-Key", ""), request)
                    self.send_json(202, result)
                    return
                match = re.fullmatch(r"/v1/ingestion/jobs/([a-f0-9]{32})(?:/(resume|cancel))?", self.path)
                if match and self.command == "GET" and match[2] is None:
                    self.send_json(200, service.status(match[1]))
                    return
                if match and self.command == "POST" and match[2]:
                    self.send_json(202, service.action(match[1], match[2]))
                    return
                self.send_json(404, {"error_code": "route_not_found"})
            except IngestionError as error:
                status = 404 if error.code == "job_not_found" else (409 if error.code in {"idempotency_conflict", "job_state_conflict"} else (503 if error.code == "queue_full" else 400))
                self.send_json(status, {"error_code": error.code})
            except (ValueError, UnicodeError, TypeError):
                self.send_json(400, {"error_code": "invalid_request_body"})
            except Exception:
                self.send_json(500, {"error_code": "internal_error"})

        do_GET = dispatch
        do_POST = dispatch

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    return server
