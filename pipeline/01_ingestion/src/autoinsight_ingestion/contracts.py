"""Small, strict contracts shared by CLI, storage and future HTTP workers."""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class IngestionError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def canonical(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def implementation_fingerprint():
    import platform
    from . import __version__
    root = Path(__file__).resolve().parent
    files = {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
             for p in sorted(root.rglob("*")) if p.is_file() and p.suffix in {".py", ".sql"}}
    return {"package_version": __version__, "python_version": platform.python_version(),
            "source_sha256": digest(files), "runtime_dependencies": "stdlib-only"}


def safe_metadata(value):
    """Strip credential fields even if an internal caller accidentally supplies them."""
    from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
    sensitive = {"authorization", "cookie", "set-cookie", "api_key", "apikey", "token", "password", "secret", "session", "auth"}
    if isinstance(value, dict):
        return {k: safe_metadata(v) for k, v in value.items() if k.lower() not in sensitive}
    if isinstance(value, list):
        return [safe_metadata(v) for v in value]
    if isinstance(value, str) and value.startswith(("https://", "http://")):
        u = urlsplit(value)
        query = [(k, v) for k, v in parse_qsl(u.query, keep_blank_values=True) if k.lower() not in sensitive]
        return urlunsplit((u.scheme, u.hostname or "", u.path, urlencode(query), ""))
    return value


def source_timezone(name="Asia/Shanghai"):
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        if name == "Asia/Shanghai":
            # This module handles current forum dates, not historical DST.
            return timezone(timedelta(hours=8), "Asia/Shanghai")
        raise IngestionError("timezone_unavailable") from None


def date_boundary(value: str, *, end=False) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except (ValueError, TypeError):
        raise IngestionError("invalid_time") from None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=source_timezone())
    if end and len(value) == 10:
        dt += timedelta(days=1)
    return dt


def relative_path(root: Path, name: str) -> Path:
    if not isinstance(name, str) or not name or "\\" in name or ":" in name:
        raise IngestionError("unsafe_relative_path")
    p = PurePosixPath(name)
    if p.is_absolute() or ".." in p.parts:
        raise IngestionError("unsafe_relative_path")
    target = (root / name).resolve()
    if not target.is_relative_to(root.resolve()):
        raise IngestionError("path_outside_data_root")
    return target


@dataclass(frozen=True)
class JobConfig:
    config_version: int = 1
    mode: str = "import"
    kind: str = "posts"
    source: str = "autohome"
    start: str = ""
    end: str = ""
    series_id: str = ""
    max_requests: int = 0
    max_pages: int = 20
    workers: int = 1
    rps: float = 1.0
    timeout_seconds: float = 20
    max_attempts: int = 3
    allow_network: bool = False
    profile_refresh_after_hours: int = 168
    overlap_days: int = 2

    @classmethod
    def parse(cls, data: dict):
        if not isinstance(data, dict) or set(data) - set(cls.__dataclass_fields__):
            raise IngestionError("unknown_configuration_field")
        try:
            c = cls(**data)
        except TypeError:
            raise IngestionError("invalid_configuration") from None
        if type(c.config_version) is not int or c.config_version != 1:
            raise IngestionError("unknown_configuration_version")
        if c.source != "autohome" or c.mode not in {"import", "replay", "collect"}:
            raise IngestionError("unsupported_mode_or_source")
        if c.kind not in {"posts", "users", "series", "models", "parameters", "product_json"}:
            raise IngestionError("unsupported_kind")
        for name, low, high in [("max_requests", 0, 10000), ("max_pages", 1, 1000),
                                ("workers", 1, 16), ("max_attempts", 1, 5),
                                ("profile_refresh_after_hours", 1, 8760), ("overlap_days", 0, 365)]:
            value = getattr(c, name)
            if type(value) is not int or not low <= value <= high:
                raise IngestionError("invalid_" + name)
        for name, low, high in [("rps", 0.1, 5), ("timeout_seconds", 1, 120)]:
            value = getattr(c, name)
            if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
                raise IngestionError("invalid_" + name)
        if type(c.allow_network) is not bool:
            raise IngestionError("invalid_network_flag")
        if not all(isinstance(v, str) for v in [c.start, c.end, c.series_id]):
            raise IngestionError("invalid_string_field")
        if c.series_id and not c.series_id.isdigit():
            raise IngestionError("invalid_series_id")
        start, end = date_boundary(c.start), date_boundary(c.end, end=True)
        if start and end and start >= end:
            raise IngestionError("invalid_time_range")
        if c.mode == "collect" and (not c.allow_network or c.max_requests < 1):
            raise IngestionError("network_not_authorized")
        if c.mode == "collect" and c.kind in {"parameters", "product_json"} and not c.series_id:
            raise IngestionError("series_id_required")
        return c

    def public(self):
        return dict(self.__dict__)


@dataclass
class Record:
    kind: str
    source_id: str
    data: dict
    locator: str
    issues: list[str] = field(default_factory=list)
    rejected: bool = False
    parser_version: str = "legacy-4"
    audit: dict = field(default_factory=dict)

    @property
    def quality_state(self):
        return "rejected" if self.rejected else ("review_required" if self.issues else "ready")
