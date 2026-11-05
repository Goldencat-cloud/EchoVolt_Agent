"""Code interpreter sandbox for the agent's analysis step.

Execution model: generated Python runs in an isolated subprocess with pandas
preloaded from the semantic mirror (semantic views only). Guards:
  - AST pass rejects imports, dangerous builtins and dunder attribute access
  - pandas I/O entry points are patched out inside the wrapper, so only the
    preloaded semantic frames are reachable
  - hard timeout and output caps per run
The sandbox is local-demo grade: it enforces semantic-layer visibility and no
OS/network access from generated code.
"""
from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from semantic.adapters import compat_views as db_mirror

HERE = Path(__file__).resolve().parent
VENV_PYTHON = HERE / ".venv" / "Scripts" / "python.exe"
DB_PATH = db_mirror.DB_PATH
LOCAL_TEMP_ROOT = HERE / ".sandbox-tmp"
MAX_CODE_CHARS = 8000
MAX_OUTPUT_CHARS = 8000
TIMEOUT_SECONDS = 20
AGENT_SKILLS_DIR = HERE / "agent_skills"

FORBIDDEN_CALLS = {"open", "exec", "eval", "compile", "__import__", "input", "breakpoint"}
FORBIDDEN_ATTRS = {"system", "popen", "spawn", "fork", "kill", "remove", "unlink",
                   "rmtree", "makedirs", "mkdir"}

WRAPPER_TEMPLATE = '''
import io, json, sys, contextlib
sys.path.insert(0, r"{ROOT}")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import pandas as pd

def _load_frames():
    """Load semantic frames BEFORE any I/O patching (order matters)."""
    from semantic.adapters.compat_views import connect
    con = connect()
    raw = {{
        "metrics": pd.read_sql("SELECT * FROM semantic_aspect_metric", con),
        "claims": pd.read_sql("SELECT * FROM semantic_claim_fact", con),
        "evidence": pd.read_sql("SELECT * FROM semantic_claim_evidence", con),
        "post_scope": pd.read_sql("SELECT * FROM semantic_post_scope", con),
    }}
    meta = dict(pd.read_sql("SELECT key, value FROM semantic_snapshot_meta", con).values)
    con.close()
    return raw, meta

class Frames(dict):
    """Dict with attribute access, so frames.metrics and frames['metrics'] both work."""
    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

frames, meta = _load_frames()
frames = Frames(frames)

def _sandbox_blocked(*args, **kwargs):
    raise RuntimeError("sandbox: 仅可使用预载的语义层数据框，不允许 I/O")

for _name in ("read_csv", "read_json", "read_excel", "read_pickle", "read_sql",
              "read_sql_query", "read_sql_table", "read_html", "read_feather",
              "read_parquet", "read_sas", "read_stata", "read_spss", "read_clipboard",
              "to_csv", "to_json", "to_excel", "to_pickle", "to_sql", "to_html",
              "to_clipboard"):
    setattr(pd, _name, _sandbox_blocked)

with open(sys.argv[1], encoding="utf-8") as handle:
    code = handle.read()
namespace = {{"pd": pd, "frames": frames, "meta": meta, "result": None}}
buffer = io.StringIO()
payload = {{"ok": False, "stdout": "", "result": None, "error": None}}
try:
    with contextlib.redirect_stdout(buffer):
        exec(compile(code, "<analysis>", "exec"), namespace)
    payload["ok"] = True
except Exception as exc:
    payload["error"] = type(exc).__name__ + ": " + str(exc)
payload["stdout"] = buffer.getvalue()
value = namespace.get("result")
if value is not None:
    if hasattr(value, "to_dict"):
        try:
            value = value.to_dict(orient="records")
        except Exception:
            value = str(value)
    try:
        json.dumps(value, ensure_ascii=False, default=str)
        payload["result"] = value
    except (TypeError, ValueError):
        payload["result"] = str(value)
chart_value = namespace.get("chart")
if chart_value is not None:
    try:
        json.dumps(chart_value, ensure_ascii=False, default=str)
        payload["chart"] = chart_value
    except (TypeError, ValueError):
        payload["chart_error"] = "chart 不可 JSON 序列化"
print("@@RESULT@@" + json.dumps(payload, ensure_ascii=False, default=str))
'''


