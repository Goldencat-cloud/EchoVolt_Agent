"""LLM 忠实改写与校验回退（task 2.7，ADR-10）。

兼容 OpenAI 的 chat 端点（temperature 0）。prompt 约束：仅使用簇内来源事实，
不评价、不推测。输出经校验（JSON 合法、摘要非空 ≤150 字）；失败或不可用 →
调用方回退最优来源原句。LLM 不可用不抛出致命错误，由 core 降级。
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

MAX_SUMMARY_LEN = 150
VALID_TYPES = {"product", "competitor", "policy", "tech", "public_opinion", "other"}


class LLMUnavailable(Exception):
    pass


def _cfg() -> tuple[str, str, str]:
    key = os.getenv("OPENAI_API_KEY")
    base = (os.getenv("OPENAI_BASE_URL") or "").rstrip("/")
    model = os.getenv("AGENT_MODEL")
    if not (key and base and model):
        raise LLMUnavailable("配置缺失: OPENAI_API_KEY/OPENAI_BASE_URL/AGENT_MODEL")
    return key, base, model


def _chat(messages: list[dict], timeout: float = 90.0) -> str:
    key, base, model = _cfg()
    try:
        resp = httpx.post(
            f"{base}/chat/completions",
            json={"model": model, "messages": messages, "temperature": 0},
            headers={"Authorization": f"Bearer {key}"},
            timeout=timeout, trust_env=False,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]
    except (httpx.HTTPError, KeyError, ValueError) as e:
        raise LLMUnavailable(f"LLM 调用失败: {e}") from e


_SYSTEM = (
    "你是严谨的事实编辑。每组包含聚到同一事件的若干候选来源报道，其中可能混入无关或噪声条目。"
    "对每组输出一个严格 JSON 对象，完成两件事："
    "\n1) 逐条判定成员去留 member_verdicts：[{\"id\":成员序号,\"ignore\":布尔,\"note\":\"≤8字忽略理由\"}]。"
    "成员级 ignore 标准（任一命中即忽略该条，逐条独立判定）："
    "\n· 与该事件/品牌产品无关；"
    "\n· 盘点/榜单/年度回顾等仅顺带提及本产品（本产品不是报道主角）；"
    "\n· 旧闻翻新（报道日期明显晚于事件实际时间，或重复发布旧事件）；"
    "\n· 品牌生态周边、联名/游戏等衍生话题（非本品本身）；"
    "\n· 营销软文或无信息量凑数内容。"
    "\n2) 仅基于【未被忽略】成员的来源事实，合成事件："
    "{\"ignore\": 整组均无有效成员时为 true 否则 false, "
    "\"title\": \"≤25字归一标题\", \"summary\": \"≤100字客观陈述，不评价、不推测、不用形容词堆砌\", "
    "\"event_type\": \"product|competitor|policy|tech|public_opinion|other\", "
    "\"subtype\": \"简短细类标签\", \"relevance\": \"core|context\"}。"
    "\nsummary 中的事实必须能在保留成员的来源里找到依据；来源矛盾时以更权威、更新日期者为准。"
    "输出严格 JSON 数组，每项按 idx 对应："
    "[{\"idx\":组序号,\"member_verdicts\":[...],\"ignore\":...,\"title\":...,\"summary\":...,"
    "\"event_type\":...,\"subtype\":...,\"relevance\":...}]，只输出 JSON。"
)


def rewrite_clusters(clusters: list[list[dict]], batch_size: int = 6) -> list[dict | None]:
    """对每个簇生成改写结果；失败项为 None（调用方回退）。与输入簇一一对应。"""
    results: list[dict | None] = []
    for start in range(0, len(clusters), batch_size):
        batch = clusters[start:start + batch_size]
        facts = []
        for gi, members in enumerate(batch):
            items = []
            for m in members[:6]:
                items.append({"date": m.get("date"), "domain": m["domain"],
                              "tier": m["tier"],
                              "text": f"{m['title']}——{(m['content'] or '')[:150]}"})
            facts.append({"idx": gi, "sources": items})
        try:
            content = _chat([{"role": "system", "content": _SYSTEM},
                             {"role": "user", "content": json.dumps(facts, ensure_ascii=False)}])
            arr = json.loads(_strip_json(content))
            by_idx = {a.get("idx"): a for a in arr if isinstance(a, dict)}
        except (LLMUnavailable, json.JSONDecodeError, AttributeError, TypeError):
            raise
        for gi, members in enumerate(batch):
            a = by_idx.get(gi)
            if not (isinstance(a, dict) and isinstance(a.get("summary"), str)):
                results.append(None)
                continue
            if a.get("ignore"):
                results.append(a)  # ignore 判定原样上交，由 core 计数丢弃
                continue
            ok = (a["summary"].strip() and len(a["summary"]) <= MAX_SUMMARY_LEN
                  and a.get("event_type") in VALID_TYPES)
            results.append(a if ok else None)
    return results


def _strip_json(s: str) -> str:
    s = s.strip()
    if s.startswith("```"):
        s = s.strip("`")
        s = s[s.index("\n"):] if "\n" in s else s
    return s[s.index("["):s.rindex("]") + 1] if "[" in s and "]" in s else s
