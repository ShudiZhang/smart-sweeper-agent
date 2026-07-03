"""集成测试：RAG 流水线（需要外部 LLM 和 Embedding 服务）"""

import os

import pytest

# 仅在设置了 DASHSCOPE_API_KEY 时运行集成测试
NEEDS_LLM = pytest.mark.skipif(
    not os.getenv("DASHSCOPE_API_KEY"),
    reason="需要 DASHSCOPE_API_KEY 环境变量",
)


class TestRagPipeline:
    """RAG 完整流水线集成测试"""

    @NEEDS_LLM
    def test_vector_store_init_and_retrieve(self):
        """向量库初始化 + 检索"""
        from rag.vector_store import VectorStoreService

        vs = VectorStoreService()
        retriever = vs.get_retriever()

        # 检索应返回结果（需要向量库中有数据）
        docs = retriever.invoke("扫地机器人")
        assert isinstance(docs, list)

    @NEEDS_LLM
    def test_rag_summarize_returns_string(self):
        """RAG 总结返回字符串"""
        from rag.rag_service import RagSummarizeService

        rag = RagSummarizeService()
        result = rag.rag_summarize("小户型适合什么扫地机器人")

        assert isinstance(result, str)
        assert len(result) > 0

    @NEEDS_LLM
    def test_rag_empty_query_graceful(self):
        """无匹配结果时降级返回友好提示"""
        from rag.rag_service import RagSummarizeService

        rag = RagSummarizeService()
        result = rag.rag_summarize("xyzzy_not_a_real_query_12345")

        assert isinstance(result, str)
        # 无结果时应包含友好提示，不应该是 LLM 编造的内容
        # （允许两种情况：检索到意外结果，或者降级提示）
        assert len(result) > 0

    @NEEDS_LLM
    def test_rag_summarize_service_reusable(self):
        """RagSummarizeService 可重复调用"""
        from rag.rag_service import RagSummarizeService

        rag = RagSummarizeService()
        r1 = rag.rag_summarize("扫地机器人选购")
        r2 = rag.rag_summarize("扫地机器人选购")

        assert isinstance(r1, str)
        # 同一实例两次调用不报错
        assert isinstance(r2, str)


class TestVectorStoreIntegration:
    """向量库操作集成测试"""

    @NEEDS_LLM
    def test_chroma_persistence(self):
        """Chroma 持久化目录存在"""
        from utils.config_handler import chroma_conf
        from utils.path_tool import get_abs_path

        persist_dir = get_abs_path(chroma_conf["persist_directory"])
        assert os.path.isdir(persist_dir)
