"""In-memory async job store with phase-level progress events.

Serves two purposes: lightweight progress hints for the UI ("理解问题中…")
and an observability surface for monitoring/evaluation — every phase
transition and the final outcome (including failures) is recorded.

State lives in a `JobStore` instance created by the composition root via
`configure()`; tests inject their own so cases never share jobs.
"""
from __future__ import annotations

import threading
import time
import uuid
from typing import Any, Callable

MAX_JOBS = 200
MAX_ACTIVE_JOBS = 2
JOB_TTL_SECONDS = 3600.0
# D5：待审/澄清中的 job 属"等用户"状态——TTL 延长（6h，演示场景一节课/半天
# 量级），且不计入执行名额；全局待审上限约束 checkpointer 内存占用。
PENDING_TTL_SECONDS = 6 * 3600.0
MAX_PENDING_JOBS = 10
PENDING_STATUSES = ("awaiting_review", "clarifying")


class JobStore:
    """任务状态的唯一容器：锁与字典同属一个实例，可由组合根整体替换。"""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.jobs: dict[str, dict[str, Any]] = {}


_store: JobStore | None = None


def configure(store: JobStore) -> None:
    """由组合根（app.py、测试 setUp）注入；缺省时懒建进程内实例。"""
    global _store
    _store = store


def _state() -> JobStore:
    global _store
    if _store is None:
        _store = JobStore()
    return _store


def create_job(question: str, brief: dict[str, Any] | None = None,
               session_id: str | None = None) -> str | None:
    # The id is a temporary bearer token for polling a report result.
    job_id = uuid.uuid4().hex
    store = _state()
    with store.lock:
        jobs = store.jobs
        active = sum(1 for job in jobs.values() if job["status"] == "running")
        if active >= MAX_ACTIVE_JOBS:
            return None
        pending = [job for job in jobs.values() if job["status"] in PENDING_STATUSES]
        if len(pending) >= MAX_PENDING_JOBS:
            return None
        if session_id and any(job.get("session_id") == session_id for job in pending):
            return None  # D5：每会话单待审 job，先完成当前审查
        # evict expired/oldest when over budget
        if len(jobs) >= MAX_JOBS:
            completed = sorted((key for key, job in jobs.items()
                                if job["status"] != "running"),
                               key=lambda key: jobs[key]["created_at"])
            to_remove = len(jobs) - MAX_JOBS + 1
            if len(completed) < to_remove:
                return None
            for key in completed[:to_remove]:
                jobs.pop(key, None)
        jobs[job_id] = {"job_id": job_id, "question": question, "status": "running",
                        "phase": "澄清中", "events": [{"phase": "澄清中",
                                                       "ts": time.time()}],
                        "brief": brief, "session_id": session_id,
                        "result": None, "error": None, "created_at": time.time()}
    return job_id


def _update(job_id: str, change: Callable[[dict[str, Any]], Any]) -> Any:
    """在锁内读取并变更一个 job；不存在时不执行变更并返回 None。"""
    store = _state()
    with store.lock:
        job = store.jobs.get(job_id)
        if job is None:
            return None
        return change(job)


def _advance(job: dict[str, Any], phase: str, **fields: Any) -> None:
    """推进阶段：更新字段、记录 phase 并追加事件（事件流的唯一写法）。"""
    job.update(fields)
    job["phase"] = phase
    job["events"].append({"phase": phase, "ts": time.time()})


def _transition(job_id: str, expected: str, phase: str, **fields: Any) -> bool:
    """仅当处于 expected 状态时推进；用于 start/resume 的重复提交守卫。"""
    def change(job: dict[str, Any]) -> bool:
        if job["status"] != expected:
            return False
        _advance(job, phase, status="running", **fields)
        return True

    return bool(_update(job_id, change))


def set_phase(job_id: str, phase: str) -> None:
    _update(job_id, lambda job: _advance(job, phase))


def finish_ok(job_id: str, result: dict[str, Any]) -> None:
    _update(job_id, lambda job: _advance(job, "已完成", status="done", result=result))


def finish_error(job_id: str, error: dict[str, Any]) -> None:
    _update(job_id, lambda job: _advance(job, "失败", status="failed", error=error))


