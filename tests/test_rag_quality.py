"""
RAG 效果独立测试脚本
====================
逐步骤展示增强检索管线：
  原始查询 → Query Rewrite → 候选召回(9篇) → LLM Rerank(分数) → Top-3 → 最终回答

用法:
  uv run python tests/test_rag_quality.py
  uv run python tests/test_rag_quality.py "你的问题"
"""

import sys

from rag.rag_service import RagSummarizeService


def test_single_query(rag: RagSummarizeService, query: str):
    """逐步骤测试单条查询"""
    print(f"\n{'='*60}")
    print(f"📝 原始查询: {query}")
    print(f"{'='*60}")

    # Step 1: Query Rewriting
    rewritten = rag.rewriter.rewrite(query)
    print(f"\n🔧 Step 1 - Query Rewrite:")
    print(f"   {rewritten}")

    # Step 2: 候选召回
    candidates = rag.vector_store.vector_store.similarity_search(
        rewritten, k=rag._candidate_k
    )
    if not candidates:
        candidates = rag.vector_store.vector_store.similarity_search(
            query, k=rag._candidate_k
        )
    print(f"\n📚 Step 2 - 候选召回 ({len(candidates)} 篇):")
    for i, doc in enumerate(candidates):
        print(f"   [{i+1}] {doc.page_content[:100]}...")

    # Step 3: Rerank
    ranked = rag.reranker.rerank(rewritten, candidates, rag._search_k)
    print(f"\n🎯 Step 3 - LLM Rerank → Top-{rag._search_k}:")
    for i, doc in enumerate(ranked):
        print(f"   [{i+1}] {doc.page_content[:120]}...")

    # Step 4: 最终回答
    print(f"\n💬 Step 4 - 最终回答:")
    answer = rag.rag_summarize(query)
    print(f"   {answer[:300]}...")

    # 对比：不加增强的结果
    print(f"\n📊 对比 - 无增强检索（仅向量 k=3）:")
    basic_docs = rag.retriever_docs(query)
    for i, doc in enumerate(basic_docs):
        print(f"   [{i+1}] {doc.page_content[:100]}...")

    print()


def main():
    rag = RagSummarizeService()

    default_queries = [
        "小户型60平养猫推荐哪款",
        "机器人开机一直滴滴响不动了",
        "拖地不出水怎么回事",
        "滤芯多久换一次",
        "科沃斯和小米哪个性价比高",
    ]

    if len(sys.argv) > 1:
        # 自定义查询
        test_single_query(rag, sys.argv[1])
    else:
        # 批量测试
        print("🧪 RAG 增强检索效果测试")
        print(
            f"   管线: Query → Rewrite → 召回({rag._candidate_k}篇) → Rerank(Top-{rag._search_k}) → Summarize\n"
        )
        for q in default_queries:
            test_single_query(rag, q)


if __name__ == "__main__":
    main()
