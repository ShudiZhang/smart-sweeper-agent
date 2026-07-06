"""
RAG 质量评估指标（LLM-as-Judge）
===============================
基于 LLM 的自动化评估，无需额外依赖：
  - Faithfulness: 回答是否忠实于上下文（0-1）
  - Answer Relevancy: 回答是否切题（0-1）
  - Context Precision: 检索文档是否精准（0-1）
  - Overall: 综合得分

用法:
  uv run python tests/eval_metrics.py
"""

from __future__ import annotations

from dataclasses import dataclass, field

from langchain_core.documents import Document
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import PromptTemplate

from model.factory import chat_model
from utils.logger_handler import logger

# ============================================================
# 评估 Prompt
# ============================================================

FAITHFULNESS_PROMPT = PromptTemplate.from_template(
    """评估 AI 回答是否忠实于给定的上下文资料。

问题：{question}
上下文资料：
{context}
AI 回答：
{answer}

评分标准：
- 1.0: 回答的所有事实声明都直接来自上下文，无编造
- 0.7: 大部分基于上下文，有少量合理推断
- 0.4: 部分基于上下文，有较多未经证实的内容
- 0.0: 完全编造，与上下文无关

请严格只输出一个数字（0.0-1.0），不要解释："""
)

RELEVANCY_PROMPT = PromptTemplate.from_template("""评估 AI 回答是否直接回应了用户问题。

用户问题：{question}
AI 回答：{answer}

评分标准：
- 1.0: 完全回答了问题，信息充足且直接相关
- 0.7: 大部分回答了问题，但略有偏离或不够完整
- 0.4: 部分相关，但遗漏了关键信息或偏离主题
- 0.0: 完全答非所问

请严格只输出一个数字（0.0-1.0），不要解释：""")

PRECISION_PROMPT = PromptTemplate.from_template("""评估检索到的文档与用户问题的相关性。

用户问题：{question}
检索到的文档：
{documents}

评分标准：
- 1.0: 所有文档都与问题高度相关，包含需要的信息
- 0.7: 大部分文档相关，少量无关
- 0.4: 只有部分文档相关
- 0.0: 所有文档都不相关

请严格只输出一个数字（0.0-1.0），不要解释：""")


# ============================================================
# 评估指标
# ============================================================


@dataclass
class EvalScores:
    """单条评估结果"""

    question: str
    answer: str = ""
    faithfulness: float = 0.0
    relevancy: float = 0.0
    context_precision: float = 0.0
    tool_call_correct: bool = False
    skill_match: bool = False

    @property
    def overall(self) -> float:
        """综合得分（等权平均）"""
        return round(
            (self.faithfulness + self.relevancy + self.context_precision) / 3, 2
        )

    @property
    def grade(self) -> str:
        """等级评定"""
        if self.overall >= 0.8:
            return "🟢 优秀"
        elif self.overall >= 0.6:
            return "🟡 良好"
        elif self.overall >= 0.4:
            return "🟠 一般"
        return "🔴 较差"


@dataclass
class EvalReport:
    """批量评估报告"""

    scores: list[EvalScores] = field(default_factory=list)
    total_time: float = 0.0

    @property
    def avg_faithfulness(self) -> float:
        return (
            round(sum(s.faithfulness for s in self.scores) / len(self.scores), 2)
            if self.scores
            else 0
        )

    @property
    def avg_relevancy(self) -> float:
        return (
            round(sum(s.relevancy for s in self.scores) / len(self.scores), 2)
            if self.scores
            else 0
        )

    @property
    def avg_precision(self) -> float:
        return (
            round(sum(s.context_precision for s in self.scores) / len(self.scores), 2)
            if self.scores
            else 0
        )

    @property
    def avg_overall(self) -> float:
        return (
            round(sum(s.overall for s in self.scores) / len(self.scores), 2)
            if self.scores
            else 0
        )

    def print_summary(self):
        """打印汇总报告"""
        print(f"\n{'='*60}")
        print(f"📊 RAG 质量评估报告")
        print(f"{'='*60}")
        print(f"  测试用例: {len(self.scores)} 条")
        print(f"  总耗时: {self.total_time:.1f} 秒")
        print(f"  {'─'*40}")
        print(
            f"  📌 忠实度 (Faithfulness):    {self.avg_faithfulness:.2f}  {'✅' if self.avg_faithfulness >= 0.7 else '⚠️'}"
        )
        print(
            f"  📌 相关性 (Relevancy):       {self.avg_relevancy:.2f}  {'✅' if self.avg_relevancy >= 0.7 else '⚠️'}"
        )
        print(
            f"  📌 检索精度 (Precision):     {self.avg_precision:.2f}  {'✅' if self.avg_precision >= 0.7 else '⚠️'}"
        )
        print(f"  {'─'*40}")
        print(
            f"  🏆 综合得分:                 {self.avg_overall:.2f}  {EvalScores(question='', faithfulness=self.avg_faithfulness, relevancy=self.avg_relevancy, context_precision=self.avg_precision).grade}"
        )
        print(f"{'='*60}")

        # 分级统计
        grades = {"优秀": 0, "良好": 0, "一般": 0, "较差": 0}
        for s in self.scores:
            if s.overall >= 0.8:
                grades["优秀"] += 1
            elif s.overall >= 0.6:
                grades["良好"] += 1
            elif s.overall >= 0.4:
                grades["一般"] += 1
            else:
                grades["较差"] += 1

        print(f"\n📈 等级分布:")
        for grade, count in grades.items():
            bar = "█" * count
            print(f"  {grade}: {count}条 {bar}")


