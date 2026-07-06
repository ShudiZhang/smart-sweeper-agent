"""
LLM Re-Ranker — 用大模型对检索结果重排序，提升 Top-K 精度
"""

from langchain_core.documents import Document
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import PromptTemplate

from model.factory import chat_model
from utils.logger_handler import logger

RERANK_PROMPT = PromptTemplate.from_template(
    """你是一个文档相关性评分器。根据用户问题，对以下候选文档逐一打分。

用户问题：{query}

候选文档：
{documents}

评分规则：
- 3分：直接相关，包含用户需要的具体信息
- 2分：部分相关，涉及相关领域但不够精准
- 1分：弱相关，仅提到关键词但未深入
- 0分：无关

请严格按以下格式输出，每行一个：
文档编号:分数

只输出评分，不要解释。"""
)


class LLMReranker:
    """基于 LLM 的文档重排序器"""

    def __init__(self):
        self.chain = RERANK_PROMPT | chat_model | StrOutputParser()

    def rerank(
        self, query: str, docs: list[Document], top_k: int = 3
    ) -> list[Document]:
        """对候选文档重排序，返回 Top-K 最相关文档

        Args:
            query: 用户查询
            docs: 候选文档列表（建议 5-10 个）
            top_k: 返回数量

        Returns:
            重排序后的 Top-K 文档
        """
        if len(docs) <= top_k:
            return docs

        # 构建候选文档列表
        docs_text = ""
        for i, doc in enumerate(docs):
            docs_text += f"文档{i + 1}: {doc.page_content[:200]}\n"

        try:
            response = self.chain.invoke(
                {
                    "query": query,
                    "documents": docs_text,
                }
            )

            # 解析评分
            scores = self._parse_scores(response, len(docs))
            if not scores:
                logger.warning("[Reranker] 评分解析失败，返回原始排序")
                return docs[:top_k]

            # 按分数降序排列
            scored_docs = list(zip(scores, docs))
            scored_docs.sort(key=lambda x: x[0], reverse=True)

            # 输出重排序日志
            top_scores = [s for s, _ in scored_docs[:top_k]]
            logger.info(
                f"[Reranker] Top-{top_k} 分数: {top_scores}, " f"原始候选: {len(docs)}"
            )

            return [doc for _, doc in scored_docs[:top_k]]

        except Exception as e:
            logger.warning(f"[Reranker] 重排序失败: {e}")
            return docs[:top_k]

    @staticmethod
    def _parse_scores(response: str, doc_count: int) -> list[float]:
        """从 LLM 响应中解析文档评分"""
        scores = [0.0] * doc_count
        for line in response.strip().split("\n"):
            line = line.strip()
            if ":" in line or "：" in line:
                # 分隔符可能是中英文冒号
                sep = ":" if ":" in line else "："
                parts = line.split(sep, 1)
                try:
                    # 提取文档编号
                    num_str = parts[0].strip()
                    num_str = "".join(c for c in num_str if c.isdigit())
                    idx = int(num_str) - 1
                    if 0 <= idx < doc_count:
                        score_str = parts[1].strip()
                        score_str = "".join(
                            c for c in score_str if c.isdigit() or c == "."
                        )
                        scores[idx] = float(score_str)
                except (ValueError, IndexError):
                    continue
        return scores


# 单例
_reranker: LLMReranker | None = None


def get_reranker() -> LLMReranker:
    global _reranker
    if _reranker is None:
        _reranker = LLMReranker()
    return _reranker
