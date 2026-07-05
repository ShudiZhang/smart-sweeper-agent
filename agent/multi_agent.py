"""
多 Agent 协作架构：Supervisor-Worker 模式
==========================================
基于 LangGraph StateGraph 实现：
  Supervisor（调度器）→ 意图分类 → 路由分发 → Worker Agent（专业执行）

4 个专业 Worker：
  - troubleshooting: 故障排查（RAG 检索 + 诊断引导）
  - purchase:       选购推荐（RAG 检索 + 对比分析）
  - report:         报告生成（多工具串联：用户ID→月份→使用记录→报告）
  - general:        通用问答（RAG + 天气 + 定位）
"""

from __future__ import annotations

from typing import Annotated

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import create_react_agent
from typing_extensions import TypedDict

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
from utils.logger_handler import logger

# ============================================================
# Worker 配置：每个 Worker 有独立的 System Prompt 和工具集
# ============================================================

WORKER_CONFIG: dict[str, dict] = {
    "troubleshooting": {
        "label": "故障排查专家",
        "system_prompt": (
            "你是扫地机器人故障排查专家。"
            "请根据知识库检索结果，逐步引导用户排查设备故障：\n"
            "1. 先确认故障现象，追问必要细节（如型号、使用时长、错误提示）\n"
            "2. 逐一排除可能原因，从简单到复杂\n"
            "3. 给出具体可操作的操作步骤\n"
            "4. 若无法解决，建议联系售后"
        ),
        "tools": [rag_summarize],
    },
    "purchase": {
        "label": "选购顾问",
        "system_prompt": (
            "你是扫地机器人选购顾问。"
            "请根据用户的户型大小、预算范围、是否养宠、地面类型（木地板/地毯/瓷砖）"
            "等需求，从知识库中匹配合适的机型，并：\n"
            "1. 给出 2-3 款推荐型号及理由\n"
            "2. 对比不同型号的核心差异（导航方式、吸力、续航、避障等）\n"
            "3. 结合用户具体情况给出最终建议"
        ),
        "tools": [rag_summarize],
    },
    "report": {
        "label": "报告生成专家",
        "system_prompt": (
            "你是使用报告生成专家。请依次执行以下步骤生成月度报告：\n"
            "1. 调用 get_user_id 获取用户ID\n"
            "2. 调用 get_current_month 获取当前月份\n"
            "3. 调用 fetch_external_data 获取该用户当月使用记录\n"
            "4. 调用 fill_context_for_report 切换到报告模式\n"
            "5. 根据数据生成结构化报告，包含：使用天数、清洁面积、"
            "故障次数、耗材状态、使用建议"
        ),
        "tools": [
            get_user_id,
            get_current_month,
            fetch_external_data,
            fill_context_for_report,
        ],
    },
    "general": {
        "label": "通用助手",
        "system_prompt": (
            "你是扫地机器人通用客服助手。"
            "回答用户关于产品使用、维护保养、配件知识等各类问题。"
            "可查询用户ID、当前时间、天气、定位等信息，为用户提供更贴心的服务。"
        ),
        "tools": [
            rag_summarize,
            get_weather,
            get_user_location,
            get_user_id,
            get_current_month,
        ],
    },
}

# Supervisor 的分类提示词
SUPERVISOR_SYSTEM_PROMPT = """你是智能路由调度器（Supervisor），负责将用户问题精准分发给最合适的专业 Agent。

分发规则：
- troubleshooting: 设备故障、报错、异响、不工作、连不上、充不进电、吸力下降、漏水、找不到充电座等异常
- purchase: 选购推荐、型号对比、性价比、哪个好、值不值得、预算推荐、产品咨询
- report: 使用报告、月度统计、使用记录、生成报告、我的使用情况
- general: 天气、定位、闲聊、维护保养常识、配件知识、产品功能询问等以上无法归类的问题

严格只回复 Agent 名称（troubleshooting / purchase / report / general），不要添加任何解释。"""


# ============================================================
# 工具函数
# ============================================================


