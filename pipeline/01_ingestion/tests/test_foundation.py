import csv
import io
import json
import socket
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from autoinsight_ingestion.contracts import IngestionError, JobConfig, date_boundary, relative_path
from autoinsight_ingestion.ingest import import_bytes, replay
from autoinsight_ingestion.normalize.basic import clean_text, number, parse_time, post_id
from autoinsight_ingestion.normalize.legacy import parse
from autoinsight_ingestion.storage import Repository


def csv_bytes(rows):
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8-sig")


def post(tid="123", full=None):
    return {"帖子链接": f"https://club.autohome.com.cn/bbs/thread/abc/{tid}-1.html",
            "帖子标题": "相同标题", "正文": "很差 很差！\n后排空间不够", "发布时间": "三天前",
            "全文": json.dumps(full, ensure_ascii=False) if full is not None else "很差 很差！\n后排空间不够",
            "图片链接": '["https://example.invalid/a.webp"]', "作者主页": "https://i.autohome.com.cn/42/home.html"}


class ContractTests(unittest.TestCase):
    def test_config_defaults_offline(self):
        self.assertFalse(JobConfig.parse({}).allow_network)

    def test_invalid_config(self):
        for data in [{"api_key": "test-secret"}, {"config_version": 2}, {"workers": True}, {"rps": float("nan")},
                     {"start": "garbage"}, {"start": "2026-10-22", "end": "2026-10-21"}, {"series_id": "../1"}]:
            with self.subTest(data=data), self.assertRaises(IngestionError):
                JobConfig.parse(data)

    def test_online_requires_permission_budget(self):
        for data in [{"mode": "collect"}, {"mode": "collect", "allow_network": True}]:
            with self.assertRaises(IngestionError):
                JobConfig.parse(data)

    def test_date_end_is_exclusive_next_day(self):
        self.assertEqual((date_boundary("2026-10-21", end=True) - date_boundary("2026-10-21")).days, 1)

    def test_relative_uses_saved_anchor(self):
        result = parse_time("3天前", "2026-10-21T12:00:00+08:00")
        self.assertEqual(result["value"], "2026-10-18")
        self.assertEqual(result["precision"], "day")
        self.assertEqual(result["basis"], "relative_to_retrieval")

    def test_relative_missing_anchor(self):
        self.assertIsNone(parse_time("昨天")["value"])
        self.assertIsNone(parse_time("昨天", "2026-10-21T10:00:00")["value"])

    def test_explicit_date(self):
        self.assertEqual(parse_time("2026/10/03")["value"], "2026-10-03")

    def test_numbers(self):
        self.assertEqual(number("1.2万"), 12000)
        self.assertEqual(number("0"), 0)
        self.assertIsNone(number(""))
        self.assertIsNone(number("未知"))

    def test_preserve_expression(self):
        self.assertEqual(clean_text("差！ 差！\r\n广告?&nbsp;保留"), "差！ 差！\n广告? 保留")

    def test_path_traversal(self):
        with tempfile.TemporaryDirectory() as root:
            for name in ["../x", "C:/x", "/x", "a\\b"]:
                with self.assertRaises(IngestionError):
                    relative_path(Path(root), name)


