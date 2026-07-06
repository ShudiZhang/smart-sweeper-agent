"""
Query Rewriting — LLM 改写用户问题，提升检索召回率
"""

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import PromptTemplate

from model.factory import chat_model
from utils.logger_handler import logger

REWRITE_PROMPT = PromptTemplate.from_template(
    """你是一个搜索查询优化器。将用户的自然语言问题改写为更适合知识库检索的查询语句。

规则：
1. 提取核心关键词，去掉口语化表达
2. 补充同义词和相关术语（如"扫地机"→"扫地机器人/扫拖一体机器人"）
3. 如果是故障类问题，补充可能相关的故障现象关键词
4. 如果是选购类问题，补充产品参数维度（导航、吸力、续航等）
5. 只输出改写后的查询语句，不要解释

用户原始问题：{query}

改写后的检索查询："""
)


class QueryRewriter:
    """基于 LLM 的查询改写器"""

    def __init__(self):
        self.chain = REWRITE_PROMPT | chat_model | StrOutputParser()

    def rewrite(self, query: str) -> str:
        """改写用户查询，返回优化后的检索字符串"""
        try:
            rewritten = self.chain.invoke({"query": query})
            if rewritten and len(rewritten.strip()) > 3:
                logger.info(
                    f"[QueryRewriter] 「{query[:30]}」→ 「{rewritten.strip()[:50]}」"
                )
                return rewritten.strip()
        except Exception as e:
            logger.warning(f"[QueryRewriter] 改写失败: {e}")
        return query


# 单例
_query_rewriter: QueryRewriter | None = None


def get_query_rewriter() -> QueryRewriter:
    global _query_rewriter
    if _query_rewriter is None:
        _query_rewriter = QueryRewriter()
    return _query_rewriter
