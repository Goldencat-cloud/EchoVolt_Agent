"""Runtime-only credential loading; cookie values never enter persisted artifacts."""
from __future__ import annotations

import json
import time
from pathlib import Path

from ..contracts import IngestionError


def load_cookies(path, *, at_time=None):
    """Parse a Playwright storageState file; raise typed errors on missing/invalid input."""
    if not path:
        return []
    try:
        raw = Path(path).read_bytes()
    except OSError:
        raise IngestionError("credential_file_missing") from None
    try:
        data = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeError, ValueError):
        raise IngestionError("credential_file_invalid") from None
    cookies = data.get("cookies") if isinstance(data, dict) else None
    if not isinstance(cookies, list) or any(not isinstance(c, dict) for c in cookies):
        raise IngestionError("credential_file_invalid")
    return [c for c in cookies if isinstance(c.get("name"), str) and isinstance(c.get("value"), str)]


def _matches(cookie_domain, host):
    domain = (cookie_domain or "").lstrip(".").lower()
    host = (host or "").lower()
    if not domain or not host:
        return False
    return host == domain or host.endswith("." + domain)


def cookie_header(cookies, host, *, at_time=None):
    """Build a Cookie header for host; drop expired and foreign-domain cookies."""
    current = time.time() if at_time is None else at_time
    usable = []
    for c in cookies:
        if not _matches(c.get("domain"), host):
            continue
        expires = c.get("expires")
        if isinstance(expires, (int, float)) and expires >= 0 and expires < current:
            continue
        usable.append(c)
    if not usable:
        return None
    usable.sort(key=lambda c: (-(len(c.get("path") or "")), c.get("name") or ""))
    return "; ".join(f"{c['name']}={c['value']}" for c in usable)
