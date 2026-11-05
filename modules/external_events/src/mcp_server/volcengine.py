"""火山引擎 Web Search：API Key REST 接入及内部结果归一化。"""
from __future__ import annotations

import os
import threading
import time
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

import httpx
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env")
DEFAULT_API_URL = "https://open.feedcoopapi.com/search_api/web_search"


class VolcengineConfigError(Exception):
    """配置缺失、鉴权失败或访问权限不足。"""


class VolcengineClient:
    provider = "volcengine"

    def __init__(self, api_key=None, api_url=None, interval=None):
        self.api_key = api_key or os.getenv("VOLCENGINE_SEARCH_API_KEY") or os.getenv("ASK_ECHO_SEARCH_INFINITY_API_KEY")
        if not self.api_key:
            raise VolcengineConfigError("配置缺失: VOLCENGINE_SEARCH_API_KEY（或 ASK_ECHO_SEARCH_INFINITY_API_KEY）未设置")
        self.api_url = api_url or os.getenv("VOLCENGINE_SEARCH_API_URL") or DEFAULT_API_URL
        parsed = urlparse(self.api_url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise VolcengineConfigError("VOLCENGINE_SEARCH_API_URL 必须是无内嵌凭据的 HTTPS API 地址")
        self.interval = float(interval if interval is not None else os.getenv("VOLCENGINE_SEARCH_INTERVAL", "0.65"))
        if self.interval < 0:
            raise VolcengineConfigError("VOLCENGINE_SEARCH_INTERVAL 不能小于0")
        self._lock = threading.Lock()
        self._next = 0.0

    def _pace(self):
        # 同一调研共享一个客户端，避免线程并发突发超过默认 QPM/QPS。
        with self._lock:
            delay = self._next - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            self._next = time.monotonic() + self.interval

    def search(self, query, max_results=8, include_domains=None,
               timeout=30.0, time_range=None):
        query = query.strip()
        if not 1 <= len(query) <= 100:
            raise ValueError("搜索词必须为1至100个字符")
        if isinstance(max_results, bool) or not isinstance(max_results, int) or not 1 <= max_results <= 50:
            raise ValueError("max_results 必须为1至50的整数")
        filters = {"NeedUrl": True, "NeedContent": False}
        if include_domains:
            if len(include_domains) > 5 or any(not d or any(c in d for c in '/|:') for d in include_domains):
                raise ValueError("include_domains 须为最多5个完整域名")
            filters["Sites"] = "|".join(include_domains)
        payload = {"Query": query, "SearchType": "web", "Count": max_results,
                   "Filter": filters, "NeedSummary": False}
        if time_range:
            start, end = time_range.split("..")
            if date.fromisoformat(start) > date.fromisoformat(end):
                raise ValueError("时间窗起点不能晚于终点")
            payload["TimeRange"] = time_range
        self._pace()
        try:
            resp = httpx.post(self.api_url, json=payload,
                              headers={"Authorization": f"Bearer {self.api_key}"},
                              timeout=timeout, trust_env=False)
        except httpx.HTTPError:
            return self._failed("network_error", "搜索请求失败；检查网络与端点")
        if resp.status_code in (401, 403):
            raise VolcengineConfigError(f"鉴权/权限失败({resp.status_code})：检查火山引擎搜索 API Key 与服务权限")
        if resp.status_code != 200:
            return self._failed(f"http_{resp.status_code}", f"搜索服务 HTTP {resp.status_code}")
        try:
            data = resp.json()
            metadata = data.get("ResponseMetadata", {})
            error = metadata.get("Error")
            if error:
                code = str(error.get("Code", "api_error"))
                if any(s in code.lower() for s in ("auth", "accessdenied", "invalidapikey", "unauthorized")):
                    raise VolcengineConfigError("火山引擎搜索鉴权/权限失败")
                return self._failed(code, "搜索 API 返回业务错误")
            result = data["Result"]
            items = result.get("WebResults")
            if items is None and result.get("ResultCount") == 0:
                items = []
            if not isinstance(items, list):
                raise ValueError("缺少 WebResults")
            normalized = []
            for item in items:
                url = item.get("Url") or ""
                parsed = urlparse(url)
                if parsed.scheme not in ("http", "https") or not parsed.hostname:
                    continue
                # Summary 是模型生成的摘要，不作为原文证据；正文缺失时使用普通切片。
                content = item.get("Content") or item.get("Snippet") or ""
                normalized.append({"title": item.get("Title") or "", "url": url,
                    "content": content, "content_kind": "body" if item.get("Content") else "snippet",
                    "published_date": item.get("PublishTime"), "domain": parsed.hostname.lower(),
                    "provider": self.provider, "provider_rank_score": item.get("RankScore"),
                    "provider_auth_level": item.get("AuthInfoLevel")})
            return {"ok": True, "results": normalized, "error": None,
                    "request_id": metadata.get("RequestId") or result.get("LogId")}
        except (ValueError, TypeError, KeyError, AttributeError):
            return self._failed("invalid_response", "搜索 API 返回非法 JSON 或结构")

    @staticmethod
    def _failed(code, message):
        # 不回显响应正文或异常对象，避免供应商错误意外包含凭据。
        return {"ok": False, "results": [], "error": message, "error_code": code}
