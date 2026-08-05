"""Agent 列表 / 提问 接口。

身份与会话来自请求头：
- `X-Device-Id`：设备唯一码 → 惰性注册用户（「用户+XXXX」）
- `X-Session-Id`：会话 id（前端生成）→ 登记到该用户
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException

from ..agents import AGENTS
from ..db import ensure_session
from ..deps import Identity, get_identity
from ..models import AgentInfo, AskRequest, AskResponse, SourceRef

router = APIRouter(prefix="/api/agents", tags=["agents"])


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


@router.post("/{name}/ask", response_model=AskResponse)
async def ask_agent(
    name: str,
    body: AskRequest,
    identity: Identity = Depends(get_identity),
    x_session_id: str | None = Header(default=None),
):
    agent = AGENTS.get(name)
    if agent is None:
        raise HTTPException(status_code=404, detail=f"未知 Agent: {name}")

    session_id = (x_session_id or "").strip()
    if session_id:
        await ensure_session(session_id, identity.user_id)

    result = await agent.ask(
        body.question.strip(),
        user_id=identity.user_id,
        session_id=session_id,
    )
    return AskResponse(
        answer=result.get("answer", ""),
        sources=[SourceRef(**s) for s in result.get("sources", [])],
    )
