"""volcengine-mcp-research-tool v2 单元测试（tasks 2.1/2.2/2.3/2.5/2.6/2.7/2.8 验收用例）。

全部离线：httpx / 检索 / 向量 / LLM 均用 mock 或 fake。
运行：工具根目录 `python -m pytest tests -q`（src 由 tests/conftest.py 自动加入 sys.path）。
"""
from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from mcp_server import cluster as cluster_mod
from mcp_server import core, rules as rules_mod, storage, textvec
from mcp_server.volcengine import VolcengineClient, VolcengineConfigError

RULES = rules_mod.load_rules()
TOKENS = rules_mod.brand_tokens("小米", "SU7")


def R(title, url, domain, content="内容", published="Mon, 16 Mar 2026 00:00:00 GMT"):
    return {"title": title, "url": url, "content": content,
            "published_date": published, "domain": domain}


def ok(results):
    return {"ok": True, "results": results, "error": None}


class FakeClient:
    def __init__(self, routes: dict[str, list] | None = None, fail_on: str | None = None):
        self.routes = routes or {}
        self.fail_on = fail_on
        self.queries: list[str] = []

    def search(self, query, topic="news", max_results=8, include_domains=None, timeout=30.0, time_range=None):
        self.queries.append(query)
        if self.fail_on and self.fail_on in query:
            return {"ok": False, "results": [], "error": "boom"}
        for sub, results in self.routes.items():
            if sub in query:
                return ok(list(results))
        return ok([])


class FakeEmbedder:
    """按文本前缀路由固定向量；未命中给正交零向量。"""

    def __init__(self, routes: dict[str, list[float]] | None = None):
        self.routes = routes or {}

    def embed(self, texts: list[str]) -> list[list[float]]:
        out = []
        for t in texts:
            v = [0.0] * 4
            hit = False
            for sub, rv in self.routes.items():
                if sub in t:
                    v = list(rv)
                    hit = True
                    break
            if not hit:
                v = [1.0, 0.0, 0.0, 0.0]  # 缺省向量彼此相同
            out.append(v)
        return out


def llm_ok(clusters):
    out = []
    for gi, members in enumerate(clusters):
        out.append({"idx": gi, "ignore": False,
                    "title": members[0]["title"][:25],
                    "summary": f"客观陈述：{members[0]['title']}"[:100],
                    "event_type": "product", "subtype": "launch", "relevance": "core"})
    return out


# ---------- task 2.1 规则模块（v2 启发式） ----------

def test_tier_gov_tld_t1():
    assert rules_mod.tier_of("www.samr.gov.cn", RULES) == "T1"


def test_tier_official_param_t1():
    assert rules_mod.tier_of("www.xiaomi.com", RULES,
                             official=frozenset({"www.xiaomi.com"})) == "T1"


def test_tier_t2_list_and_subdomain():
    assert rules_mod.tier_of("jiemian.com", RULES) == "T2"
    assert rules_mod.tier_of("m.autohome.com.cn", RULES) == "T2"


def test_tier_miss_is_t3():
    assert rules_mod.tier_of("example-blog.com", RULES) == "T3"


def test_learn_official_by_product_token():
    assert rules_mod.learn_official("event.xiaomi-su7.cn", "SU7")
    assert not rules_mod.learn_official("example.com", "小米")


def test_noise_blacklist():
    assert rules_mod.noise_reason("任意", "任意", "mp.ofweek.com", RULES,
                                  TOKENS, strict=True) == "blacklist_domain"


def test_noise_strict_off_topic_only_for_given_flag():
    assert rules_mod.noise_reason("今天天气不错", "外出", "a.com", RULES,
                                  TOKENS, strict=True) == "off_topic"
    assert rules_mod.noise_reason("今天天气不错", "外出", "a.com", RULES,
                                  TOKENS, strict=False) is None


def test_brand_tokens_derived_from_params():
    assert "小米" in TOKENS and "SU7" in TOKENS and "小米SU7" in TOKENS


# ---------- task 2.2 火山引擎客户端 ----------

