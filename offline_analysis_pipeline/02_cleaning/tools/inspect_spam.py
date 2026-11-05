# -*- coding: utf-8 -*-
"""人工抽查 spam_suspect=1 的帖子：按规则抽样打印原文与作者信息。"""
import json
import sqlite3
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
DB = Path(__file__).resolve().parents[2] / "data" / "stock" / "db" / "ingestion.sqlite3"
conn = sqlite3.connect(str(DB))
conn.row_factory = sqlite3.Row

rows = conn.execute("""
  SELECT a.post_id, a.spam_reasons_json, a.norm_key, a.excluded, p.body_text, p.title,
         p.published_at, p.author_nickname, p.author_id
  FROM cleaning_annotations a JOIN posts p ON p.post_id = a.post_id
  WHERE a.spam_suspect = 1
""").fetchall()

by_rule = {}
for r in rows:
    reasons = json.loads(r["spam_reasons_json"])
    for k in reasons:
        if k.startswith("r"):
            by_rule.setdefault(k, []).append((r, reasons))

print("spam_suspect=1 总数:", len(rows))
for k, items in sorted(by_rule.items()):
    print(f"\n===== {k}: {len(items)} 帖 =====")
    for r, reasons in items[:8]:
        body = (r["body_text"] or "").replace("\n", " ")[:80]
        print(f"[{r['post_id']}] @{r['author_nickname']} ({r['published_at'][:10]}) ex={r['excluded']!r}")
        print(f"   正文: {body}")
        print(f"   依据: {json.dumps(reasons[k], ensure_ascii=False)[:160]}")

# r2 的 norm_key 分布：是否多为短句
r2 = [json.loads(r["spam_reasons_json"])["r2_cross_author_key"]["norm_key_sample"] for r, _ in by_rule.get("r2_cross_author_key", [])]
from collections import Counter
lens = Counter(len(k) for k in r2)
print("\nr2 norm_key 长度分布:", dict(sorted(lens.items())))
print("r2 高频文本 top8:")
for k, n in Counter(r2).most_common(8):
    print(f"  x{n}: {k[:60]}")

# r3 与发布时间分布
r3_pub = [r["published_at"][:7] for r, _ in by_rule.get("r3_new_account_burst", [])]
print("\nr3 发帖月份分布:", dict(Counter(r3_pub).most_common()))
conn.close()
