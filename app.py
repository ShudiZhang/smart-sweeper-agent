"""智扫通机器人客服 — Streamlit 入口"""

import logging
import os
import subprocess
import sys
import time

import streamlit as st

from agent.smart_agent import SmartAgent
from utils.skill_loader import get_skill_manager
from utils.tracing import init_tracing

# 减少第三方库的日志噪音
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("langchain").setLevel(logging.WARNING)


def _load_mcp_tools():
    """加载 MCP 工具 — 通过 langchain_mcp 适配器连接高德 MCP Server"""
    try:
        from langchain_mcp import load_mcp_tools

        server_path = os.path.join(
            os.path.dirname(__file__), "mcp_servers", "amap_server.py"
        )
        # 使用当前 Python 解释器启动 MCP Server
        mcp_tools = load_mcp_tools(
            f"{sys.executable} {server_path}",
        )
        if mcp_tools:
            logging.getLogger(__name__).info(
                f"[MCP] 成功加载 {len(mcp_tools)} 个 MCP 工具"
            )
            return mcp_tools
    except ImportError:
        logging.getLogger(__name__).warning(
            "[MCP] langchain_mcp 未安装，请执行: pip install langchain-mcp"
        )
    except Exception as e:
        logging.getLogger(__name__).warning(f"[MCP] 加载失败: {e}")
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
        skill_manager = get_skill_manager()
        skill_map = skill_manager.list_all()
        skill_options = ["🧠 自动匹配（推荐）"] + [
            f"📌 {desc} ({name})" for name, desc in skill_map.items()
        ]
        selected_skill_label = st.selectbox(
            "激活 Skill 模板",
            skill_options,
            help="自动匹配：根据你的问题自动选择最合适的技能模板",
        )

        if selected_skill_label == "🧠 自动匹配（推荐）":
            active_skill = None
            auto_match = True
        else:
            # 从 "📌 描述 (name)" 格式中提取 name
            active_skill = selected_skill_label.split("(")[-1].rstrip(")")
            auto_match = False

        # 显示当前可用 Skill 列表
        with st.expander("📋 可用技能模板"):
            for name, desc in skill_map.items():
                st.caption(f"**{name}**: {desc}")

        # MCP 开关
        use_mcp = st.checkbox(
            "启用 MCP 工具（高德IP定位+天气）",
            value=False,
            help="需要安装 langchain-mcp 包并配置 AMAP_API_KEY",
        )

        st.divider()
        st.caption("Agent 会自动根据你的提问选择合适的工具。")

        tool_list = "RAG检索、用户数据、外部记录"
        if use_mcp:
            tool_list += "、高德定位、高德天气"
        st.caption(f"可用工具：{tool_list}")

        if st.button("🔄 重置会话"):
            st.session_state.clear()
            st.rerun()

    # ---- 初始化 Agent（首次加载或配置变更时重建） ----
    cache_key = f"agent_{active_skill}_{auto_match}_{use_mcp}"
    if st.session_state.get("agent_key") != cache_key:
        mcp_tools = _load_mcp_tools() if use_mcp else None
        st.session_state["agent"] = SmartAgent(
            mcp_tools=mcp_tools,
            active_skill=active_skill,
            auto_match_skill=auto_match,
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
