"""AutoInsight MVP Web service — 应用入口与依赖装配。

本轮重构拆分（原单文件 646 行）：
- routes.py      ：HTTP 协议层（路由/限流/静态资源）；
- orchestrator.py：业务编排层（报告任务/问答/对话，框架无关）；
- app.py（本文件）：应用创建、配置装载、启动入口，并作为既有调用方的兼容门面。

统计数字与证据一律来自 service.py 的确定性工具；LLM 仅在其上组织解释。
报告问答基于最新已发布报告（/report/full、/api/reports/published/latest）。
密钥只从进程环境读取。
"""
from __future__ import annotations

import os

from http.server import ThreadingHTTPServer

import config
from research import service
import report_source
import report_publisher
# 兼容门面：既有调用方（tests/e2e probes）通过 app.X 访问这些名字。
# 注意：patch 测试应 patch 定义处（routes._rate_limited / orchestrator._call_report_qa），
# 这里 re-export 的引用仅用于直接调用与状态访问。
from routes import (Handler, LEGACY_REPORT, MAX_BODY, RATE_LIMIT_REQUESTS,
                    RATE_WINDOW_SECONDS, WEB, _RATE, _rate_limited)
from orchestrator import (MAX_QUESTION, MAX_REPORT_CONTEXT_CHARS, SESSIONS,
                          _call_report_qa, _present, _suggestions_payload,
                          agent_report_clarify, agent_report_outline,
                          agent_report_start, agent_report_status, ask_core,
                          model_configured, question_core)


def _load_env(path=None) -> None:
    """Shim kept for compatibility: configuration loading lives in config.py."""
    config.load_env(path)


_load_env()

if __name__ == "__main__":
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "8000"))
    print(f"AutoInsight listening on http://{host}:{port}")
    ThreadingHTTPServer((host, port), Handler).serve_forever()
