import json
import threading
import time
from http.server import ThreadingHTTPServer

import httpx
import pytest

from mcp_server import web


def data():
    return {"brand": "小米", "product": "SU7", "aspects": ["tech"],
            "time_from": "2026-08-01", "time_to": "2026-08-31"}


@pytest.mark.parametrize("change", [{"brand": ""}, {"aspects": []}, {"aspects": ["bad"]},
    {"time_to": "2026-01-01"}, {"time_from": "bad"}, {"official_domains": ["https://a.com"]}])
def test_reject_invalid_input(change):
    with pytest.raises(ValueError):
        web.validate_input({**data(), **change})


def test_restart_marks_job_interrupted(tmp_path):
    folder = tmp_path / "job"
    folder.mkdir()
    (folder / "job.json").write_text(json.dumps({"id": "job", "status": "running"}), encoding="utf-8")
    jobs = web.Jobs(tmp_path)
    assert jobs.snapshot("job")["status"] == "interrupted"


def test_no_duplicate_running_job(tmp_path, monkeypatch):
    gate = threading.Event()
    def blocked(*args):
        gate.wait(2)
    monkeypatch.setattr(web.Jobs, "run", blocked)
    jobs = web.Jobs(tmp_path)
    job = jobs.start(data())
    try:
        assert job["query_count"] == 4
        with pytest.raises(RuntimeError):
            jobs.start(data())
        assert (tmp_path / job["id"] / "job.json").exists()
    finally:
        gate.set()


def test_http_ui_and_origin_guard(tmp_path):
    server = ThreadingHTTPServer(("127.0.0.1", 0), web.handler(web.Jobs(tmp_path)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}"
    try:
        with httpx.Client(trust_env=False) as client:
            assert "事件聚合工具" in client.get(url).text
            config = client.get(url + "/api/config").json()
            assert set(config) == {"search", "llm", "embedding"}
            assert client.get(url + "/api/jobs").json() == []
            assert client.get(url + "/api/jobs/missing").status_code == 404
            assert client.post(url + "/api/jobs", json=data(), headers={"Origin": "https://example.com"}).status_code == 403
            assert client.post(url + "/api/jobs", json={}).status_code == 400
    finally:
        server.shutdown()
        server.server_close()
