"""模型工厂 - 懒加载单例，避免导入时即创建连接"""

from functools import lru_cache

from langchain_community.chat_models.tongyi import ChatTongyi
from langchain_community.embeddings import DashScopeEmbeddings

from utils.config_handler import get_config


@lru_cache(maxsize=1)
def get_chat_model() -> ChatTongyi:
    """获取对话模型（懒加载单例）"""
    cfg = get_config()
    return ChatTongyi(model=cfg.rag.chat_model_name)


@lru_cache(maxsize=1)
def get_embed_model() -> DashScopeEmbeddings:
    """获取嵌入模型（懒加载单例）"""
    cfg = get_config()
    return DashScopeEmbeddings(model=cfg.rag.embedding_model_name)


# 向后兼容：旧代码中 from model.factory import chat_model 仍可工作
def __getattr__(name: str):
    if name == "chat_model":
        return get_chat_model()
    if name == "embed_model":
        return get_embed_model()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
