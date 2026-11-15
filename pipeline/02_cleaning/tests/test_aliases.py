# -*- coding: utf-8 -*-
"""aliases 单测：对应 spec「产品别名映射」（含向上归一约束、幂等保留人工决定）。"""
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from corpus_cleaning.aliases import (  # noqa: E402
    build_official_variant,
    edit_distance,
    mine_community,
)
from corpus_cleaning.polish import norm_key  # noqa: E402

SPECS = [
    {"spec_id": "76173", "series_id": "6962", "brand_name": "小米汽车",
     "series_name": "小米SU7", "spec_name": "2026款 后驱标准版"},
    {"spec_id": "75668", "series_id": "6962", "brand_name": "小米汽车",
     "series_name": "小米SU7", "spec_name": "2026款 四驱Max版"},
    {"spec_id": "74430", "series_id": "6962", "brand_name": "小米汽车",
     "series_name": "小米SU7", "spec_name": "2024款 SU7 L 猜想图"},
]
T = "2026-10-22T00:00:00+00:00"


class TestOfficialVariant(unittest.TestCase):
    def setUp(self):
        self.rows = build_official_variant(SPECS, T)

    def _find(self, alias):
        key = norm_key(alias)
        return [r for r in self.rows if r["alias_norm"] == key]

    def test_official_spec_level(self):
        r = self._find("2026款 后驱标准版")[0]
        self.assertEqual((r["canonical_spec_id"], r["canonical_series_id"], r["status"]),
                         ("76173", "6962", "confirmed"))
        self.assertEqual(r["canonical_spec_name"], "2026款 后驱标准版")
        self.assertEqual(r["canonical_brand_name"], "小米汽车")

    def test_variant_year_strip_stays_spec_level(self):
        r = self._find("后驱标准版")[0]
        self.assertEqual(r["canonical_spec_id"], "76173")  # 年款不改变粒度

    def test_variant_config_strip_moves_up_to_series(self):
        r = self._find("SU7")[0]
        self.assertEqual((r["canonical_series_id"], r["canonical_spec_id"]), ("6962", None))

    def test_series_and_brand_series_level_only(self):
        for alias in ("小米SU7", "小米汽车", "su7", "su7max", "su7 max", "su7 pro"):
            rs = self._find(alias)
            self.assertTrue(rs, alias)
            self.assertIsNone(rs[0]["canonical_spec_id"], alias)  # 禁止向下到 spec 级
            self.assertEqual(rs[0]["canonical_series_id"], "6962")

    def test_upward_invariant_all_rows(self):
        from corpus_cleaning.aliases import YEAR_PREFIX
        allowed_spec_level = set()
        for s in SPECS:
            allowed_spec_level.add(norm_key(s["spec_name"]))
            allowed_spec_level.add(norm_key(YEAR_PREFIX.sub("", s["spec_name"]).strip()))
        for r in self.rows:
            if r["alias_type"] in ("official", "variant") and r["canonical_spec_id"] is not None:
                # spec 级仅允许：官方全名或仅剥年款（两者都含完整配置语义）
                self.assertIn(norm_key(r["alias_display"]), allowed_spec_level, r["alias_display"])


class TestCommunity(unittest.TestCase):
    def test_matched_not_duplicate_candidate(self):
        corpus = ["小米su7 真香 " * 10, "苏7 不错 " * 10, "无关内容"]
        candidates, stats = mine_community(SPECS, corpus, T)
        keys = {c["alias_norm"] for c in candidates}
        self.assertNotIn(norm_key("su7max"), keys)   # 已有 alias 不重复出候选
        self.assertNotIn(norm_key("小米su7"), keys)  # 已知别名只计入覆盖统计
        self.assertGreater(stats["matched_total_occurrences"], 0)

    def test_candidate_pending_and_upward(self):
        corpus = ["苏7 " * 20, "小米su7 " * 5]
        candidates, stats = mine_community(SPECS, corpus, T)
        su = [c for c in candidates if c["alias_norm"] == norm_key("苏7")]
        if su:  # 编辑距离 ≤2 且 freq≥5 才入候选
            # 模糊候选不预设归属（可能是其他车型），canonical 留空待人工确认
            self.assertEqual((su[0]["status"], su[0]["canonical_series_id"],
                              su[0]["canonical_brand_name"], su[0]["match_method"]),
                             ("pending", None, None, "fuzzy"))
        self.assertIn("pending_candidates", stats)

    def test_low_freq_not_candidate(self):
        _, stats = mine_community(SPECS, ["苏7"], T)
        self.assertEqual(stats["pending_candidates"], 0)

    def test_edit_distance(self):
        self.assertEqual(edit_distance("苏7", "su7"), 2)   # 临界：恰在阈值内 → 入候选
        self.assertGreater(edit_distance("su7max", "su7"), 2)  # 超阈值不入


