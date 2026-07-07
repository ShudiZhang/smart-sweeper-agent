"""配置管理 - 基于 Pydantic v2 的类型安全配置，支持懒加载 + 字段校验"""

from functools import lru_cache
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator

from utils.path_tool import get_abs_path


class ChromaConfig(BaseModel):
    """Chroma 向量库配置"""

    collection_name: str = "agent"
    persist_directory: str = "chroma_db"
    k: int = Field(default=3, ge=1, le=100, description="检索返回文档数")
    chunk_size: int = Field(default=600, ge=50, le=5000, description="文本分片大小")
    chunk_overlap: int = Field(default=20, ge=0, le=500, description="分片重叠大小")
    separators: list[str] = Field(
        default_factory=lambda: ["\n\n", "\n", ".", "!", "?", "。", "！", "？", " ", ""]
    )
    data_path: str = "data"
    md5_hex_store: str = "md5.text"
    allow_knowledge_file_type: list[str] = Field(default_factory=lambda: ["txt", "pdf"])

    @field_validator("chunk_overlap")
    @classmethod
    def overlap_less_than_chunk(cls, v: int, info: Any) -> int:
        """重叠大小不能超过分片大小"""
        chunk_size = info.data.get("chunk_size", 200)
        if v >= chunk_size:
            raise ValueError(f"chunk_overlap({v}) 必须小于 chunk_size({chunk_size})")
        return v

    def __getitem__(self, key: str) -> Any:
        """兼容旧的 dict 方式访问: chroma_conf['collection_name']"""
        return getattr(self, key)


class RAGConfig(BaseModel):
    """RAG 模型配置"""

    chat_model_name: str = Field(default="qwen3-max", min_length=1)
    embedding_model_name: str = Field(default="text-embedding-v4", min_length=1)

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)


class AgentConfig(BaseModel):
    """Agent 配置"""

    external_data_path: str = "data/external/records.csv"

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)


class PromptsConfig(BaseModel):
    """提示词路径配置"""

    main_prompt_path: str = "prompts/main_prompt.txt"
    rag_summarize_prompt_path: str = "prompts/rag_summarize.txt"
    report_prompt_path: str = "prompts/report_prompt.txt"

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)


class AppConfig(BaseModel):
    """应用总配置"""

    chroma: ChromaConfig = Field(default_factory=ChromaConfig)
    rag: RAGConfig = Field(default_factory=RAGConfig)
    agent: AgentConfig = Field(default_factory=AgentConfig)
    prompts: PromptsConfig = Field(default_factory=PromptsConfig)

    @classmethod
    def from_yaml(cls) -> "AppConfig":
        """从 YAML 文件加载配置，Pydantic 自动校验"""

        def _load(rel_path: str) -> dict:
            with open(get_abs_path(rel_path), encoding="utf-8") as f:
                return yaml.load(f, Loader=yaml.FullLoader) or {}

        return cls(
            chroma=ChromaConfig(**_load("config/chroma.yml")),
            rag=RAGConfig(**_load("config/rag.yml")),
            agent=AgentConfig(**_load("config/agent.yml")),
            prompts=PromptsConfig(**_load("config/prompts.yml")),
        )


@lru_cache(maxsize=1)
def get_config() -> AppConfig:
    """获取应用配置（懒加载单例，首次调用时从 YAML 读取并校验）"""
    return AppConfig.from_yaml()


# ---- 向后兼容：模块级变量通过 __getattr__ 延迟加载 ----

_config: AppConfig | None = None


def _ensure_config() -> AppConfig:
    global _config
    if _config is None:
        _config = get_config()
    return _config


def __getattr__(name: str) -> Any:
    cfg = _ensure_config()
    mapping = {
        "chroma_conf": cfg.chroma,
        "rag_conf": cfg.rag,
        "agent_conf": cfg.agent,
        "prompts_conf": cfg.prompts,
    }
    if name in mapping:
        return mapping[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


if __name__ == "__main__":
    cfg = get_config()
    print(f"模型: {cfg.rag.chat_model_name}")
    print(f"检索 top_k: {cfg.chroma.k}")
    print(f"分片大小: {cfg.chroma.chunk_size}")
