"""DeepSeek LLM 客户端（OpenAI 兼容协议）。

DeepSeek 与 OpenAI SDK 兼容，直接走 /chat/completions。
未配置 DEEPSEEK_API_KEY 时抛出 LLMError，上层按「降级策略」处理
（回退到 feed 自带摘要 + 启发式热度分），保证 RSS 聚合仍可用。
"""

from __future__ import annotations

import json

import httpx

from ..config import settings


class LLMError(Exception):
    """LLM 调用失败（未配置 key / 网络 / 服务错误）。"""


async def chat_completion(
    messages: list[dict],
    *,
    json_mode: bool = False,
    temperature: float = 0.3,
    max_tokens: int = 1024,
    user_id: str = "",
    session_id: str = "",
) -> str:
    """调用 DeepSeek chat 接口，返回助手消息文本。

    user_id / session_id 透传给服务端（DeepSeek `user` 字段用于审计/个性化），
    后续所有 LLM 调用都应带上。
    """
    if not settings.deepseek_api_key:
        raise LLMError("未配置 DEEPSEEK_API_KEY")

    url = settings.deepseek_base_url.rstrip("/") + "/chat/completions"
    payload: dict = {
        "model": settings.deepseek_model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }
    if user_id:
        payload["user"] = user_id
    if session_id:
        payload["session_id"] = session_id
    if json_mode:
        payload["response_format"] = {"type": "json_object"}

    async with httpx.AsyncClient(timeout=90) as client:
        r = await client.post(
            url,
            json=payload,
            headers={"Authorization": f"Bearer {settings.deepseek_api_key}"},
        )

    if r.status_code != 200:
        raise LLMError(f"DeepSeek 调用失败: HTTP {r.status_code} {r.text[:300]}")
    data = r.json()
    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise LLMError(f"DeepSeek 返回格式异常: {str(data)[:300]}")


async def chat_json(
    messages: list[dict],
    *,
    temperature: float = 0.2,
    user_id: str = "",
    session_id: str = "",
) -> dict:
    """JSON 模式的对话，返回解析后的 dict。解析失败抛 LLMError。"""
    text = await chat_completion(
        messages, json_mode=True, temperature=temperature, user_id=user_id, session_id=session_id
    )
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # 兜底：从文本中截取首个 {...} 块
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            raise LLMError(f"DeepSeek 非 JSON 返回: {text[:300]}")
        data = json.loads(text[start : end + 1])
    if not isinstance(data, dict):
        raise LLMError("DeepSeek JSON 返回不是对象")
    return data
