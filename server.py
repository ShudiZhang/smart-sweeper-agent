"""
智扫通 FastAPI 服务层
=====================
提供 REST API 接口，将 Agent 能力封装为生产服务。

端点:
  GET  /health              — 健康检查
  POST /chat                — 对话（非流式）
  POST /chat/stream         — 对话（SSE 流式）
  GET  /sessions            — 历史会话列表
  GET  /sessions/{id}       — 会话详情
  DELETE /sessions/{id}     — 删除会话

启动:
  uv run uvicorn server:app --host 0.0.0.0 --port 8000 --reload
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import RedirectResponse, StreamingResponse
from pydantic import BaseModel, Field

from agent.multi_agent import MultiAgentOrchestrator
from agent.smart_agent import SmartAgent
from utils.conversation_store import get_conversation_store
from utils.guardrails import GuardAction, get_input_guard

# ============================================================
# 数据模型
# ============================================================


class HistoryMessage(BaseModel):
    role: str = Field(..., description="user 或 assistant")
    content: str = Field(..., description="消息内容")


class ChatRequest(BaseModel):
    query: str = Field(..., description="用户问题", min_length=1)
    user_token: str = Field(default="default", description="用户标识")
    session_id: str | None = Field(default=None, description="会话ID，不传则新建")
    mode: str = Field(default="single", description="Agent模式: single | multi")
    history: list[HistoryMessage] | None = Field(default=None, description="对话历史")


class ChatResponse(BaseModel):
    answer: str
    session_id: str
    mode: str


class SessionInfo(BaseModel):
    session_id: str
    message_count: int
    last_active: float


# ============================================================
# Agent 管理
# ============================================================


class AgentManager:
    """管理单/多 Agent 实例（懒加载单例）"""

    def __init__(self):
        self._single: SmartAgent | None = None
        self._multi: MultiAgentOrchestrator | None = None

    def get_agent(self, mode: str = "single"):
        if mode == "multi":
            if self._multi is None:
                self._multi = MultiAgentOrchestrator()
            return self._multi
        else:
            if self._single is None:
                self._single = SmartAgent()
            return self._single


agent_manager = AgentManager()
conv_store = get_conversation_store()


# ============================================================
# FastAPI 应用
# ============================================================


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动时初始化"""
    yield


app = FastAPI(
    title="智扫通 API",
    description="扫地机器人智能客服 REST API",
    version="0.2.0",
    lifespan=lifespan,
)


# ---- 健康检查 ----


@app.get("/")
async def root():
    """重定向到 Swagger 文档"""
    return RedirectResponse(url="/docs")


@app.get("/health")
async def health():
    return {"status": "ok", "service": "smart-sweeper-agent"}


# ---- 非流式对话 ----


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    """非流式对话：发送问题，返回完整回答"""
    # Input Guard
    ig = get_input_guard()
    gr = ig.check(req.query)
    if gr.action == GuardAction.BLOCK:
        raise HTTPException(status_code=400, detail=gr.reason)

    session_id = req.session_id or uuid.uuid4().hex[:12]
    agent = agent_manager.get_agent(req.mode)

    # 转换 history 为 Agent 需要的 dict 格式
    history_dicts = (
        [{"role": h.role, "content": h.content} for h in req.history]
        if req.history
        else None
    )

    # 执行 Agent
    chunks: list[str] = []
    for chunk in agent.execute_stream(req.query, history=history_dicts):
        chunks.append(chunk)
    answer = "".join(chunks).strip()

    # 持久化
    conv_store.add_message(session_id, "user", req.query, user_token=req.user_token)
    conv_store.add_message(session_id, "assistant", answer, user_token=req.user_token)

    return ChatResponse(answer=answer, session_id=session_id, mode=req.mode)


# ---- 流式对话 (SSE) ----


@app.post("/chat/stream")
async def chat_stream(req: ChatRequest):
    """流式对话：Server-Sent Events 实时推送回答"""
    # Input Guard
    ig = get_input_guard()
    gr = ig.check(req.query)
    if gr.action == GuardAction.BLOCK:
        raise HTTPException(status_code=400, detail=gr.reason)

    session_id = req.session_id or uuid.uuid4().hex[:12]
    agent = agent_manager.get_agent(req.mode)

    # 转换 history 为 Agent 需要的 dict 格式
    history_dicts = (
        [{"role": h.role, "content": h.content} for h in req.history]
        if req.history
        else None
    )

    full_answer: list[str] = []

    async def generate():
        for chunk in agent.execute_stream(req.query, history=history_dicts):
            full_answer.append(chunk)
            yield f"data: {chunk}\n\n"

        # 持久化
        answer = "".join(full_answer).strip()
        conv_store.add_message(session_id, "user", req.query, user_token=req.user_token)
        conv_store.add_message(
            session_id, "assistant", answer, user_token=req.user_token
        )

        # 发送结束标记
        yield f"data: [DONE]\n\n"
        yield f'data: {{"session_id": "{session_id}"}}\n\n'

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ---- 会话管理 ----


@app.get("/sessions", response_model=list[SessionInfo])
async def list_sessions(user_token: str = Query(default="default")):
    """列出用户的所有会话"""
    sessions = conv_store.list_sessions(user_token=user_token)
    return [
        SessionInfo(
            session_id=s["session_id"],
            message_count=s["message_count"],
            last_active=s["last_active"],
        )
        for s in sessions
    ]


@app.get("/sessions/{session_id}")
async def get_session(session_id: str, user_token: str = Query(default="default")):
    """获取指定会话的对话历史"""
    messages = conv_store.get_session_history(session_id, user_token=user_token)
    if not messages:
        raise HTTPException(status_code=404, detail="会话不存在或已删除")
    return {"session_id": session_id, "messages": messages}


@app.delete("/sessions/{session_id}")
async def delete_session(session_id: str, user_token: str = Query(default="default")):
    """软删除指定会话"""
    count = conv_store.delete_session(session_id, user_token=user_token)
    return {"session_id": session_id, "deleted": count}


# ============================================================
# 启动入口
# ============================================================

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True)
