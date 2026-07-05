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
from utils.prompt_loader import load_system_prompts


class ReactAgent:
    def __init__(self):
        self.agent = create_react_agent(
            model=chat_model,
            tools=[
                rag_summarize,
                get_weather,
                get_user_location,
                get_user_id,
                get_current_month,
                fetch_external_data,
                fill_context_for_report,
            ],
            prompt=load_system_prompts(),
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
            for node_output in chunk.values():
                if not isinstance(node_output, dict):
                    continue
                messages = node_output.get("messages", [])
                for msg in messages if isinstance(messages, list) else [messages]:
                    if hasattr(msg, "tool_calls") and msg.tool_calls:
                        continue
                    if getattr(msg, "type", None) == "tool":
                        continue
                    content = getattr(msg, "content", "")
                    if content:
                        yield content.strip() + "\n"


if __name__ == "__main__":
    agent = ReactAgent()

    for chunk in agent.execute_stream("给我生成我的使用报告"):
        print(chunk, end="", flush=True)
