"""统一的 LLM 客户端创建入口（本轮重构收口）。

此前服务内共有 3 处独立的客户端创建（agent_engine._model、clarify._llm_judge
内联 ChatOpenAI、research/embeddings._client），各自读取同一组环境变量。
现收敛到本模块；不同调用场景通过参数区分（超时/重试/温度），不做多余抽象。

约定：
- 环境变量：AI_MODEL / AI_BASE_URL / AI_API_KEY（由 app 启动时从 local-config 装载）；
- 聊天模型走 langchain_openai.ChatOpenAI；向量检索走 openai SDK 的 /embeddings；
- 允许按场景覆盖参数，但配置读取只有这一处。
"""
from __future__ import annotations

import os


def chat_model(*, timeout: int = 240, max_retries: int = 2,
               temperature: float = 0):
    """创建聊天模型客户端。agent 主链路用默认值；轻量判定用小超时/低重试。"""
    from langchain_openai import ChatOpenAI

    return ChatOpenAI(
        model=os.environ["AI_MODEL"],
        base_url=os.environ["AI_BASE_URL"],
        api_key=os.environ["AI_API_KEY"],
        temperature=temperature,
        timeout=timeout,
        max_retries=max_retries,
    )


def embeddings_client():
    """创建 embeddings 客户端（openai SDK；后端可选，失败由调用方降级）。"""
    from openai import OpenAI  # imported lazily: backend is optional

    return OpenAI(base_url=os.getenv("AI_BASE_URL"), api_key=os.getenv("AI_API_KEY"))


def chat_completions_url() -> str:
    """chat/completions 端点 URL（raw HTTP 调用方使用；SDK 客户端自带拼接）。"""
    base = os.environ["AI_BASE_URL"].rstrip("/")
    return base if base.endswith("/chat/completions") else base + "/chat/completions"