def _build_context_messages(
    history: list[dict] | None, query: str
) -> list[HumanMessage | AIMessage]:
    """将历史对话 + 当前问题构建为 LangChain 消息列表"""
    messages: list[HumanMessage | AIMessage] = []
    if history:
        for msg in history:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if role == "user":
                messages.append(HumanMessage(content=content))
            elif role == "assistant":
                messages.append(AIMessage(content=content))
    messages.append(HumanMessage(content=query))
    return messages


# ============================================================
# State
# ============================================================


class MultiAgentState(TypedDict):
    messages: Annotated[list, add_messages]
    next_agent: str  # Supervisor 路由决策结果


# ============================================================
# MultiAgentOrchestrator
# ============================================================


class MultiAgentOrchestrator:
    """Supervisor-Worker 多 Agent 编排器

    工作流程：
        User Query → Supervisor（意图分类）→ 条件路由 → Worker（ReAct 执行）→ 最终回答
    """

    def __init__(self, mcp_tools: list | None = None):
        self._workers: dict[str, any] = {}
        self._build_workers(mcp_tools)
        self.graph = self._build_graph()
        logger.info(
            f"[MultiAgent] 编排器初始化完成，" f"Workers={list(self._workers.keys())}"
        )

    # ---- Worker 构建 ----

    def _build_workers(self, mcp_tools: list | None):
        """为每个专业领域构建独立的 ReAct Agent"""
        for name, config in WORKER_CONFIG.items():
            tools = list(config["tools"])
            # MCP 工具（天气/定位）挂载到 general worker
            if mcp_tools and name == "general":
                tools.extend(mcp_tools)

            self._workers[name] = create_react_agent(
                model=chat_model,
                tools=tools,
                prompt=config["system_prompt"],
            )
            logger.info(
                f"[MultiAgent] Worker '{name}' ({config['label']}) 已就绪，"
                f"工具数={len(tools)}"
            )

    # ---- Graph 构建 ----

    def _build_graph(self) -> StateGraph:
        """构建 Supervisor → Workers 的 StateGraph"""
        workflow = StateGraph(MultiAgentState)

        # 节点
        workflow.add_node("supervisor", self._supervisor_node)
        for name in WORKER_CONFIG:
            workflow.add_node(name, self._make_worker_node(name))

        # 入口
        workflow.set_entry_point("supervisor")

        # Supervisor → 条件路由 → Worker
        route_map = {name: name for name in WORKER_CONFIG}
        workflow.add_conditional_edges("supervisor", self._route_to_worker, route_map)

        # Worker → END
        for name in WORKER_CONFIG:
            workflow.add_edge(name, END)

        return workflow.compile()

    # ---- Supervisor Node ----

    def _supervisor_node(self, state: MultiAgentState) -> dict:
        """Supervisor：分析用户意图，输出路由决策"""
        messages = state["messages"]

        # 提取最后一条用户消息
        user_query = ""
        for msg in reversed(messages):
            if isinstance(msg, HumanMessage):
                user_query = str(msg.content)
                break

        if not user_query:
            return {"next_agent": "general"}

        # LLM 意图分类
        classification_messages = [
            SystemMessage(content=SUPERVISOR_SYSTEM_PROMPT),
            HumanMessage(content=f"用户问题：{user_query}"),
        ]
        response = chat_model.invoke(classification_messages)
        agent_name = response.content.strip().lower() if response.content else ""

        # 规范化 & 降级
        if agent_name not in WORKER_CONFIG:
            logger.warning(
                f"[Supervisor] 模型返回无效路由 '{agent_name}'，降级为 general"
            )
            agent_name = "general"

        logger.info(
            f"[Supervisor] 「{user_query[:40]}」→ {agent_name} ({WORKER_CONFIG[agent_name]['label']})"
        )

        # 内部提示消息（不展示给用户）
        route_msg = AIMessage(
            content=(
                f"[系统] 已自动分配至【{WORKER_CONFIG[agent_name]['label']}】"
                f"处理您的问题"
            )
        )
        return {"messages": [route_msg], "next_agent": agent_name}

    # ---- 条件路由 ----

    def _route_to_worker(self, state: MultiAgentState) -> str:
        """条件边：读取 Supervisor 的路由决策"""
        return state.get("next_agent", "general")

    # ---- Worker Node Factory ----

    def _make_worker_node(self, name: str):
        """创建 Worker 节点：封装子 Agent 的完整 ReAct 执行"""
        sub_agent = self._workers[name]

        def worker_node(state: MultiAgentState):
            # 过滤：只保留用户消息和非路由 AI 消息
            user_messages = [
                m
                for m in state["messages"]
                if isinstance(m, HumanMessage)
                or (
                    isinstance(m, AIMessage)
                    and not (m.content or "").startswith("[系统]")
                )
            ]

            logger.info(f"[Worker:{name}] 开始执行，上下文消息数={len(user_messages)}")

            # 调用子 Agent（完整 ReAct 循环：Thought → Tool Call → Observation → Answer）
            try:
                result = sub_agent.invoke(
                    {"messages": user_messages},
                    config={"recursion_limit": 25},
                )
            except Exception as e:
                logger.error(f"[Worker:{name}] 执行失败: {e}")
                return {
                    "messages": [
                        AIMessage(
                            content="抱歉，当前服务繁忙，请稍后重试。"
                            "如问题紧急，建议联系人工客服。"
                        )
                    ]
                }

            # 提取最终 AI 回复（排除含 tool_calls 的中间思考消息）
            final_messages = result.get("messages", [])
            ai_answers = [
                m
                for m in final_messages
                if isinstance(m, AIMessage) and not getattr(m, "tool_calls", None)
            ]

            if ai_answers:
                logger.info(
                    f"[Worker:{name}] 完成，回复长度={len(ai_answers[-1].content)}"
                )
                return {"messages": [ai_answers[-1]]}

            return {
                "messages": [
                    AIMessage(content="抱歉，我暂时无法回答这个问题，请换个方式提问。")
                ]
            }

        return worker_node

    # ---- 流式执行接口（兼容 SmartAgent） ----

    def execute_stream(self, query: str, history: list[dict] | None = None):
        """流式执行，与 SmartAgent 接口保持一致

        Args:
            query: 当前用户问题
            history: 可选，历史对话 [{"role": "user/assistant", "content": "..."}]

        Yields:
            仅产出最终 AI 回答的文本片段（隐藏 Supervisor 路由消息和工具调用过程）
        """
        # 构建完整上下文消息
        messages = _build_context_messages(history, query)
        state = {"messages": messages}

        for chunk in self.graph.stream(
            state,
            stream_mode="updates",
            config={"recursion_limit": 50},
        ):
            for node_name, node_output in chunk.items():
                # Supervisor 的路由消息不展示
                if node_name == "supervisor":
                    continue

                if not isinstance(node_output, dict):
                    continue

                messages = node_output.get("messages", [])
                for msg in (messages if isinstance(messages, list) else [messages]):
                    # 跳过工具调用消息
                    if hasattr(msg, "tool_calls") and msg.tool_calls:
                        continue
                    if getattr(msg, "type", None) == "tool":
                        continue

                    content = getattr(msg, "content", "")
                    # 过滤内部路由标识
                    if content and not content.startswith("[系统]"):
                        yield content.strip() + "\n"


# ============================================================
# 快速测试
# ============================================================

if __name__ == "__main__":
    import sys

    orchestrator = MultiAgentOrchestrator()

    test_queries = [
        ("故障排查", "机器人开机后滴滴响，不动了怎么办？"),
        ("选购推荐", "60平米小户型养猫，推荐哪款扫地机器人？"),
        ("报告生成", "帮我生成我的使用报告"),
        ("通用问答", "今天深圳天气怎么样？"),
    ]

    if len(sys.argv) > 1:
        # 单条测试
        query = sys.argv[1]
        print(f"\n{'='*50}")
        print(f"用户: {query}")
        print(f"{'='*50}")
        for chunk in orchestrator.execute_stream(query):
            print(chunk, end="", flush=True)
        print()
    else:
        # 全量测试
        for category, query in test_queries:
            print(f"\n{'='*50}")
            print(f"[{category}] 用户: {query}")
            print(f"{'='*50}")
            for chunk in orchestrator.execute_stream(query):
                print(chunk, end="", flush=True)
            print()
