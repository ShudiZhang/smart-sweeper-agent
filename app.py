"""智扫通机器人客服 — Streamlit 入口"""

import logging
import time

import streamlit as st

from agent.smart_agent import SmartAgent
from utils.skill_loader import load_all_skills
from utils.tracing import init_tracing

# 减少第三方库的日志噪音
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("langchain").setLevel(logging.WARNING)


def _load_mcp_tools():
    """尝试加载 MCP 工具（需要安装 mcp 包且配置了 AMAP_API_KEY）"""
    try:
        import subprocess

        subprocess.run(["python", "-c", "import mcp"], capture_output=True, check=True)
        # 这里可以对接 langchain 的 MCP 适配器
        # from langchain_mcp import MCPToolkit
        # return MCPToolkit.from_server(f"python {server_path}").get_tools()
    except Exception:
        pass
    return []


def main():
    # LangSmith 追踪 — 设了 Key 则自动捕获，没设则静默跳过
    init_tracing()

    st.set_page_config(page_title="智扫通", page_icon="🤖")
    st.title("🤖 智扫通机器人智能客服")

    # ---- 侧边栏配置 ----
    with st.sidebar:
        st.header("⚙️ Agent 配置")

        # Skill 选择
        skills = load_all_skills()
        skill_options = ["无（通用模式）"] + list(skills.keys())
        selected_skill_label = st.selectbox(
            "激活 Skill 模板",
            skill_options,
            help="选择后 Agent 会按特定领域模板工作",
        )
        active_skill = (
            None if selected_skill_label == "无（通用模式）" else selected_skill_label
        )

        # MCP 开关
        use_mcp = st.checkbox(
            "启用 MCP 工具（高德IP定位+天气）",
            value=False,
            help="需要安装 mcp 包并配置 AMAP_API_KEY",
        )

        st.divider()
        st.caption("Agent 会自动根据你的提问选择合适的工具。")
        st.caption(
            "可用工具：RAG检索、用户数据、外部记录"
            + ("、高德定位、高德天气" if use_mcp else "")
        )

        if st.button("🔄 重置会话"):
            st.session_state.clear()
            st.rerun()

    # ---- 初始化 Agent（首次加载或配置变更时重建） ----
    cache_key = f"agent_{active_skill}_{use_mcp}"
    if st.session_state.get("agent_key") != cache_key:
        mcp_tools = _load_mcp_tools() if use_mcp else None
        st.session_state["agent"] = SmartAgent(
            mcp_tools=mcp_tools,
            active_skill=active_skill,
        )
        st.session_state["agent_key"] = cache_key

    # ---- 初始化消息列表 ----
    if "message" not in st.session_state:
        st.session_state["message"] = []

    # ---- 渲染历史消息 ----
    for message in st.session_state["message"]:
        st.chat_message(message["role"]).write(message["content"])

    # ---- 用户输入 ----
    prompt = st.chat_input("请输入你的问题...")

    if prompt:
        st.chat_message("user").write(prompt)
        st.session_state["message"].append({"role": "user", "content": prompt})

        response_messages: list[str] = []
        with st.spinner("智能客服思考中..."):
            res_stream = st.session_state["agent"].execute_stream(prompt)

            def capture(generator, cache_list):
                for chunk in generator:
                    cache_list.append(chunk)
                    for char in chunk:
                        time.sleep(0.01)
                        yield char

            st.chat_message("assistant").write_stream(
                capture(res_stream, response_messages)
            )
            st.session_state["message"].append(
                {"role": "assistant", "content": "".join(response_messages)}
            )
            st.rerun()


if __name__ == "__main__":
    main()
