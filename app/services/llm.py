"""DeepSeek LLM 客户端（OpenAI 兼容协议）。

DeepSeek 与 OpenAI SDK 兼容，直接走 /chat/completions。
未配置 DEEPSEEK_API_KEY 时抛出 LLMError，上层按「降级策略」处理
（回退到 feed 自带摘要 + 启发式热度分），保证 RSS 聚合仍可用。
"""

from __future__ import annotations

import json

import httpx

from ..logger_config import get_logger

from ..config import settings

logger = get_logger()


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

    headers = {"Authorization": f"Bearer {settings.deepseek_api_key}"}
    answer = ""
    # 返回空内容时自动重试一次；连续两次为空则抛 LLMError，由上层给用户友好提示
    for attempt in (1, 2):
        async with httpx.AsyncClient(timeout=90) as client:
            r = await client.post(url, json=payload, headers=headers)
        if r.status_code != 200:
            raise LLMError(f"DeepSeek 调用失败: HTTP {r.status_code} {r.text[:300]}")
        data = r.json()
        try:
            answer = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise LLMError(f"DeepSeek 返回格式异常: {str(data)[:300]}")
        if answer and answer.strip():
            break
        logger.warning("LLM 返回空内容，第 %d 次尝试（user=%s session=%s）",
                       attempt, user_id or "-", session_id or "-")
    else:
        raise LLMError("DeepSeek 连续两次返回空内容")
    logger.info("LLM 回答[user=%s session=%s]：%s", user_id or "-", session_id or "-", answer)
    return answer


async def chat_completion_stream(
    messages: list[dict],
    *,
    temperature: float = 0.4,
    max_tokens: int = 1024,
    user_id: str = "",
    session_id: str = "",
):
    """流式调用 DeepSeek chat，逐段 yield 文本 delta（OpenAI 兼容 SSE）。

    与 :func:`chat_completion` 同款降级语义：整条流一个内容 delta 都没有时
    自动重试一次，仍空抛 LLMError；网络/HTTP 异常立即抛 LLMError（不重试）。
    """
    if not settings.deepseek_api_key:
        raise LLMError("未配置 DEEPSEEK_API_KEY")

    url = settings.deepseek_base_url.rstrip("/") + "/chat/completions"
    payload: dict = {
        "model": settings.deepseek_model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": True,
    }
    if user_id:
        payload["user"] = user_id
    if session_id:
        payload["session_id"] = session_id

    headers = {"Authorization": f"Bearer {settings.deepseek_api_key}"}
    for attempt in (1, 2):
        got_any = False
        async with httpx.AsyncClient(timeout=90) as client:
            try:
                async with client.stream("POST", url, json=payload, headers=headers) as r:
                    if r.status_code != 200:
                        body = (await r.aread()).decode("utf-8", "replace")
                        raise LLMError(f"DeepSeek 调用失败: HTTP {r.status_code} {body[:300]}")
                    async for line in r.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        data = line[len("data:"):].strip()
                        if data == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data)
                            delta = chunk["choices"][0]["delta"].get("content", "")
                        except (KeyError, IndexError, TypeError, json.JSONDecodeError):
                            continue  # 心跳/空对象/格式异常，忽略
                        if delta:
                            got_any = True
                            yield delta
            except httpx.HTTPError as e:
                raise LLMError(f"DeepSeek 网络/HTTP 异常: {e}") from e
        if got_any:
            return
        logger.warning("LLM 流式返回空内容，第 %d 次尝试（user=%s session=%s）",
                       attempt, user_id or "-", session_id or "-")
    raise LLMError("DeepSeek 连续两次返回空内容")


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
