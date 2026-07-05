"""智扫通机器人客服 — Streamlit 入口"""

import logging
import os
import subprocess
import sys
import time
import uuid

import streamlit as st

from agent.multi_agent import MultiAgentOrchestrator
from agent.smart_agent import SmartAgent
from utils.conversation_store import get_conversation_store
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

    # 对话持久化存储（提前初始化，sidebar 重置按钮会用到）
    conv_store = get_conversation_store()

    # 用户标识（每个浏览器 Tab 独立，互不干扰）
    if "user_token" not in st.session_state:
        st.session_state["user_token"] = uuid.uuid4().hex[:12]

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

        # 多 Agent 模式开关
        st.divider()
        agent_mode = st.radio(
            "🧠 Agent 模式",
            ["单 Agent（工具+Skill）", "多 Agent 协作（Supervisor）"],
            help=(
                "单 Agent：一个 Agent 管理所有工具和 Skill，适合简单问答\n"
                "多 Agent：Supervisor 自动识别意图并分发给专业 Agent，"
                "适合复杂多步骤任务"
            ),
        )
        use_multi_agent = agent_mode.startswith("多 Agent")

        st.divider()
        st.caption("Agent 会自动根据你的提问选择合适的工具。")

        tool_list = "RAG检索、用户数据、外部记录"
        if use_mcp:
            tool_list += "、高德定位、高德天气"
        st.caption(f"可用工具：{tool_list}")

        if st.button("🔄 重置会话"):
            # 删除 Chroma 中的旧会话，生成新 ID
            conv_store.delete_session(
                st.session_state.get("session_id", ""),
                user_token=st.session_state["user_token"],
            )
            st.session_state["session_id"] = uuid.uuid4().hex[:12]
            st.session_state["message"] = []
            st.session_state["persisted_count"] = 0
            st.rerun()

        # ---- 历史会话列表 ----
        st.divider()
        with st.expander("📜 历史会话", expanded=False):
            all_sessions = conv_store.list_sessions(
                user_token=st.session_state["user_token"]
            )
            current_sid = st.session_state.get("session_id", "")
            if not all_sessions:
                st.caption("暂无历史会话")
            else:
                for s in all_sessions:
                    sid = s["session_id"]
                    count = s["message_count"]
                    is_current = sid == current_sid
                    msgs = conv_store.get_session_history(
                        sid, user_token=st.session_state["user_token"]
                    )
                    preview = ""
                    for m in msgs:
                        if m["role"] == "user":
                            preview = m["content"][:30]
                            break
                    label = (
                        f"{'📍 当前' if is_current else '💬'} {preview}...（{count}条）"
                        if preview
                        else f"{'📍 当前' if is_current else '💬'} 会话 {sid[:8]}（{count}条）"
                    )
                    if is_current:
                        st.caption(label)
                    elif st.button(label, key=f"load_{sid}", use_container_width=True):
                        st.session_state["message"] = msgs
                        st.session_state["session_id"] = sid
                        st.session_state["persisted_count"] = len(msgs)
                        st.rerun()
                    if not is_current and st.button(
                        "🗑️", key=f"del_{sid}", help=f"删除会话 {sid[:8]}"
                    ):
                        conv_store.delete_session(
                            sid, user_token=st.session_state["user_token"]
                        )
                        st.rerun()

    # ---- 初始化 Agent（首次加载或配置变更时重建） ----
    cache_key = f"agent_{active_skill}_{auto_match}_{use_mcp}_{use_multi_agent}"
    if st.session_state.get("agent_key") != cache_key:
        mcp_tools = _load_mcp_tools() if use_mcp else None

        if use_multi_agent:
            st.session_state["agent"] = MultiAgentOrchestrator(mcp_tools=mcp_tools)
        else:
            st.session_state["agent"] = SmartAgent(
                mcp_tools=mcp_tools,
                active_skill=active_skill,
                auto_match_skill=auto_match,
            )
        st.session_state["agent_key"] = cache_key

    # ---- 会话管理：从 Chroma 加载/持久化对话历史 ----
    user_token = st.session_state["user_token"]

    # 初始化会话 ID：优先恢复最近会话，否则创建新会话
    if "session_id" not in st.session_state:
        recent = conv_store.list_sessions(user_token=user_token)
        if recent:
            st.session_state["session_id"] = recent[0]["session_id"]
        else:
            st.session_state["session_id"] = uuid.uuid4().hex[:12]

    if "message" not in st.session_state:
        st.session_state["message"] = conv_store.get_session_history(
            st.session_state["session_id"], user_token=user_token
        )

    # 已持久化的消息条数（用于增量写入）
    if "persisted_count" not in st.session_state:
        st.session_state["persisted_count"] = len(st.session_state["message"])

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
            # 传入完整对话历史，让 Agent 感知上下文
            history = st.session_state["message"]
            res_stream = st.session_state["agent"].execute_stream(
                prompt, history=history
            )

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

            # ---- 增量持久化到 Chroma ----
            persisted = st.session_state["persisted_count"]
            new_messages = st.session_state["message"][persisted:]
            for msg in new_messages:
                conv_store.add_message(
                    session_id=st.session_state["session_id"],
                    role=msg["role"],
                    content=msg["content"],
                    user_token=user_token,
                )
            st.session_state["persisted_count"] = len(st.session_state["message"])

            st.rerun()


if __name__ == "__main__":
    main()
