"""统一 Ask 路由：按领域把问题派发到不同专家 Agent；判不出时通用回答兜底。

- :func:`route`：LLM 分类 → 返回选中的专家 Agent（可带会话历史辅助判断追问/指代）
- :func:`general_answer`：兜底通用回答（不带专家上下文，可带会话历史）
- :func:`persist_session`：入口层统一落会话历史（所有专家共享上下文，避免各 agent 各落各的）

专家列表从 ``AGENTS`` 动态生成，只取 available 的（占位 agent 不进路由）。
"""

from __future__ import annotations

from ..agents import Agent, AGENTS
from ..db import add_message
from ..logger_config import get_logger
from .llm import LLMError, chat_completion, chat_json

logger = get_logger()

_FALLBACK_ANSWER = (
    "我现在可以帮你做这些：\n"
    "· 热点新闻 —— 回答关于当前热点事件的提问\n"
    "· 粘贴查询 —— 用自然语言查已保存的粘贴（标题/语言/浏览量/过期时间/附件等）\n"
    "换个方向问，或者直接说说你想了解什么。"
)


def _available_agents() -> list[Agent]:
    return [a for a in AGENTS.values() if a.available]


def _format_history(history: list) -> str:
    """会话历史 → 提示词片段（角色 + 截断内容）。"""
    lines = []
    for m in history:
        role = "用户" if m.role == "user" else "助手"
        lines.append(f"{role}: {m.content[:200]}")
    return "\n".join(lines)


def _router_prompt(history: list | None = None) -> str:
    lines = [
        "你是问题路由助手。根据用户问题，从下面的专家 Agent 中选最合适的一个，只输出 JSON：",
        '{"agent": "<名字>"}',
        "如果都不合适（闲聊、无关问题），输出 {\"agent\": null}。不要输出其他内容。",
        "",
        "可用专家：",
    ]
    for a in _available_agents():
        lines.append(f"- {a.name}（{a.label}）：{a.description}")
    if history:
        lines.append("")
        lines.append("【本会话最近对话，用于判断追问/指代】")
        lines.append(_format_history(history))
    return "\n".join(lines)


async def route(
    question: str,
    *,
    user_id: str = "",
    session_id: str = "",
    history: list | None = None,
) -> Agent | None:
    """LLM 分类 → 返回选中专家；无 key / 分类失败 / 无匹配 → None（外层走兜底）。"""
    if not _available_agents():
        return None
    try:
        data = await chat_json(
            [
                {"role": "system", "content": _router_prompt(history)},
                {"role": "user", "content": question},
            ],
            temperature=0.0,  # 分类要确定性
            user_id=user_id,
            session_id=session_id,
        )
    except LLMError as e:
        logger.warning("路由分类 LLM 失败：%s", e)
        return None
    name = data.get("agent")
    agent = AGENTS.get(name) if isinstance(name, str) else None
    if agent is None or not agent.available:
        return None
    logger.info("路由[user=%s]: %s → %s", user_id or "-", question[:50], agent.name)
    return agent


async def general_answer(
    question: str,
    *,
    user_id: str = "",
    session_id: str = "",
    history: list | None = None,
) -> str:
    """兜底：通用助手直接回答（不带专家上下文）。LLM 失败 → 静态专家清单。"""
    directions = "、".join(f"{a.label}（{a.description}）" for a in _available_agents())
    messages = [
        {
            "role": "system",
            "content": (
                "你是通用助手。用户的问题不属于任何专家方向，直接自然回答；"
                "若问题适合更专业的处理，简要说明可以问的方向。\n"
                f"可用的专家方向：{directions}"
            ),
        },
    ]
    if history:
        messages.append({"role": "user", "content": f"【本会话最近对话】\n{_format_history(history)}"})
    messages.append({"role": "user", "content": question})
    try:
        answer = await chat_completion(
            messages, temperature=0.4, user_id=user_id, session_id=session_id
        )
    except LLMError as e:
        logger.warning("兜底通用回答 LLM 失败：%s", e)
        return _FALLBACK_ANSWER
    return answer or _FALLBACK_ANSWER


async def persist_session(session_id: str, question: str, answer: str) -> None:
    """入口层统一落会话历史（user + assistant）。无会话 / 失败静默。"""
    if not session_id:
        return
    try:
        await add_message(session_id, "user", question)
        await add_message(session_id, "assistant", answer)
    except Exception:
        logger.exception("会话历史落库失败")
