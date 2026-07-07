"""
Agent 整合：MCP 工具 + Skill 模板 + 内置工具
基于 langgraph 1.0 create_react_agent，极简配置
"""

from __future__ import annotations

from langgraph.prebuilt import create_react_agent

from agent.tools.agent_tools import (
    fetch_external_data,
    fill_context_for_report,
    get_current_month,
    get_user_id,
    get_user_location,
    get_weather,
    rag_summarize,
)
from model.factory import chat_model
from rag.vector_store import VectorStoreService
from utils.logger_handler import logger
from utils.prompt_loader import load_system_prompts


class SmartAgent:
    """智能 Agent"""

    def __init__(
        self,
        mcp_tools: list | None = None,
        active_skill: str | None = None,
        auto_match_skill: bool = True,
    ):
        # 自动增量加载 data/ 中的新文档到向量库
        logger.info("[SmartAgent] 检查知识库增量更新...")
        VectorStoreService().load_document()

        tools = [
            rag_summarize,
            get_weather,
            get_user_location,
            get_user_id,
            get_current_month,
            fetch_external_data,
            fill_context_for_report,
        ] + (mcp_tools or [])

        prompt = load_system_prompts()
        if active_skill:
            from utils.skill_loader import inject_skill

            prompt = inject_skill(prompt, active_skill)

        self.agent = create_react_agent(
            model=chat_model,
            tools=tools,
            prompt=prompt,
        )

    def execute_stream(self, query: str, history: list[dict] | None = None):
        # 构建完整上下文消息
        messages = []
        if history:
            for msg in history:
                messages.append({"role": msg["role"], "content": msg["content"]})
        messages.append({"role": "user", "content": query})
        state = {"messages": messages}
        for chunk in self.agent.stream(
            state, stream_mode="updates", config={"recursion_limit": 25}
        ):
            # stream_mode="updates" 只返回每个节点的增量
            # 过滤：只输出最终的 AI 回复（不含 tool_calls 的 AIMessage）
            for node_output in chunk.values():
                if not isinstance(node_output, dict):
                    continue
                messages = node_output.get("messages", [])
                for msg in messages if isinstance(messages, list) else [messages]:
                    # 跳过 ToolMessage 和有 tool_calls 的 AIMessage（思考过程）
                    if hasattr(msg, "tool_calls") and msg.tool_calls:
                        continue
                    if getattr(msg, "type", None) == "tool":
                        continue
                    content = getattr(msg, "content", "")
                    if content:
                        yield content.strip() + "\n"


if __name__ == "__main__":
    agent = SmartAgent()
    for chunk in agent.execute_stream("帮我看看今天深圳天气怎么样"):
        print(chunk, end="", flush=True)
