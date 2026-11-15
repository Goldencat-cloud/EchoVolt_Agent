# -*- coding: utf-8 -*-
"""① 废串命中的帖子全文（评估整帖排除是否误删）
   ② r3 阈值敏感性分析（gap × post_count 网格 + 2024-03/04 上市潮占比）"""
import json
import re
import sqlite3
import sys
from collections import Counter
from datetime import date, datetime
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from corpus_cleaning import contracts as C

DB = Path(__file__).resolve().parents[2] / "data" / "stock" / "db" / "ingestion.sqlite3"
conn = sqlite3.connect(str(DB))
conn.row_factory = sqlite3.Row

print("========== ① 废串命中全量（excluded=system_junk） ==========")
for r in conn.execute("""
  SELECT a.post_id, p.body_text, p.title FROM cleaning_annotations a
  JOIN posts p ON p.post_id = a.post_id WHERE a.excluded='system_junk'
"""):
    print(f"\n[{r['post_id']}] title={r['title']}")
    print(f"  正文({len(r['body_text'] or '')}字): {(r['body_text'] or '')[:300]}")

print("\n========== ①b 正文含废串词但未标 junk 的（对照，看规则边界） ==========")
n = 0
for r in conn.execute("SELECT post_id, body_text FROM posts"):
    body = r["body_text"] or ""
    if C.JUNK.search(body):
        hit, _ = None, None
        # 是否被标为 junk（查标注）
        marked = conn.execute("SELECT excluded FROM cleaning_annotations WHERE post_id=?",
                              (r["post_id"],)).fetchone()[0]
        if marked != "system_junk":
            n += 1
            if n <= 5:
                print(f"[{r['post_id']}] excluded={marked!r} 正文: {body[:150]}")
print(f"（含废串词但未被标 system_junk 的共 {n} 条）")

print("\n========== ② r3 阈值敏感性 ==========")
FMT = ("%Y-%m-%d", "%Y/%m/%d")


def pd_(s):
    if not s:
        return None
    for f in FMT:
        try:
            return datetime.strptime(str(s).strip()[:10], f).date()
        except ValueError:
            pass
    return None


rows = conn.execute("""
  SELECT a.post_id, a.spam_reasons_json, p.published_at
  FROM cleaning_annotations a JOIN posts p ON p.post_id = a.post_id
  WHERE a.spam_reasons_json LIKE '%r3_new_account_burst%'
""").fetchall()
grid = Counter()
launch = Counter()
for r in rows:
    reasons = json.loads(r["spam_reasons_json"])["r3_new_account_burst"]
    gap, cnt = reasons["gap_days"], reasons["platform_post_count"]
    mon = r["published_at"][:7]
    is_launch = mon in ("2024-03", "2024-04")
    for g_max in (3, 7, 14, 30):
        for c_max in (1, 2, 3, 5):
            if gap <= g_max and cnt <= c_max:
                grid[(g_max, c_max)] += 1
                if is_launch:
                    launch[(g_max, c_max)] += 1
print("当前规则 gap≤30 且 cnt≤5 命中:", len(rows))
print("阈值网格 (gap_max, cnt_max): 总命中 / 其中2024-03~04上市潮")
for g_max in (3, 7, 14, 30):
    line = []
    for c_max in (1, 2, 3, 5):
        line.append(f"c≤{c_max}: {grid[(g_max, c_max)]}/{launch[(g_max, c_max)]}")
    print(f"  g≤{g_max}: " + "  ".join(line))
conn.close()
