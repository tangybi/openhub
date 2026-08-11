"""Agent 列表 / 提问 接口。

身份与会话来自请求头：
- `X-Device-Id`：设备唯一码 → 惰性注册用户（「用户+XXXX」）
- `X-Session-Id`：会话 id（前端生成）→ 登记到该用户

统一 Ask 入口 `POST /api/agents/ask`：按领域自动路由到专家 Agent（services.router），
会话消息统一落库（避免各 agent 各落各的），路由时带最近会话历史辅助判断追问/指代。
"""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import StreamingResponse

from ..agents import AGENTS
from ..db import ensure_session, get_messages
from ..deps import Identity, get_identity
from ..logger_config import get_logger
from ..models import AgentInfo, AskRequest, AskResponse, SourceRef
from ..services import router as route_svc

logger = get_logger()

router = APIRouter(prefix="/api/agents", tags=["agents"])

_ROUTER_HISTORY_LIMIT = 6  # 路由带最近几条会话历史，辅助判断追问/指代

# 后台会话落库任务跟踪：持有引用防 GC 中途取消
_pending_persist_tasks: set[asyncio.Task] = set()


def _schedule_persist(question: str, answer: str, session_id: str) -> None:
    """把会话消息落库调度到后台任务，不阻塞 done 帧送达与连接关闭。"""
    if not session_id or not answer:
        return
    try:
        task = asyncio.create_task(route_svc.persist_session(session_id, question, answer))
    except RuntimeError:  # 事件循环不可用（极少数关闭场景）
        return
    _pending_persist_tasks.add(task)
    task.add_done_callback(_pending_persist_tasks.discard)


def _sse_headers() -> dict:
    return {
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
        "Connection": "keep-alive",
    }


async def _stream_sse(stream, *, question: str, session_id: str):
    """把 Agent 事件流统一转成 SSE 帧，并收集 delta 供会话落库；异常 → error 帧。

    stream 为 async generator，产出 AgentEvent：(sources/delta/done, data)。
    """
    answer_parts: list[str] = []
    try:
        async for event, data in stream:
            if event == "sources":
                yield f"event: sources\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
            elif event == "delta":
                answer_parts.append(data)
                yield f"event: delta\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
            elif event == "done":
                yield "event: done\ndata: {}\n\n"
    except Exception as e:
        logger.warning("流式回答出错：%s", e)
        yield f"event: error\ndata: {json.dumps({'message': str(e)}, ensure_ascii=False)}\n\n"
    finally:
        _schedule_persist(question, "".join(answer_parts), session_id)


@router.get("", response_model=dict)
async def list_agents(identity: Identity = Depends(get_identity)):
    return {
        "agents": [
            AgentInfo(
                name=a.name, label=a.label, category=a.category,
                available=a.available, description=a.description,
            )
            for a in AGENTS.values()
        ]
    }


@router.post("/ask", response_model=AskResponse)
async def ask_unified(
    body: AskRequest,
    identity: Identity = Depends(get_identity),
    x_session_id: str | None = Header(default=None),
):
    """统一 Ask 入口：按领域自动路由到专家 Agent；判不出时通用回答兜底。"""
    session_id = (x_session_id or "").strip()
    if session_id:
        await ensure_session(session_id, identity.user_id)
    question = body.question.strip()

    history = await get_messages(session_id, limit=_ROUTER_HISTORY_LIMIT) if session_id else []
    agent = await route_svc.route(
        question, user_id=identity.user_id, session_id=session_id, history=history
    )
    if agent is not None:
        result = await agent.ask(question, user_id=identity.user_id, session_id=session_id)
        answer = result.get("answer", "")
        sources = [SourceRef(**s) for s in result.get("sources", [])]
    else:
        answer = await route_svc.general_answer(
            question, user_id=identity.user_id, session_id=session_id, history=history
        )
        sources = []

    if session_id and answer:
        await route_svc.persist_session(session_id, question, answer)
    return AskResponse(answer=answer, sources=sources)


