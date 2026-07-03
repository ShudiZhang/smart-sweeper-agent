"""
Agent 整合示例：MCP 工具 + Skill 模板 + 内置工具
展示如何将三者结合起来使用
"""

from langchain.agents import create_agent

from agent.middleware import log_before_model, monitor_tool, report_prompt_switch
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
from utils.prompt_loader import load_system_prompts
from utils.skill_loader import inject_skill


class SmartAgent:
    """
    智能 Agent：
    - 内置工具：rag_summarize, fetch_external_data, get_user_id, get_current_month,
      get_user_location, get_weather
    - MCP 工具：amap_ip_location, amap_weather（通过 MCP 协议连接高德服务）
    - Skill 模板：report_generation, troubleshooting
    """

    def __init__(self, mcp_tools: list | None = None, active_skill: str | None = None):
        # 内置工具
        builtin_tools = [
            rag_summarize,
            get_user_id,
            get_current_month,
            get_user_location,
            get_weather,
            fetch_external_data,
            fill_context_for_report,
        ]

        # 合并 MCP 工具（如果有）
        all_tools = builtin_tools + (mcp_tools or [])

        # 加载系统提示词
        system_prompt = load_system_prompts()

        # 注入 Skill 模板
        if active_skill:
            system_prompt = inject_skill(system_prompt, active_skill)

        self.agent = create_agent(
            model=chat_model,
            system_prompt=system_prompt,
            tools=all_tools,
            middleware=[monitor_tool, log_before_model, report_prompt_switch],
        )

    def execute_stream(self, query: str):
        input_dict = {"messages": [{"role": "user", "content": query}]}
        for chunk in self.agent.stream(
            input_dict, stream_mode="values", context={"report": False}
        ):
            latest_message = chunk["messages"][-1]
            if latest_message.content:
                yield latest_message.content.strip() + "\n"


# ---- 使用示例 ----

if __name__ == "__main__":
    """
    方式一：纯内置工具（当前模式）
    agent = SmartAgent()

    方式二：连接 MCP Server
    from langchain_mcp import load_mcp_tools
    mcp_tools = load_mcp_tools("python mcp_servers/amap_server.py")
    agent = SmartAgent(mcp_tools=mcp_tools)

    方式三：激活特定 Skill
    agent = SmartAgent(active_skill="report_generation")
    """
    agent = SmartAgent()
    for chunk in agent.execute_stream("帮我看看今天深圳天气怎么样"):
        print(chunk, end="", flush=True)
