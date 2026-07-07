"""
混合检索器：BM25（稀疏/关键词） + 向量（稠密/语义） → RRF 融合
================================================================
Dense（语义匹配）擅长理解同义改写，但对专有名词/型号/代码等精确匹配弱。
Sparse（关键词匹配）擅长精确匹配，但对语义改写不敏感。
RRF（Reciprocal Rank Fusion）融合两者，互补优势。
"""

import re

from langchain_chroma import Chroma
from langchain_core.documents import Document
from rank_bm25 import BM25Okapi

from utils.logger_handler import logger


class HybridRetriever:
    """混合检索器：BM25 + 向量 → RRF 融合去重"""

    def __init__(self, vector_store: Chroma, documents: list[Document]):
        """
        Args:
            vector_store: Chroma 向量库实例
            documents: 全部文档块（与向量库同步），用于构建 BM25 索引
        """
        self._vector_store = vector_store
        self._build_bm25(documents)

    # ---- BM25 索引构建 ----

    def _build_bm25(self, documents: list[Document]) -> None:
        """构建 BM25 稀疏检索索引"""
        self._bm25_docs = documents
        tokenized = [self._tokenize(doc.page_content) for doc in documents]
        self._bm25 = BM25Okapi(tokenized)
        logger.info(f"[HybridRetriever] BM25 索引就绪，文档数={len(documents)}")

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        """中文按单字切分 + 英文/数字按词切分，适配 BM25"""
        tokens: list[str] = []
        for match in re.finditer(r"[\u4e00-\u9fff]|[a-zA-Z]+|\d+", text):
            tokens.append(match.group())
        return tokens

    # ---- 融合检索 ----

    def retrieve(
        self,
        query: str,
        vector_k: int = 9,
        bm25_k: int = 9,
        rrf_k: int = 60,
    ) -> list[Document]:
        """混合检索：BM25 + 向量 → RRF 融合

        Args:
            query: 检索查询
            vector_k: 向量召回数量
            bm25_k: BM25 召回数量
            rrf_k: RRF 平滑参数（通常 60）

        Returns:
            融合去重后的文档列表（按 RRF 分数降序）
        """
        # ---- 1. BM25 关键词召回 ----
        tokenized = self._tokenize(query)
        bm25_scores = self._bm25.get_scores(tokenized)
        bm25_ranked = sorted(enumerate(bm25_scores), key=lambda x: x[1], reverse=True)[
            :bm25_k
        ]

        # ---- 2. 向量语义召回 ----
        vector_docs: list[Document] = self._vector_store.similarity_search(
            query, k=vector_k
        )

        # ---- 3. RRF 融合 ----
        fused = self._rrf_fusion(bm25_ranked, vector_docs, k=rrf_k)

        logger.info(
            f"[HybridRetriever] BM25={len(bm25_ranked)} + "
            f"Vector={len(vector_docs)} → Fusion={len(fused)}"
        )
        return fused

    def _rrf_fusion(
        self,
        bm25_ranked: list[tuple[int, float]],
        vector_docs: list[Document],
        k: int = 60,
    ) -> list[Document]:
        """RRF 融合：合并两个排序列表，按 RRF 分数降序

        公式: RRF(d) = Σ 1/(k + rank_i(d))
        - 同一文档出现在两个列表中时分数累加
        - 以 page_content 全文作为去重键（chunk ~200 字，可接受）
        """
        scores: dict[str, float] = {}
        doc_map: dict[str, Document] = {}

        # BM25 贡献
        for rank, (idx, _) in enumerate(bm25_ranked):
            doc = self._bm25_docs[idx]
            key = doc.page_content  # 全文去重
            scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank + 1)
            doc_map[key] = doc

        # 向量贡献
        for rank, doc in enumerate(vector_docs):
            key = doc.page_content
            scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank + 1)
            doc_map[key] = doc

        # 按 RRF 分数降序
        sorted_keys = sorted(scores, key=scores.get, reverse=True)
        return [doc_map[key] for key in sorted_keys]
