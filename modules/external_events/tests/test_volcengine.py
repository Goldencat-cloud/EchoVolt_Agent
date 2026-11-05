import httpx
import pytest

from mcp_server import core
from mcp_server.volcengine import VolcengineClient, VolcengineConfigError


def response(monkeypatch, body, status=200):
    captured = {}
    def post(url, **kwargs):
        captured.update(url=url, **kwargs)
        return httpx.Response(status, json=body)
    monkeypatch.setattr(httpx, "post", post)
    return captured


def test_request_and_normalization(monkeypatch):
    captured = response(monkeypatch, {"ResponseMetadata": {"RequestId": "req"}, "Result": {
        "WebResults": [{"Title": "title", "Url": "https://A.com/item", "Content": "body",
                        "PublishTime": "2025-05-30T19:35:24+08:00", "AuthInfoLevel": 1,
                        "RankScore": 0.9}]}})
    out = VolcengineClient(api_key="test", interval=0).search("q", include_domains=["a.com"],
                                                            time_range="2025-01-01..2025-12-31")
    assert captured["headers"]["Authorization"] == "Bearer test"
    assert "api_key" not in captured["json"]
    assert captured["json"]["SearchType"] == "web"
    assert captured["json"]["Filter"]["Sites"] == "a.com"
    assert captured["json"]["TimeRange"] == "2025-01-01..2025-12-31"
    assert out["request_id"] == "req"
    assert out["results"][0]["domain"] == "a.com"
    assert out["results"][0]["content_kind"] == "body"
    assert core.normalize_date(out["results"][0]["published_date"]) == ("2025-05-30", "day", False)


def test_summary_not_used_as_source(monkeypatch):
    response(monkeypatch, {"Result": {"WebResults": [{"Url": "https://a.com", "Content": None,
                               "Snippet": "source slice", "Summary": "model summary"}]}})
    item = VolcengineClient(api_key="test", interval=0).search("q")["results"][0]
    assert item["content"] == "source slice" and item["content_kind"] == "snippet"
    assert item["published_date"] is None


@pytest.mark.parametrize("status", [401, 403])
def test_http_auth_failure(monkeypatch, status):
    response(monkeypatch, {}, status)
    with pytest.raises(VolcengineConfigError):
        VolcengineClient(api_key="test", interval=0).search("q")


@pytest.mark.parametrize("body", [{}, {"Result": {}}, {"Result": {"WebResults": "bad"}},
                                      {"ResponseMetadata": {"Error": {"Code": "QuotaExceeded"}}}])
def test_malformed_or_business_error(monkeypatch, body):
    response(monkeypatch, body)
    assert not VolcengineClient(api_key="test", interval=0).search("q")["ok"]


def test_empty_success(monkeypatch):
    response(monkeypatch, {"Result": {"ResultCount": 0, "WebResults": None}})
    result = VolcengineClient(api_key="test", interval=0).search("q")
    assert result["ok"] and result["results"] == []


def test_rate_limit_no_secret_echo(monkeypatch):
    response(monkeypatch, {"secret": "test"}, 429)
    result = VolcengineClient(api_key="test", interval=0).search("q")
    assert result["error_code"] == "http_429" and "test" not in result["error"]


def test_api_auth_failure(monkeypatch):
    response(monkeypatch, {"ResponseMetadata": {"Error": {"Code": "AccessDenied"}}})
    with pytest.raises(VolcengineConfigError):
        VolcengineClient(api_key="test", interval=0).search("q")


@pytest.mark.parametrize("raw,expected", [("2025-05-30", ("2025-05-30", "day", False)),
    ("2025年11月", ("2025-11-01", "month", False)), ("2025年", ("2025-01-01", "year", False)),
    ("2025-02-30", (None, "unknown", True)), (None, (None, "unknown", True))])
def test_date_precision(raw, expected):
    assert core.normalize_date(raw) == expected


def test_all_queries_failed_is_not_empty_success():
    class Failed:
        def search(self, *args, **kwargs):
            return {"ok": False, "results": [], "error": "failed"}
    result = core.run("a", "b", aspects=["tech"], client=Failed(),
                      rewriter=lambda groups: [])
    assert result["meta"]["status"] == "search_error"
    assert all(x["error"] == "failed" for x in result["meta"]["query_stats"])


def test_request_pacing(monkeypatch):
    import mcp_server.volcengine as module
    clock = [0.0]
    starts = []
    monkeypatch.setattr(module.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(module.time, "sleep", lambda delay: clock.__setitem__(0, clock[0] + delay))
    def post(*args, **kwargs):
        starts.append(clock[0])
        return httpx.Response(200, json={"Result": {"ResultCount": 0}})
    monkeypatch.setattr(httpx, "post", post)
    client = VolcengineClient(api_key="test", interval=0.65)
    for _ in range(3):
        client.search("q")
    assert starts == pytest.approx([0, 0.65, 1.3])


@pytest.mark.parametrize("kwargs", [{"query": ""}, {"query": "x" * 101},
    {"query": "q", "max_results": 51}, {"query": "q", "max_results": True},
    {"query": "q", "time_range": "2026-02-30..2026-03-01"},
    {"query": "q", "time_range": "2026-03-01..2026-02-01"},
    {"query": "q", "include_domains": ["https://a.com"]}])
def test_invalid_request_rejected_before_http(monkeypatch, kwargs):
    def forbidden(*args, **kwargs):
        pytest.fail("非法输入不应发出HTTP请求")
    monkeypatch.setattr(httpx, "post", forbidden)
    with pytest.raises(ValueError):
        VolcengineClient(api_key="test", interval=0).search(**kwargs)