def test_client_success(monkeypatch):
    class Resp:
        status_code = 200

        def json(self):
            return {"Result": {"WebResults": [{"Title": "t", "Url": "https://www.xiaomi.com/a",
                                 "Content": "c", "PublishTime": "2026-03-16"}]}}

    monkeypatch.setattr(httpx, "post", lambda *a, **k: Resp())
    out = VolcengineClient(api_key="k").search("q")
    assert out["ok"] and out["results"][0]["domain"] == "www.xiaomi.com"


def test_client_failure_tolerated(monkeypatch):
    def boom(*a, **k):
        raise httpx.ConnectError("net down")

    monkeypatch.setattr(httpx, "post", boom)
    out = VolcengineClient(api_key="k").search("q")
    assert out["ok"] is False and out["results"] == []


def test_client_missing_key_raises(monkeypatch):
    monkeypatch.delenv("VOLCENGINE_SEARCH_API_KEY", raising=False)
    monkeypatch.delenv("ASK_ECHO_SEARCH_INFINITY_API_KEY", raising=False)
    with pytest.raises(VolcengineConfigError, match="VOLCENGINE_SEARCH_API_KEY"):
        VolcengineClient()


# ---------- task 2.6 向量化与聚类 ----------

def test_ngram_cosine_same_event_higher():
    a = textvec._ngram_vector("小米SU7召回116887辆标准版")
    b = textvec._ngram_vector("小米SU7召回超11万辆标准版电动汽车")
    c = textvec._ngram_vector("周杰伦演唱会门票开售")
    assert textvec.cosine(a, b) > textvec.cosine(a, c)


def test_cluster_merges_same_event_multi_source():
    items = [{"date": "2026-03-16"}, {"date": "2026-03-17"}, {"date": "2026-03-18"}]
    vec = [1.0, 1.0, 0.0, 0.0]
    groups = cluster_mod.cluster_candidates(items, [vec] * 3, 0.55, 3)
    assert len(groups) == 1 and len(groups[0]) == 3


def test_cluster_threshold_blocks_merge():
    items = [{"date": "2026-03-16"}, {"date": "2026-03-16"}]
    groups = cluster_mod.cluster_candidates(
        items, [[1.0, 0, 0, 0], [0, 1.0, 0, 0]], 0.55, 3)
    assert len(groups) == 2


def test_cluster_date_window_blocks_merge():
    items = [{"date": "2026-03-01"}, {"date": "2026-03-20"}]
    vec = [1.0, 1.0, 0.0, 0.0]
    groups = cluster_mod.cluster_candidates(items, [vec, vec], 0.55, 3)
    assert len(groups) == 2


def test_cluster_deterministic():
    items = [{"date": "2026-03-16"}, {"date": "2026-03-17"}]
    vec = [1.0, 1.0, 0.0, 0.0]
    g1 = cluster_mod.cluster_candidates(items, [vec, vec], 0.55, 3)
    g2 = cluster_mod.cluster_candidates(items, [vec, vec], 0.55, 3)
    assert g1 == g2


# ---------- task 2.3/2.8 编排（v2 全链路） ----------

def test_queries_overview_and_year_slicing():
    queries = core.build_queries("小米", "SU7", ["product"], "2024-06-01", "2026-10-03", "汽车")
    aspects_q = [q for q in queries if q["aspect"] == "product"]
    overview_q = [q for q in queries if q["aspect"] == "overview"]
    assert len(overview_q) == 3 and all("汽车" in q["query"] for q in overview_q)
    assert len(aspects_q) == 4 * 3  # 4 模板 × 3 年
    assert all(q["query"].rstrip().endswith(("2024", "2025", "2026")) for q in aspects_q)


def test_full_pipeline_schema_v2():
    routes = {"上市": [R("小米SU7 正式上市", "https://a.com/1", "a.com", published="2025-06-01"),
                       R("小米SU7 上市发布会", "https://b.com/1", "b.com", published="2025-06-02")]}
    tl = core.run("小米", "SU7", ["product"], time_from="2025-01-01", time_to="2025-12-31",
                  client=FakeClient(routes), rules=RULES,
                  vectorizer=FakeEmbedder({"上市": [1.0, 1.0, 0, 0]}),
                  rewriter=llm_ok)
    assert tl["schema_version"] == 3 and tl["meta"]["llm_used"] is True
    assert len(tl["events"]) == 1  # 两篇报道聚合为一个事件
    e = tl["events"][0]
    assert e["media_coverage"]["source_count"] == 2 and e["media_coverage"]["level"] == "low"
    assert e["authority"] == 60  # 单T3有日期50 + 双域名印证10
    assert len(e["sources"]) == 2
    assert all(set(s) == {"source_domain", "source_tier", "confidence", "url",
                          "published_date", "title"}
               for s in e["sources"])
    assert tl["meta"]["filter_stats"]["fallback"] == 0