class TestStoreIdempotent(unittest.TestCase):
    def _init_db(self, path):
        conn = sqlite3.connect(path)
        conn.executescript("""
        CREATE TABLE posts (post_id TEXT PRIMARY KEY, title TEXT, body_text TEXT, clean_text TEXT,
          author_id TEXT, published_at TEXT, source_url TEXT, view_count INTEGER,
          reply_count INTEGER, tags_json TEXT, content_segments_json TEXT NOT NULL DEFAULT '[]',
          author_context_json TEXT NOT NULL DEFAULT '{}');
        CREATE TABLE product_specs (spec_id TEXT PRIMARY KEY, series_id TEXT, spec_name TEXT,
          series_name TEXT, brand_name TEXT);
        """)
        return conn

    def test_rerun_preserves_human_status(self):
        from corpus_cleaning.store import ensure_schema, write_aliases, write_annotations
        from corpus_cleaning.pipeline import run
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
            db = str(Path(td) / "t.sqlite3")
            conn = self._init_db(db)
            for s in SPECS:
                conn.execute("INSERT INTO product_specs VALUES (?,?,?,?,?)",
                             (s["spec_id"], s["series_id"], s["spec_name"], s["series_name"], s["brand_name"]))
            conn.execute("INSERT INTO posts VALUES ('p1','t','正文','正文','a','2026-09-01','https://x/p1',10,2,'[]','[]','{}')")
            conn.commit()
            conn.close()
            stats1 = run(db, cleaning_version="clean-v1")
            self.assertEqual(stats1["posts_total"], 1)
            conn = sqlite3.connect(db)
            # 模拟人工拒绝一个竞品种子
            conn.execute("UPDATE product_aliases SET status='rejected' WHERE alias_type='competitor' AND alias_norm=(SELECT MIN(alias_norm) FROM product_aliases WHERE alias_type='competitor')")
            before = conn.execute("SELECT alias_norm, status FROM product_aliases WHERE status='rejected'").fetchall()
            conn.commit()
            conn.close()
            # 重跑（同版本幂等）
            run(db, cleaning_version="clean-v1")
            conn = sqlite3.connect(db)
            after = conn.execute("SELECT alias_norm, status FROM product_aliases WHERE status='rejected'").fetchall()
            n_ann = conn.execute("SELECT count(*) FROM cleaning_annotations").fetchone()[0]
            n_view = conn.execute("SELECT count(*) FROM v_clean_subset").fetchone()[0]
            conn.close()
            self.assertEqual(before, after)  # 人工拒绝不被重跑覆盖
            self.assertEqual(n_ann, 1)
            self.assertEqual(n_view, 1)  # p1 正文非空且非重复 → 进子集

    def test_write_aliases_never_overwrites(self):
        from corpus_cleaning.store import ensure_schema, write_aliases
        from corpus_cleaning import aliases as AL
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
            db = str(Path(td) / "t.sqlite3")
            conn = self._init_db(db)
            ensure_schema(conn)
            rows = AL.competitor_rows(T)
            write_aliases(conn, rows)
            conn.execute("UPDATE product_aliases SET status='confirmed' WHERE alias_norm=?", (rows[0]["alias_norm"],))
            conn.commit()
            res = write_aliases(conn, rows)  # 重写同批
            conn.commit()
            status = conn.execute("SELECT status FROM product_aliases WHERE alias_norm=?",
                                  (rows[0]["alias_norm"],)).fetchone()[0]
            conn.close()
            self.assertEqual(status, "confirmed")
            # pending 行被整批替换重插；仅人工确认过的 1 行命中 IGNORE
            self.assertEqual(res["ignored_existing"], 1)
            self.assertEqual(res["inserted"], len(rows) - 1)


if __name__ == "__main__":
    unittest.main()