# ============================================================
# 评估器
# ============================================================


class RAGEvaluator:
    """RAG 质量评估器（LLM-as-Judge）"""

    def __init__(self):
        self.faithfulness_chain = FAITHFULNESS_PROMPT | chat_model | StrOutputParser()
        self.relevancy_chain = RELEVANCY_PROMPT | chat_model | StrOutputParser()
        self.precision_chain = PRECISION_PROMPT | chat_model | StrOutputParser()

    def evaluate(
        self,
        question: str,
        answer: str,
        context_docs: list[Document] | None = None,
    ) -> EvalScores:
        """评估单条 RAG 回答的质量

        Args:
            question: 用户问题
            answer: AI 回答
            context_docs: 检索到的上下文文档

        Returns:
            EvalScores 包含各项指标
        """
        scores = EvalScores(question=question, answer=answer)

        # 1. Faithfulness（有上下文时）
        if context_docs:
            context_text = ""
            for i, doc in enumerate(context_docs[:5]):
                context_text += f"[{i+1}] {doc.page_content[:300]}\n"

            try:
                result = self.faithfulness_chain.invoke(
                    {
                        "question": question,
                        "context": context_text,
                        "answer": answer[:500],
                    }
                )
                scores.faithfulness = self._parse_score(result)
            except Exception as e:
                logger.warning(f"[Eval] Faithfulness 评估失败: {e}")

        # 2. Answer Relevancy
        try:
            result = self.relevancy_chain.invoke(
                {
                    "question": question,
                    "answer": answer[:500],
                }
            )
            scores.relevancy = self._parse_score(result)
        except Exception as e:
            logger.warning(f"[Eval] Relevancy 评估失败: {e}")

        # 3. Context Precision（有上下文时）
        if context_docs:
            docs_text = ""
            for i, doc in enumerate(context_docs[:5]):
                docs_text += f"[{i+1}] {doc.page_content[:200]}\n"

            try:
                result = self.precision_chain.invoke(
                    {
                        "question": question,
                        "documents": docs_text,
                    }
                )
                scores.context_precision = self._parse_score(result)
            except Exception as e:
                logger.warning(f"[Eval] Precision 评估失败: {e}")

        return scores

    @staticmethod
    def _parse_score(text: str) -> float:
        """从 LLM 输出中解析 0.0-1.0 的分数"""
        import re

        match = re.search(r"(\d+\.?\d*)", str(text))
        if match:
            score = float(match.group(1))
            return max(0.0, min(1.0, score))
        return 0.0


# ============================================================
# 单例
# ============================================================

_evaluator: RAGEvaluator | None = None


def get_evaluator() -> RAGEvaluator:
    global _evaluator
    if _evaluator is None:
        _evaluator = RAGEvaluator()
    return _evaluator


# ============================================================
# 快速测试
# ============================================================

if __name__ == "__main__":
    evaluator = RAGEvaluator()

    # 模拟评估
    from langchain_core.documents import Document

    test_context = [
        Document(
            page_content="小户型推荐选择机身紧凑的扫地机器人，吸力1500Pa以上即可满足日常需求。",
            metadata={"source": "选购指南"},
        ),
        Document(
            page_content="养猫家庭需要关注防缠绕功能，推荐选择带胶刷的机型。",
            metadata={"source": "选购指南"},
        ),
    ]

    result = evaluator.evaluate(
        question="小户型养猫推荐哪款扫地机器人？",
        answer="推荐选择机身紧凑、吸力1500Pa以上的机型，养猫家庭建议选择带胶刷防缠绕的款式。",
        context_docs=test_context,
    )

    print("=== 单条评估测试 ===")
    print(f"  忠实度: {result.faithfulness:.2f}")
    print(f"  相关性: {result.relevancy:.2f}")
    print(f"  检索精度: {result.context_precision:.2f}")
    print(f"  综合得分: {result.overall:.2f} {result.grade}")
