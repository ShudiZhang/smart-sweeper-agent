"""
RAG 总结服务：Query Rewriting → 混合检索 → LLM Rerank → 总结回复
========================================================================
管线：
  用户问题 → InputGuard 安检 → QueryRewriter 改写 → Chroma 多召回
  → LLMReranker 重排序 → LLM 总结 → OutputGuard 事实校验
"""

from langchain_core.documents import Document
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import PromptTemplate

from model.factory import chat_model
from rag.query_rewriter import get_query_rewriter
from rag.reranker import get_reranker
from rag.vector_store import VectorStoreService
from utils.config_handler import get_config
from utils.guardrails import GuardAction, get_input_guard, get_output_guard
from utils.logger_handler import logger
from utils.prompt_loader import load_rag_prompts


def _debug_prompt(prompt):
    """调试用：仅在 DEBUG 级别时输出完整 prompt 内容"""
    logger.debug("=" * 20)
    logger.debug(prompt.to_string())
    logger.debug("=" * 20)
    return prompt


class RagSummarizeService:
    """RAG 总结服务 — 集成 Query Rewriting + Re-rank 的增强检索管线"""

    def __init__(self):
        self.vector_store = VectorStoreService()
        self.retriever = self.vector_store.get_retriever()
        self.prompt_text = load_rag_prompts()
        self.prompt_template = PromptTemplate.from_template(self.prompt_text)
        self.model = chat_model
        self.chain = self._init_chain()

        # 增强组件（懒加载）
        self._rewriter = None
        self._reranker = None

        # 配置
        cfg = get_config()
        self._search_k = getattr(cfg.chroma, "k", 3)  # 最终返回数
        self._candidate_k = self._search_k * 3  # 召回候选数（用于 rerank）

    def _init_chain(self):
        chain = self.prompt_template | _debug_prompt | self.model | StrOutputParser()
        return chain

    @property
    def rewriter(self):
        if self._rewriter is None:
            self._rewriter = get_query_rewriter()
        return self._rewriter

    @property
    def reranker(self):
        if self._reranker is None:
            self._reranker = get_reranker()
        return self._reranker

    def retriever_docs(self, query: str) -> list[Document]:
        """基础检索：从 Chroma 向量库检索（不带增强）"""
        return self.retriever.invoke(query)

    def enhanced_retrieve(self, query: str) -> list[Document]:
        """增强检索管线：Rewrite → 多召回 → Rerank

        Args:
            query: 用户原始问题

        Returns:
            重排序后的 Top-K 相关文档
        """
        # Step 1: Query Rewriting — 将口语化问题改写为检索友好的查询
        rewritten_query = self.rewriter.rewrite(query)

        # Step 2: 多召回 — 扩大候选池（最终 K 的 3 倍）
        candidates = self.vector_store.vector_store.similarity_search(
            rewritten_query, k=self._candidate_k
        )

        if not candidates:
            # 改写后仍无结果，尝试原查询
            candidates = self.vector_store.vector_store.similarity_search(
                query, k=self._candidate_k
            )

        if not candidates:
            logger.warning(f"[RAG] 检索为空，query={query[:50]}")
            return []

        # Step 3: LLM Re-rank — 从候选池中精选最相关的 Top-K
        ranked = self.reranker.rerank(rewritten_query, candidates, self._search_k)

        return ranked

    def rag_summarize(self, query: str) -> str:
        """执行完整 RAG 管线：安检 → 增强检索 → 总结 → 事实校验

        Args:
            query: 用户原始问题

        Returns:
            基于检索资料的总结回答（已过安全护栏）
        """
        # ---- Input Guard: 输入安全检测 ----
        input_guard = get_input_guard()
        guard_result = input_guard.check(query)
        if guard_result.action == GuardAction.BLOCK:
            logger.warning(f"[RAG] 输入被拦截: {guard_result.reason}")
            return f"抱歉，{guard_result.reason}。如有疑问请联系人工客服。"

        # ---- 增强检索 ----
        context_docs = self.enhanced_retrieve(query)

        # 检索为空时降级，避免 LLM 基于空上下文编造答案
        if not context_docs:
            logger.warning(f"[RAG] 增强检索无结果，query={query[:50]}")
            return (
                "抱歉，当前知识库中暂无与您问题相关的资料。"
                "建议您换个方式提问，或联系人工客服获取帮助。"
            )

        context = ""
        for i, doc in enumerate(context_docs, 1):
            context += (
                f"【参考资料{i}】: {doc.page_content} "
                f"| 参考元数据：{doc.metadata}\n"
            )

        answer = self.chain.invoke(
            {
                "input": query,
                "context": context,
            }
        )

        # ---- Output Guard: 事实一致性校验 ----
        output_guard = get_output_guard()
        fact_check = output_guard.check(answer, context_docs)
        if fact_check.action == GuardAction.WARN:
            # 追加免责声明
            answer += (
                "\n\n⚠️ 温馨提示：以上部分信息可能需要进一步核实，"
                "建议以产品说明书或官方客服为准。"
            )
        elif fact_check.action == GuardAction.BLOCK:
            return "抱歉，当前无法生成可靠回答，请稍后重试或联系人工客服。"

        return answer


if __name__ == "__main__":
    rag = RagSummarizeService()

    print("=== RAG 增强检索测试 ===\n")
    for q in [
        "小户型适合哪些扫地机器人",
        "机器人一直滴滴响不动了",
    ]:
        print(f"Q: {q}")
        print(f"A: {rag.rag_summarize(q)[:200]}...\n")
