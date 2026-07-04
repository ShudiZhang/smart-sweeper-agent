"""Agent Hooks — langgraph 1.0 pre_model_hook / prompt callable / tool wrapper"""

from __future__ import annotations

from functools import wraps
from typing import Any

from langchain_core.messages import HumanMessage
from langchain_core.tools import BaseTool

from utils.logger_handler import logger
from utils.prompt_loader import load_report_prompts, load_system_prompts
from utils.skill_loader import get_skill_manager

# ============================================================
# Prompt 动态构建（替代 dynamic_prompt 中间件）
# ============================================================


def build_prompt(state: dict) -> str:
    """
    动态构建 System Prompt。
    作为 create_react_agent 的 prompt 参数传入，每次模型调用前执行。
    """
    is_report = state.get("_report_mode", False)
    base_text = load_report_prompts() if is_report else load_system_prompts()

    # 注入 Skill
    manual_skill = state.get("_active_skill")
    auto_skills = state.get("_auto_skills", [])

    if manual_skill:
        base_text = get_skill_manager().inject(base_text, [manual_skill])
    elif auto_skills:
        base_text = get_skill_manager().inject(base_text, auto_skills)

    # 强制收敛：统计已执行的工具调用次数，超过阈值时注入停止指令
    messages = state.get("messages", [])
    tool_call_count = sum(
        1
        for m in messages
        if hasattr(m, "tool_call_id") or getattr(m, "type", None) == "tool"
    )
    max_tools = 5 if is_report else 3
    if tool_call_count >= max_tools:
        base_text += (
            f"\n\n⛔ 【强制停止】已调用 {tool_call_count} 次工具，禁止再调用任何工具。"
            "用 2-3 句话简洁回答用户。用自己的话总结，禁止直接复制工具返回的原文。"
        )

    return base_text


# ============================================================
# pre_model_hook：日志 + Skill 自动匹配
# ============================================================


def pre_model_hook(state: dict) -> dict:
    """
    模型调用前 Hook：
    1. 记录日志
    2. 首条用户消息时自动匹配 Skill
    返回 state 更新 dict。
    """
    messages = state.get("messages", [])
    logger.info(f"[pre_model_hook] 即将调用模型，消息数={len(messages)}")
    if messages:
        last = messages[-1]
        logger.debug(
            f"[pre_model_hook] {type(last).__name__} | {str(last.content)[:100]}"
        )

    updates: dict[str, Any] = {}

    # Skill 自动匹配（仅首次）
    if not state.get("_skill_matched") and not state.get("_active_skill"):
        user_query = ""
        for msg in messages:
            if isinstance(msg, HumanMessage):
                user_query = str(msg.content)
                break

        if user_query:
            manager = get_skill_manager()
            matched = manager.match(user_query, top_k=1)
            if matched:
                updates["_auto_skills"] = matched
                logger.info(f"[skill_auto_match] 自动匹配: {matched}")

        updates["_skill_matched"] = True

    return updates


# ============================================================
# 工具包装器（替代 wrap_tool_call 中间件）
# ============================================================

# fill_context_for_report 每次会话只能调一次
_fill_context_called = False


def _reset_tool_guards():
    """重置工具调用守卫（每次新会话时调用）"""
    global _fill_context_called
    _fill_context_called = False


def wrap_tool_with_monitor(tool: BaseTool) -> BaseTool:
    """
    包装单个工具，添加调用日志和调用次数限制。
    """
    original_func = tool.func

    @wraps(original_func)
    def monitored_func(*args: Any, **kwargs: Any) -> Any:
        global _fill_context_called
        tool_name = tool.name

        # fill_context_for_report 只能调一次
        if tool_name == "fill_context_for_report":
            if _fill_context_called:
                logger.warning(
                    "[tool monitor] fill_context_for_report 已调用过，拒绝重复调用"
                )
                return "该工具已调用过，无需重复调用。请继续执行后续步骤。"
            _fill_context_called = True

        logger.info(f"[tool monitor] 执行工具：{tool_name}")
        if kwargs:
            logger.info(f"[tool monitor] 传入参数：{kwargs}")
        try:
            result = original_func(*args, **kwargs)
            logger.info(f"[tool monitor] 工具 {tool_name} 调用成功")
            return result
        except Exception as e:
            logger.error(f"[tool monitor] 工具 {tool_name} 调用失败: {e}")
            raise

    return tool.model_copy(update={"func": monitored_func})


def wrap_tools_with_monitor(tools: list[BaseTool]) -> list[BaseTool]:
    """批量包装工具，添加监控"""
    return [wrap_tool_with_monitor(t) for t in tools]


# ============================================================
# post_model_hook：检测 report 模式切换
# ============================================================


def post_model_hook(state: dict) -> dict:
    """
    模型调用后 Hook：检测 fill_context_for_report 是否被调用。
    如果最后一条 ToolMessage 来自 fill_context_for_report，设置 _report_mode。
    """
    messages = state.get("messages", [])
    # 检查最近的 ToolMessage
    for msg in reversed(messages):
        if hasattr(msg, "name") and msg.name == "fill_context_for_report":
            logger.info(
                "[post_model_hook] 检测到 fill_context_for_report，切换到报告模式"
            )
            return {"_report_mode": True}
        # 如果遇到了 AIMessage 而不是 ToolMessage，说明没有新的 tool call
        if hasattr(msg, "tool_calls") or hasattr(msg, "type") and msg.type == "ai":
            break
    return {}
