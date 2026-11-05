"""确定性事件聚类（task 2.6，ADR-9）。

单遍聚类：候选按日期排序（缺失排最后），与既有簇代表比较；
"日期邻近（±window 天）AND 余弦 ≥ 阈值"才合并。不用 LLM 做分组决策。
"""
from __future__ import annotations

from datetime import date


def _date_close(d1: str | None, d2: str | None, window_days: int) -> bool:
    if d1 is None or d2 is None:
        return True  # 缺失日期不参与日期约束（由更高相似度阈值把关）
    delta = abs((date.fromisoformat(d2) - date.fromisoformat(d1)).days)
    return delta <= window_days


def cluster_candidates(items: list[dict], vectors: list[list[float]],
                       cos_threshold: float, date_window_days: int,
                       missing_date_penalty: float = 0.05) -> list[list[int]]:
    """返回簇列表（每簇为 items 的下标列表）。确定性：同输入同输出。"""
    order = sorted(range(len(items)),
                   key=lambda i: (items[i].get("date") is None, items[i].get("date") or ""))
    clusters: list[dict] = []  # {"sum": 累加向量, "n": 簇大小, "date": 代表日期, "members": [idx]}

    for idx in order:
        vec = vectors[idx]
        it = items[idx]
        best_j, best_sim = None, 0.0
        for j, c in enumerate(clusters):
            if not _date_close(it.get("date"), c["date"], date_window_days):
                continue
            rep = [s / c["n"] for s in c["sum"]]
            sim = _cos(rep, vec)
            need = cos_threshold + (missing_date_penalty if it.get("date") is None else 0.0)
            if sim >= need and sim > best_sim:
                best_j, best_sim = j, sim
        if best_j is None:
            clusters.append({"sum": list(vec), "n": 1, "date": it.get("date"), "members": [idx]})
        else:
            c = clusters[best_j]
            c["sum"] = [a + b for a, b in zip(c["sum"], vec)]
            c["n"] += 1
            c["members"].append(idx)
            if it.get("date") and c["date"] and it["date"] < c["date"]:
                c["date"] = it["date"]  # 簇代表日期取最早

    # 输出按簇内最早事件日期排序，保证确定性
    clusters.sort(key=lambda c: (c["date"] is None, c["date"] or ""))
    return [list(c["members"]) for c in clusters]


def _cos(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    na = sum(x * x for x in a) ** 0.5 or 1.0
    nb = sum(x * x for x in b) ** 0.5 or 1.0
    return sum(x * y for x, y in zip(a, b)) / (na * nb)