def pause_for_review(job_id: str, outline: dict[str, Any]) -> None:
    """Job paused at the outline gate (D4/D9): waiting for the user, not running.

    An awaiting job does not count against MAX_ACTIVE_JOBS (see create_job) —
    it occupies no execution slot while the graph is suspended in the
    checkpointer.
    """
    def change(job: dict[str, Any]) -> None:
        _advance(job, "待大纲审查", status="awaiting_review", outline=outline)
        job.setdefault("outline_history", []).append(outline)

    _update(job_id, change)


def pause_for_clarify(job_id: str, questions: list[dict[str, Any]]) -> None:
    """Job waiting for clarification answers (D10): status `clarifying`."""
    _update(job_id, lambda job: _advance(job, "澄清中", status="clarifying",
                                        clarify_questions=questions))


def record_clarification(job_id: str, answer: dict[str, Any],
                         questions: list[dict[str, Any]] | None) -> None:
    """Store one clarification round; `questions` replaces the open list."""
    def change(job: dict[str, Any]) -> None:
        job.setdefault("clarifications", []).append(answer)
        if questions is not None:
            job["clarify_questions"] = questions
        job["events"].append({"phase": "澄清中", "ts": time.time()})

    _update(job_id, change)


def claim_for_run(job_id: str, phase: str = "数据探索中") -> bool:
    """Atomically transition clarifying → running (start/continue agent run)."""
    return _transition(job_id, "clarifying", phase)


def pending_exists_for(session_id: str) -> bool:
    """True when the session already has a waiting (clarifying/review) job (D5)."""
    store = _state()
    with store.lock:
        return any(job.get("session_id") == session_id
                   for job in store.jobs.values() if job["status"] in PENDING_STATUSES)


def claim_for_resume(job_id: str, phase: str = "编写分析代码中") -> bool:
    """Atomically transition awaiting_review → running (guards double resume)."""
    return _transition(job_id, "awaiting_review", phase)


def record_regenerate(job_id: str) -> int:
    """Count one outline regenerate (reject→redraft) cycle; returns new count."""
    def change(job: dict[str, Any]) -> int:
        job["regenerates"] = int(job.get("regenerates", 0)) + 1
        return job["regenerates"]

    return _update(job_id, change) or 0


def record_delivery_spec(job_id: str, spec: dict[str, Any]) -> None:
    """Store the optional 重点/受众 delivery spec carried with confirm/edit (D12)."""
    _update(job_id, lambda job: job.update(delivery_spec=spec))


def get_job(job_id: str) -> dict[str, Any] | None:
    return _update(job_id, json_copy)


def json_copy(job: dict[str, Any]) -> dict[str, Any]:
    # Never echo the submitted question or internal timestamps from the public
    # polling endpoint. The browser needs only progress and the completed result.
    visible = {k: v for k, v in job.items() if k not in {"question", "created_at"}}
    return {k: (list(v) if isinstance(v, list) else dict(v) if isinstance(v, dict) else v)
            for k, v in visible.items()}


def run_async(job_id: str, work: Callable[[Callable[[str], None]], dict[str, Any]]) -> None:
    """Run `work(set_phase)` in a background thread; record outcome."""

    def target() -> None:
        try:
            result = work(lambda phase: set_phase(job_id, phase))
            finish_ok(job_id, result)
        except Exception as exc:  # failures must surface, never be swallowed
            finish_error(job_id, {"error": f"{type(exc).__name__}: {exc}"})

    threading.Thread(target=target, daemon=True).start()


def cleanup() -> None:
    """Drop finished jobs past JOB_TTL; waiting jobs past the longer PENDING_TTL (D5)."""
    now = time.time()
    terminal_cutoff = now - JOB_TTL_SECONDS
    pending_cutoff = now - PENDING_TTL_SECONDS
    store = _state()
    with store.lock:
        expired = [key for key, job in store.jobs.items()
                   if (job["status"] not in PENDING_STATUSES and job["status"] != "running"
                       and job["created_at"] < terminal_cutoff)
                   or (job["status"] in PENDING_STATUSES
                       and job["created_at"] < pending_cutoff)]
        for key in expired:
            store.jobs.pop(key, None)
