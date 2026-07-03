"""LangSmith 追踪初始化 — 自动捕获 Agent 调用链、LLM 请求、工具执行"""

import os
from pathlib import Path

from utils.logger_handler import logger

# 加载 .env（确保 LANGCHAIN_API_KEY 等变量已就位）
_env_file = Path(__file__).resolve().parents[1] / ".env"
if _env_file.exists():
    with open(_env_file, encoding="utf-8") as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _v = _line.split("=", 1)
                os.environ.setdefault(_k.strip(), _v.strip().strip("\"'"))


def init_tracing() -> None:
    """
    初始化 LangSmith 追踪。
    设置环境变量 LANGCHAIN_API_KEY 后自动生效，无需额外代码。
    未设置 Key 时静默跳过，不影响正常运行。
    """
    api_key = os.getenv("LANGCHAIN_API_KEY", "")

    if not api_key:
        logger.info("[Tracing] 未设置 LANGCHAIN_API_KEY，跳过追踪初始化")
        return

    # LangChain 自动读取以下环境变量，无需额外配置
    os.environ.setdefault("LANGCHAIN_TRACING_V2", "true")
    os.environ.setdefault("LANGCHAIN_PROJECT", "smart-sweeper-agent")

    logger.info(
        f"[Tracing] LangSmith 追踪已启用，项目: {os.environ['LANGCHAIN_PROJECT']}"
    )
