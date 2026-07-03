"""测试 utils/config_handler.py"""

from pathlib import Path

import pytest
import yaml

from utils.config_handler import (
    AgentConfig,
    AppConfig,
    ChromaConfig,
    PromptsConfig,
    RAGConfig,
    get_config,
)


class TestConfigModels:
    """Pydantic 配置模型测试"""

    def test_chroma_config_defaults(self):
        c = ChromaConfig()
        assert c.collection_name == "agent"
        assert c.k == 3
        assert c.chunk_size == 200

    def test_chroma_config_custom(self):
        c = ChromaConfig(collection_name="test", k=5)
        assert c.collection_name == "test"
        assert c.k == 5
        assert c.chunk_size == 200  # 未指定的保持默认

    def test_chroma_overlap_must_be_less_than_chunk(self):
        """校验：chunk_overlap 必须小于 chunk_size"""
        with pytest.raises(ValueError, match="chunk_overlap"):
            ChromaConfig(chunk_size=100, chunk_overlap=100)

    def test_chroma_k_must_be_positive(self):
        """校验：k 必须 >= 1"""
        with pytest.raises(ValueError):
            ChromaConfig(k=0)

    def test_rag_config_defaults(self):
        c = RAGConfig()
        assert c.chat_model_name == "qwen3-max"

    def test_rag_empty_model_name_rejected(self):
        """校验：模型名不能为空"""
        with pytest.raises(ValueError):
            RAGConfig(chat_model_name="")

    def test_dict_style_access_backward_compat(self):
        """验证旧的 dict 方式访问仍然可用"""
        c = ChromaConfig(collection_name="test", k=10)
        assert c["collection_name"] == "test"
        assert c["k"] == 10

    def test_agent_config_default(self):
        c = AgentConfig()
        assert c["external_data_path"] == "data/external/records.csv"

    def test_prompts_config_default(self):
        c = PromptsConfig()
        assert c["main_prompt_path"] == "prompts/main_prompt.txt"


class TestAppConfig:
    """AppConfig 测试"""

    def test_default_construction(self):
        cfg = AppConfig()
        assert cfg.chroma.collection_name == "agent"
        assert cfg.rag.chat_model_name == "qwen3-max"

    def test_from_yaml_partial_override(self, tmp_path: Path):
        """YAML 只覆盖部分字段时，其余用默认值"""
        chroma_yml = tmp_path / "chroma.yml"
        chroma_yml.write_text(
            "collection_name: my_collection\nk: 10\n", encoding="utf-8"
        )

        rag_yml = tmp_path / "rag.yml"
        rag_yml.write_text("chat_model_name: test-model\n", encoding="utf-8")

        agent_yml = tmp_path / "agent.yml"
        agent_yml.write_text("external_data_path: custom/path.csv\n", encoding="utf-8")

        prompts_yml = tmp_path / "prompts.yml"
        prompts_yml.write_text(
            "main_prompt_path: custom/prompt.txt\n", encoding="utf-8"
        )

        # 通过直接构造 dict 来模拟 from_yaml 的行为
        chroma_dict = yaml.load(chroma_yml.read_text(), Loader=yaml.FullLoader)
        c = ChromaConfig(**chroma_dict)
        assert c.collection_name == "my_collection"
        assert c.k == 10
        # 未覆盖的用默认值
        assert c.chunk_size == 200

    def test_get_config_returns_same_instance(self):
        """get_config 是单例"""
        # get_config 缓存了真实 YAML 加载的结果，多次调用返回同一实例
        cfg1 = get_config()
        cfg2 = get_config()
        assert cfg1 is cfg2