@router.post("/ask/stream")
async def ask_unified_stream(
    body: AskRequest,
    identity: Identity = Depends(get_identity),
    x_session_id: str | None = Header(default=None),
):
    """统一 Ask 流式入口（SSE）：路由后委托专家流式回答；兜底时整段流出通用回答。"""
    session_id = (x_session_id or "").strip()
    if session_id:
        await ensure_session(session_id, identity.user_id)
    question = body.question.strip()

    async def _sse():
        try:
            history = await get_messages(session_id, limit=_ROUTER_HISTORY_LIMIT) if session_id else []
            agent = await route_svc.route(
                question, user_id=identity.user_id, session_id=session_id, history=history
            )
        except Exception as e:
            logger.warning("统一 Ask 路由失败：%s", e)
            yield f"event: error\ndata: {json.dumps({'message': str(e)}, ensure_ascii=False)}\n\n"
            return
        if agent is not None:
            stream = agent.ask_stream(question, user_id=identity.user_id, session_id=session_id)
        else:

            async def _fallback_stream():
                answer = await route_svc.general_answer(
                    question, user_id=identity.user_id, session_id=session_id, history=history
                )
                yield ("sources", [])
                if answer:
                    yield ("delta", answer)
                yield ("done", None)

            stream = _fallback_stream()
        async for frame in _stream_sse(stream, question=question, session_id=session_id):
            yield frame

    return StreamingResponse(_sse(), media_type="text/event-stream", headers=_sse_headers())


@router.post("/{name}/ask", response_model=AskResponse)
async def ask_agent(
    name: str,
    body: AskRequest,
    identity: Identity = Depends(get_identity),
    x_session_id: str | None = Header(default=None),
):
    """直调指定 Agent（向后兼容；会话消息同样由入口统一落库）。"""
    agent = AGENTS.get(name)
    if agent is None:
        raise HTTPException(status_code=404, detail=f"未知 Agent: {name}")

    session_id = (x_session_id or "").strip()
    if session_id:
        await ensure_session(session_id, identity.user_id)

    question = body.question.strip()
    result = await agent.ask(question, user_id=identity.user_id, session_id=session_id)
    answer = result.get("answer", "")
    if session_id and answer:
        await route_svc.persist_session(session_id, question, answer)
    return AskResponse(
        answer=answer,
        sources=[SourceRef(**s) for s in result.get("sources", [])],
    )


@router.post("/{name}/ask/stream")
async def ask_agent_stream(
    name: str,
    body: AskRequest,
    identity: Identity = Depends(get_identity),
    x_session_id: str | None = Header(default=None),
):
    """直调指定 Agent 的 SSE 流式回答。身份/会话错误在流开始前抛（正常 HTTP 4xx）。"""
    agent = AGENTS.get(name)
    if agent is None:
        raise HTTPException(status_code=404, detail=f"未知 Agent: {name}")

    session_id = (x_session_id or "").strip()
    if session_id:
        await ensure_session(session_id, identity.user_id)

    question = body.question.strip()
    stream = agent.ask_stream(question, user_id=identity.user_id, session_id=session_id)
    return StreamingResponse(
        _stream_sse(stream, question=question, session_id=session_id),
        media_type="text/event-stream",
        headers=_sse_headers(),
    )


@router.get("/history")
async def agent_history(
    identity: Identity = Depends(get_identity),
    x_session_id: str | None = Header(default=None),
):
    """当前会话的历史消息（断点重连/刷新恢复用）。无会话或空会话返回空列表。"""
    session_id = (x_session_id or "").strip()
    if not session_id:
        return {"messages": []}
    try:
        await ensure_session(session_id, identity.user_id)
        messages = await get_messages(session_id, limit=50)
    except ValueError:
        return {"messages": []}
    return {
        "messages": [
            {"role": m.role, "content": m.content}
            for m in messages
        ]
    }