class SandboxError(ValueError):
    """Raised when generated code violates sandbox rules."""


def check_code(code: str) -> None:
    """Static guard: reject imports, dangerous calls and dunder attribute access."""
    if not code or not code.strip():
        raise SandboxError("代码为空")
    if len(code) > MAX_CODE_CHARS:
        raise SandboxError(f"代码过长（>{MAX_CODE_CHARS} 字符）")
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        raise SandboxError(f"语法错误: {exc}") from exc
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            raise SandboxError("沙箱内不允许 import；可用的是预载的 pandas / frames / meta")
        if isinstance(node, ast.Call):
            func = node.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
            if name in FORBIDDEN_CALLS:
                raise SandboxError(f"沙箱内不允许调用 {name}()")
        if isinstance(node, ast.Attribute):
            if node.attr.startswith("__"):
                raise SandboxError("沙箱内不允许访问双下划线属性")
            if node.attr in FORBIDDEN_ATTRS:
                raise SandboxError(f"沙箱内不允许访问 .{node.attr}")


def _wrapper_source(*, supplied_frames: bool = False) -> str:
    src = WRAPPER_TEMPLATE.replace("{DB}", DB_PATH.as_posix())
    src = src.replace("{ROOT}", HERE.as_posix())
    # the template escapes braces for readability; collapse them for execution
    src = src.replace("{{", "{").replace("}}", "}")
    if supplied_frames:
        src = src.replace("frames, meta = _load_frames()", """with open(sys.argv[2], encoding="utf-8") as _input:
    _payload = json.load(_input)
frames = {name: pd.DataFrame(rows) for name, rows in _payload["frames"].items()}
meta = _payload["meta"]""")
    return src


def run_code(code: str, *, frames: dict[str, Any] | None = None,
             meta: dict[str, Any] | None = None) -> dict[str, Any]:
    """Execute generated analysis code against the semantic frames."""
    try:
        check_code(code)
    except SandboxError as exc:
        return {"ok": False, "error": str(exc), "stdout": "", "result": None}
    python = VENV_PYTHON if VENV_PYTHON.is_file() else Path(sys.executable)
    tmp_root = Path(os.environ.get("AI_SANDBOX_TMP", str(LOCAL_TEMP_ROOT)))
    tmp_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=tmp_root) as tmp:
        tmp_dir = Path(tmp)
        wrapper = tmp_dir / "wrapper.py"
        user_code = tmp_dir / "analysis.py"
        wrapper.write_text(_wrapper_source(supplied_frames=frames is not None), encoding="utf-8")
        user_code.write_text(code, encoding="utf-8")
        arguments = [str(python), "-I", str(wrapper), str(user_code)]
        if frames is not None:
            input_path = tmp_dir / "frames.json"
            input_path.write_text(json.dumps({"frames": frames, "meta": meta or {}},
                                             ensure_ascii=False, default=str), encoding="utf-8")
            arguments.append(str(input_path))
        safe_env = {"PATH": os.environ.get("PATH", ""),
                    "PYTHONIOENCODING": "utf-8"}
        if os.name == "nt":
            for key in ("SYSTEMROOT", "WINDIR", "TEMP", "TMP"):
                if os.environ.get(key):
                    safe_env[key] = os.environ[key]
        try:
            completed = subprocess.run(
                arguments,
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=TIMEOUT_SECONDS, cwd=str(tmp_dir),
                # Never pass the web process' model credentials or deployment
                # configuration into generated analysis code.
                env=safe_env)
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": f"执行超时（>{TIMEOUT_SECONDS}s）",
                    "stdout": "", "result": None}
        raw = completed.stdout or ""
        marker = raw.rfind("@@RESULT@@")
        if marker < 0:
            stderr_tail = (completed.stderr or "")[-900:]
            return {"ok": False,
                    "error": "沙箱未返回结果（启动失败），stderr: " + (stderr_tail or "空"),
                    "stdout": raw[-MAX_OUTPUT_CHARS:], "result": None}
        try:
            payload = json.loads(raw[marker + len("@@RESULT@@"):])
        except json.JSONDecodeError:
            return {"ok": False, "error": "沙箱结果解析失败", "stdout": raw[-MAX_OUTPUT_CHARS:],
                    "result": None}
        for key in ("stdout", "result"):
            value = payload.get(key)
            if isinstance(value, str) and len(value) > MAX_OUTPUT_CHARS:
                payload[key] = value[:MAX_OUTPUT_CHARS] + "…(截断)"
        return payload