def test_influence_levels():
    assert core._media_coverage({f"d{i}" for i in range(12)}, ["T1"])["level"] == "high"
    assert core._media_coverage({"a", "b", "c"}, ["T2"])["level"] == "medium"
    assert core._media_coverage({"a"}, ["T3"])["level"] == "low"


def test_confidence_scoring():
    assert rules_mod.confidence_of("www.samr.gov.cn", "T1", RULES,
                                   has_date=True) == 100  # 90+10官方+10日期
    assert rules_mod.confidence_of("www.jiemian.com", "T2", RULES, has_date=True) == 80
    assert rules_mod.confidence_of("example.com", "T3", RULES, has_date=True) == 50
    assert rules_mod.confidence_of("chejiahao.autohome.com.cn", "T2", RULES,
                                   has_date=True) == 40  # 70-40UGC+10日期


def test_low_authority_dropped():
    routes = {"上市": [R("小米SU7 旧闻", "https://chejiahao.autohome.com.cn/1",
                         "chejiahao.autohome.com.cn")]}
    tl = core.run("小米", "SU7", ["product"], client=FakeClient(routes), rules=RULES,
                  vectorizer=FakeEmbedder(), rewriter=llm_ok)
    assert tl["events"] == []
    assert tl["meta"]["filter_stats"]["low_authority_dropped"] == 1


def test_events_sorted_and_fields_complete():
    routes = {"上市": [R("小米SU7 B标题", "https://a.com/2", "a.com", published="2025-06-01"),
                       R("小米SU7 A标题", "https://a.com/1", "a.com", published="2024-01-01"),
                       R("小米SU7 C无日期", "https://a.com/3", "a.com", published=None)]}
    tl = core.run("小米", "SU7", ["product"], client=FakeClient(routes), rules=RULES)
    dates = [e["event_date"] for e in tl["events"]]
    assert dates == sorted(dates, key=lambda d: (d is None, d or ""))
    required = {"event_id", "event_date", "date_precision", "date_missing", "event_type",
                "subtype", "relevance", "title", "summary", "media_coverage",
                "authority", "sources"}
    assert all(required <= set(e) for e in tl["events"])
    assert all(set(s) >= {"source_domain", "source_tier", "confidence", "url",
                          "published_date", "title"}
               for e in tl["events"] for s in e["sources"])


def test_official_domain_promoted_t1():
    routes = {"上市": [R("小米SU7 上市", "https://www.xiaomi.com/1", "www.xiaomi.com")]}
    tl = core.run("小米", "SU7", ["product"], client=FakeClient(routes), rules=RULES,
                  vectorizer=FakeEmbedder(), rewriter=llm_ok, official_domains=["www.xiaomi.com"])
    assert tl["events"][0]["sources"][0]["source_tier"] == "T1"


def test_llm_ignore_drops_cluster():
    def llm_ignore(clusters):
        return [{"idx": gi, "ignore": True} for gi in range(len(clusters))]

    routes = {"竞品": [R("某竞品发布新车", "https://a.com/1", "a.com")]}
    tl = core.run("小米", "SU7", ["competitor"], client=FakeClient(routes), rules=RULES,
                  vectorizer=FakeEmbedder(), rewriter=llm_ignore)
    assert tl["events"] == [] and tl["meta"]["filter_stats"]["llm_ignored"] == 1


