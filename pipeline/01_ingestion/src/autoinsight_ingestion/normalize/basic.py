from __future__ import annotations

import html
import re
from datetime import datetime, timedelta

from ..contracts import source_timezone


def clean_text(value: str) -> str:
    text = html.unescape(str(value or "")).replace("\r\n", "\n").replace("\r", "\n")
    return "\n".join(re.sub(r"[\t \u00a0]+", " ", line).strip() for line in text.split("\n")).strip()


def number(value):
    s = str(value if value is not None else "").strip().replace(",", "")
    match = re.fullmatch(r"(\d+(?:\.\d+)?)(万|亿)?", s)
    if not match:
        return None
    result = float(match[1]) * {None: 1, "万": 10000, "亿": 100000000}[match[2]]
    return int(result) if result.is_integer() else result


def parse_time(raw, retrieved_at=None):
    """Relative values are anchored to saved acquisition time, never today's date."""
    raw = str(raw or "").strip()
    normalized = raw.replace("/", "-")
    try:
        dt = datetime.fromisoformat(normalized)
        dt = dt if dt.tzinfo else dt.replace(tzinfo=source_timezone())
        if len(normalized) == 10:
            return {"value": dt.date().isoformat(), "precision": "day", "basis": "explicit", "raw": raw}
        return {"value": dt.isoformat(), "precision": "second", "basis": "explicit", "raw": raw}
    except ValueError:
        pass
    match = re.fullmatch(r"(\d+)\s*天前", raw)
    days = int(match[1]) if match else {"今天": 0, "昨天": 1, "前天": 2}.get(raw)
    if days is not None and retrieved_at:
        try:
            anchor = datetime.fromisoformat(retrieved_at)
            if not anchor.tzinfo:
                # Ambiguous historical anchor is not silently interpreted.
                raise ValueError
            day = anchor.astimezone(source_timezone()).date() - timedelta(days=days)
            return {"value": day.isoformat(), "precision": "day", "basis": "relative_to_retrieval", "raw": raw}
        except (ValueError, TypeError):
            pass
    return {"value": None, "precision": "unknown", "basis": "unknown", "raw": raw}


def post_id(url):
    s = str(url or "")
    for pattern in [r"/bbs/thread/(?:[a-zA-Z0-9]+/)?(\d+)-\d+\.html", r"/bbs/thread-c-\d+-(\d+)-"]:
        m = re.search(pattern, s)
        if m:
            return m[1]
    return ""


def user_id(url):
    m = re.search(r"(?:i|i\.m)\.autohome\.com\.cn/(\d+)(?:/|$)", str(url or ""))
    return m[1] if m else ""
