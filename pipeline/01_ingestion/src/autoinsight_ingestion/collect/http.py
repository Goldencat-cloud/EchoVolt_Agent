from __future__ import annotations

import time
import urllib.error
import urllib.parse
import urllib.request

from ..contracts import IngestionError, now, safe_metadata
from .credentials import cookie_header, load_cookies

HOSTS = {"club.autohome.com.cn", "club.m.autohome.com.cn", "i.autohome.com.cn", "car-web-api.autohome.com.cn"}
REDIRECT_STATUSES = (301, 302, 307, 308)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Transport:
    def __init__(self, store, run_id, config, cancelled=lambda: False):
        self.store, self.run_id, self.config = store, run_id, config
        self.cancelled = cancelled
        self.used = 0
        self.last_request = 0.0
        self.opener = urllib.request.build_opener(NoRedirect())
        self.targets = {}
        self.credential_path = None

    def attach_credentials(self, path):
        """Validate and enable runtime credential injection; values stay out of persisted state."""
        load_cookies(path)
        self.credential_path = path

    def _credentials_state(self):
        return "provided" if self.credential_path else "absent"

    def get(self, url, validator=None, _depth=0):
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme != "https" or parsed.hostname not in HOSTS or parsed.port not in (None, 443) or parsed.username or parsed.password:
            raise IngestionError("target_not_allowed")
        if not self.config.allow_network:
            raise IngestionError("network_not_authorized")
        task_id = self.store.task(self.run_id, "http", url)
        self.targets[task_id] = url
        for attempt in range(self.config.max_attempts):
            if self.cancelled():
                raise IngestionError("cancelled")
            if self.used >= self.config.max_requests:
                raise IngestionError("request_budget_exhausted")
            time.sleep(max(0, 1 / self.config.rps - (time.monotonic() - self.last_request)))
            if self.cancelled():
                raise IngestionError("cancelled")
            self.used += 1
            self.last_request = time.monotonic()
            response_id, status, error, content = None, None, None, b""
            headers = {"User-Agent": "AutoInsightResearch/0.1 (bounded ingestion)", "Accept": "text/html,application/json", "Accept-Encoding": "identity"}
            if self.credential_path:
                cookie = cookie_header(load_cookies(self.credential_path), parsed.hostname)
                if cookie:
                    headers["Cookie"] = cookie
            req = urllib.request.Request(url, headers=headers)
            location = None
            try:
                with self.opener.open(req, timeout=self.config.timeout_seconds) as response:
                    status = response.status
                    content = response.read(12_000_001)
                    location = response.headers.get("Location")
            except urllib.error.HTTPError as e:
                status = e.code
                content = e.read(12_000_001)
                error = "http_error"
                location = e.headers.get("Location") if e.headers else None
            except (urllib.error.URLError, TimeoutError, OSError):
                error = "connection_failed"
            acquired = now()
            if len(content) > 12_000_000:
                error = "response_too_large"
            meta = {"url": url, "http_status": status, "credentials": self._credentials_state()}
            if status in REDIRECT_STATUSES and location:
                meta["redirect_target"] = safe_metadata(urllib.parse.urljoin(url, location))
            response_id = self.store.response(task_id, content, meta, acquired, "http_body")
            self.store.attempt(self.run_id,url,status,error,response_id,acquired)
            if status in (401, 403, 405, 429):
                self.fail(task_id, "blocked_or_rate_limited")
                raise IngestionError("blocked_or_rate_limited")
            if status in REDIRECT_STATUSES:
                resolved = urllib.parse.urljoin(url, location) if location else None
                parts = urllib.parse.urlsplit(resolved) if resolved else None
                allowed = bool(parts) and parts.scheme == "https" and parts.hostname in HOSTS \
                    and parts.port in (None, 443) and not parts.username and not parts.password
                if not allowed or _depth >= 1:
                    self.fail(task_id, "redirect_rejected")
                    raise IngestionError("redirect_rejected")
                return self.get(resolved, validator, _depth=_depth + 1)
            text = None
            for encoding in ('utf-8-sig','gb18030'):
                try:
                    text=content.decode(encoding); break
                except UnicodeError: pass
            if text is None:
                self.fail(task_id,'response_encoding_unrecognized')
                raise IngestionError('response_encoding_unrecognized')
            if any(word in text[:100000] for word in ["用户访问安全认证", "请完成安全验证", "访问过于频繁"]):
                self.fail(task_id, "blocked")
                raise IngestionError("blocked")
            if not error and status == 200:
                try:
                    parsed = validator(text) if validator else None
                except IngestionError as exc:
                    self.store.mark_parsed(response_id,'failed',{'error_code':exc.code})
                    self.store.failure(self.run_id,url,exc.code,snapshot_id=response_id)
                    if exc.code == 'blocked': raise
                    error = exc.code
                else:
                    self.store.resolved(self.run_id,url)
                    return {"task_id": task_id, "response_id": response_id, "body": content, "text": text, "retrieved_at": acquired,'parsed':parsed}
            if error == "response_too_large" or (status and status != 200 and status < 500):
                break
            if attempt + 1 < self.config.max_attempts:
                time.sleep(min(2 ** attempt, 4))
        self.fail(task_id, error or "unexpected_http_status")
        raise IngestionError(error or "unexpected_http_status")

    def fail(self, task_id, code):
        self.store.failure(self.run_id,self.targets.get(task_id,task_id),code)