class LegacyTests(unittest.TestCase):
    def test_ordered_multimodal(self):
        r = list(parse(csv_bytes([post(full=[["text", "甲"], ["img", "https://example.invalid/a.webp"], ["text", "乙"], ["vid", "A60"]])]), "posts"))[0]
        self.assertEqual([s["kind"] for s in r.data["segments"]], ["text", "image", "text", "video"])
        self.assertEqual(r.data["sequence_status"], "ordered")

    def test_unordered_not_fabricated(self):
        r = list(parse(csv_bytes([post()]), "posts"))[0]
        self.assertIn("media_order_unknown", r.issues)
        self.assertIsNone(r.data["time"]["value"])

    def test_missing_id_rejected(self):
        row = post(); row["帖子链接"] = "https://example.invalid/no-id"
        self.assertTrue(list(parse(csv_bytes([row]), "posts"))[0].rejected)

    def test_conflicting_id_rejected(self):
        row = post(); row["post_id"] = "999"
        self.assertTrue(list(parse(csv_bytes([row]), "posts"))[0].rejected)

    def test_user_inference_separate(self):
        row = {"user_id": "42", "sex_raw": "0", "sex_source": "pronoun(他3/她0)", "sex_label": "男", "status": "ok"}
        d = list(parse(csv_bytes([row]), "users"))[0].data
        self.assertIsNone(d["sex_explicit"])
        self.assertEqual(d["sex_inferred"], "男")
        self.assertIsNone(d["followers"])

    def test_parameter_names_do_not_collapse(self):
        rows = [{"specid": "74430", "车型名称": "2024款猜想图", "年款": "2024", "状态": "未售", "配置分组": "参数", "配置分类": cat, "配置项": "尺寸", "配置值": "1"} for cat in ["车身", "轮胎"]]
        r = list(parse(csv_bytes(rows), "parameters", series_id="6962"))[0]
        self.assertTrue(r.data["is_concept"])
        self.assertEqual(len({p["source_item_key"] for p in r.data["parameters"]}), 2)

    def test_empty_csv_invalid(self):
        with self.assertRaises(IngestionError):
            list(parse(b"", "posts"))


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "data"
        self.store = Repository(self.root)

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def load(self, rows=None):
        return import_bytes(self.store, csv_bytes(rows or [post()]), "posts", {"fixture": "posts"}, retrieved_at="2026-10-21T12:00:00+08:00")

    def test_no_network_import(self):
        with patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden")):
            self.load()

    def test_idempotent_import(self):
        self.assertEqual(self.load()["counts"]["inserted"], 1)
        self.assertEqual(self.load()["counts"]["unchanged"], 1)
        self.assertEqual(self.store.verify()["counts"]["posts"], 1)

    def test_same_title_different_ids(self):
        self.load([post("123"), post("124")])
        self.assertEqual(self.store.verify()["counts"]["posts"], 2)

    def test_snapshots_preserved(self):
        self.load(); row = post(); row["正文"] = "修改后的正文"
        self.load([row])
        self.assertEqual(self.store.verify()["counts"]["posts"], 1)
        self.assertEqual(self.store.verify()["counts"]["source_snapshots"], 2)

    def test_replay_uses_saved_input(self):
        r = self.load(); before = self.store.logical_export()
        with patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden")):
            replay(self.store, r["response_id"])
        self.assertEqual(before, self.store.logical_export())

    def test_transaction_failure_recover(self):
        content = csv_bytes([post()])
        run = self.store.begin_run({"kind": "posts"}); task = self.store.task(run, "posts", "x")
        response = self.store.response(task, content, {"fixture": "crash"})
        with self.assertRaises(IngestionError):
            self.store.ingest(run, task, response, parse(content, "posts"), fail_after=1)
        self.assertEqual(self.store.verify()["counts"]["posts"], 0)
        self.assertEqual(self.store.db.execute("SELECT parse_state FROM source_snapshots WHERE snapshot_id=?", (response,)).fetchone()[0], "pending")
        self.store.ingest(run, task, response, parse(content, "posts"))
        self.assertEqual(self.store.verify()["counts"]["posts"], 1)

    def test_lock_rejects_second_process(self):
        script = "from autoinsight_ingestion.storage import Repository; import sys; Repository(sys.argv[1])"
        import os
        env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / "src"))
        r = subprocess.run([sys.executable, "-c", script, str(self.root)], env=env, capture_output=True, text=True)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("data_root_in_use", r.stderr)

    def test_backup_restore_new_path(self):
        self.load(); before = self.store.logical_export()
        backup = Path(self.tmp.name) / "备份 目录"
        self.store.backup(backup)
        restored = Path(self.tmp.name) / "恢复 目录"
        self.assertTrue(Repository.restore(backup, restored)["ok"])
        with Repository(restored) as other:
            self.assertEqual(other.logical_export(), before)
            replay(other, other.db.execute("SELECT snapshot_id FROM source_snapshots LIMIT 1").fetchone()[0])
            self.assertEqual(other.logical_export(), before)
        with self.assertRaises(IngestionError):
            Repository.restore(backup, restored)

    def test_backup_tamper_rejected(self):
        self.load(); backup = Path(self.tmp.name) / "backup"
        self.store.backup(backup)
        blob = next((backup / "raw").rglob("*"))
        blob = next(p for p in (backup / "raw").rglob("*") if p.is_file())
        blob.write_bytes(b"bad")
        with self.assertRaises(IngestionError):
            Repository.restore(backup, Path(self.tmp.name) / "restore")

    def test_unknown_schema(self):
        root = Path(self.tmp.name) / "future"
        with Repository(root) as other:
            other.db.execute("PRAGMA user_version=999"); other.db.commit()
        with self.assertRaises(IngestionError):
            Repository(root)

    def test_idempotency_conflict(self):
        a, new = self.store.create_job("same", {"source": "one"})
        self.assertTrue(new)
        self.assertEqual(self.store.create_job("same", {"source": "one"}), (a, False))
        with self.assertRaises(IngestionError):
            self.store.create_job("same", {"source": "two"})

    def test_rejected_keeps_source(self):
        row = post(); row["帖子链接"] = "bad"
        self.load([row])
        checks = self.store.verify()
        self.assertEqual(checks["counts"]["posts"], 0)
        self.assertEqual(checks["counts"]["source_snapshots"], 1)
        self.assertNotEqual(self.store.db.execute('SELECT issues_json FROM source_snapshots').fetchone()[0],'[]')

    def test_reboot_requires_explicit_resume(self):
        jid, _ = self.store.create_job("restart", {"source": "one"})
        self.store.interrupt_jobs()
        self.assertEqual(self.store.job(jid)["state"], "interrupted")
        self.store.job_action(jid, "resume")
        self.assertEqual(self.store.job(jid)["state"], "pending")

    def test_dead_process_lock_released(self):
        import os
        target = Path(self.tmp.name) / "child-store"
        env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / "src"))
        code = "from autoinsight_ingestion.storage import Repository; import sys; r=Repository(sys.argv[1]); print('ready',flush=True); sys.stdin.read()"
        child = subprocess.Popen([sys.executable, "-c", code, str(target)], env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            self.assertEqual(child.stdout.readline().strip(), "ready")
            child.terminate(); child.wait(timeout=5)
            with Repository(target) as reopened:
                self.assertTrue(reopened.verify()["ok"])
        finally:
            if child.poll() is None:
                child.terminate(); child.wait(timeout=5)
            for stream in [child.stdin, child.stdout, child.stderr]:
                stream.close()

    def test_metadata_does_not_store_credentials(self):
        run = self.store.begin_run({}); task = self.store.task(run, "test", "test")
        response = self.store.response(task, b"public content", {"Cookie": "test-secret", "headers": {"Authorization": "test-secret"}, "url": "https://example.invalid/?token=test-secret&id=1"})
        text = self.store.db.execute("SELECT provenance_json FROM source_snapshots WHERE snapshot_id=?", (response,)).fetchone()[0]
        self.assertNotIn("test-secret", text)


if __name__ == "__main__":
    unittest.main()