def semantic_sandbox_backend():
    """我们的沙箱实现为 DeepAgents 的 SandboxBackendProtocol 子类。

    deepagents 自带的是协议抽象 + LangSmith 云沙箱（需其服务）与
    LocalShellBackend（文档明示"unrestricted"，即宿主机裸执行）——
    没有本地 Python 数据沙箱。本类把语义层沙箱接入同一协议，
    execute(code) 直接执行 pandas 分析代码（非 shell 命令）。
    """
    from deepagents.backends import FilesystemBackend
    from deepagents.backends.sandbox import BaseSandbox, ExecuteResponse

    class SemanticSandboxBackend(FilesystemBackend, BaseSandbox):
        @property
        def id(self) -> str:
            return "semantic-sandbox"

        def execute(self, command: str, *, timeout: int | None = None) -> ExecuteResponse:
            global TIMEOUT_SECONDS
            original = TIMEOUT_SECONDS
            TIMEOUT_SECONDS = timeout or original
            try:
                outcome = run_code(command)
            finally:
                TIMEOUT_SECONDS = original
            output = outcome.get("stdout") or ""
            if outcome.get("result") is not None:
                output += "\nresult = " + json.dumps(
                    outcome["result"], ensure_ascii=False, default=str)[:2000]
            if outcome.get("error"):
                output += "\nERROR: " + str(outcome["error"])
            truncated = len(output) > MAX_OUTPUT_CHARS
            return ExecuteResponse(output=output[:MAX_OUTPUT_CHARS],
                                   exit_code=0 if outcome.get("ok") else 1,
                                   truncated=truncated)

    return SemanticSandboxBackend(root_dir=AGENT_SKILLS_DIR)


def semantic_frames_info() -> dict[str, Any]:
    """Describe the preloaded frames for the agent's exploration phase."""
    import re
    con = db_mirror.connect()
    try:
        out: dict[str, Any] = {}
        for name, table in (("metrics", "semantic_aspect_metric"),
                            ("claims", "semantic_claim_fact"),
                            ("evidence", "semantic_claim_evidence"),
                            ("post_scope", "semantic_post_scope")):
            cursor = con.execute(f"SELECT * FROM {table} LIMIT 3")
            columns = [d[0] for d in cursor.description]
            rows = [dict(r) for r in cursor.fetchall()]
            count = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            out[name] = {"columns": columns, "row_count": count, "sample": rows}
        meta = {r["key"]: r["value"] for r in
                con.execute("SELECT key, value FROM semantic_snapshot_meta")}
        version_raw = meta.get("data_version", "")
        match = re.search(r"V\d+(?:\.\d+)?", version_raw)
        version_token = match.group(0) if match else version_raw[:12]
        out["snapshot"] = {"data_version": version_token,
                           "temporary_sample": "占位" in version_raw or "临时" in version_raw,
                           "snapshot_hash": meta.get("snapshot_hash", ""),
                           "built_at": meta.get("built_at", "")}
        return out
    finally:
        con.close()