def test_llm_member_ignore_keeps_rest():
    """簇内条级去噪：无关条目被逐条忽略，有效条目照常聚成事件。"""
    routes = {"上市": [R("小米SU7 上市发布", "https://a.com/1", "a.com"),
                       R("大亨座驾盘点提及SU7", "https://b.com/1", "b.com")]}

    def llm_partial(clusters):
        out = []
        for gi, members in enumerate(clusters):
            verdicts = [{"id": i, "ignore": "盘点" in m["title"], "note": "盘点点名"}
                        for i, m in enumerate(members)]
            kept = [m for i, m in enumerate(members) if not verdicts[i]["ignore"]]
            out.append({"idx": gi, "member_verdicts": verdicts, "ignore": not kept,
                        "title": kept[0]["title"][:25] if kept else "",
                        "summary": (kept[0].get("content") or "x")[:100] if kept else "",
                        "event_type": "product", "subtype": "launch", "relevance": "core"})
        return out

    tl = core.run("小米", "SU7", ["product"], client=FakeClient(routes), rules=RULES,
                  vectorizer=FakeEmbedder({"上市": [1.0, 1.0, 0, 0]}), rewriter=llm_partial)
    assert len(tl["events"]) == 1
    assert len(tl["events"][0]["sources"]) == 1  # 盘点条目被逐条忽略
    assert tl["meta"]["filter_stats"]["member_ignored"] == 1
    assert tl["events"][0]["sources"][0]["url"] == "https://a.com/1"


def test_llm_fallback_on_failure():
    def llm_boom(clusters):
        raise core.llm_mod.LLMUnavailable("down")

    routes = {"上市": [R("小米SU7 召回计划", "https://a.com/1", "a.com")]}
    tl = core.run("小米", "SU7", ["product"], client=FakeClient(routes), rules=RULES,
                  vectorizer=FakeEmbedder(), rewriter=llm_boom)
    assert tl["meta"]["llm_used"] is False
    assert tl["meta"]["filter_stats"]["fallback"] == 1
    assert tl["events"][0]["subtype"] == "recall"  # 回退走通用关键词映射
    assert tl["events"][0]["summary"]  # 回退用最优来源原句


def test_month_precision_and_window():
    routes = {"上市": [R("小米SU7 上市", "https://a.com/1", "a.com", published="2025年11月"),
                       R("小米SU7 老闻", "https://a.com/2", "a.com",
                         published="Sat, 01 Jun 2024 00:00:00 GMT")]}
    tl = core.run("小米", "SU7", ["product"], time_from="2025-01-01", time_to="2025-12-31",
                  client=FakeClient(routes), rules=RULES,
                  vectorizer=FakeEmbedder({"上市": [1, 1, 0, 0]}), rewriter=llm_ok)
    assert len(tl["events"]) == 1
    assert tl["events"][0]["event_date"] == "2025-11-01"
    assert tl["events"][0]["date_precision"] == "month"
    assert tl["meta"]["filter_stats"]["out_of_window"] == 1


def test_empty_no_fabrication():
    tl = core.run("小米", "SU7", ["product"], client=FakeClient({}), rules=RULES,
                  vectorizer=FakeEmbedder(), rewriter=llm_ok)
    assert tl["meta"]["status"] == "empty" and tl["events"] == []


def test_partial_status():
    routes = {"上市": [R("小米SU7 上市", "https://a.com/1", "a.com")]}
    tl = core.run("小米", "SU7", ["product"], client=FakeClient(routes, fail_on="召回"),
                  rules=RULES, vectorizer=FakeEmbedder(), rewriter=llm_ok)
    assert tl["meta"]["status"] == "partial"


# ---------- task 2.5 落盘 ----------

def test_save_creates_and_overwrites(tmp_path):
    routes = {"上市": [R("小米SU7 上市", "https://a.com/1", "a.com")]}
    tl = core.run("小米", "SU7", ["product"], client=FakeClient(routes), rules=RULES,
                  vectorizer=FakeEmbedder(), rewriter=llm_ok)
    p1 = storage.save_timeline(tl, out_dir=tmp_path)
    assert json.loads(open(p1, encoding="utf-8").read())["schema_version"] == 3
    assert storage.save_timeline(tl, out_dir=tmp_path) == p1
    # txt 可读版同步产出且内容同步
    txt = Path(p1).with_suffix(".txt")
    assert txt.exists()
    body = txt.read_text(encoding="utf-8")
    assert "产品事件时间线" in body and tl["events"][0]["title"] in body
    s = storage.summary(tl, p1)
    assert "events" not in s and s["event_count"] == len(tl["events"])
