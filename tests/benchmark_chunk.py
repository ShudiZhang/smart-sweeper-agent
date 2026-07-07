"""
Chunk 大小对召回率影响的基准测试
================================
对比不同 chunk_size 下的 Recall@K，数据驱动地选择最优 chunk 参数。

原理：
  对每个评测问题，检索 Top-K 个 chunk，检查是否命中"黄金答案"的关键词。
  Recall@K = 命中数 / 总查询数

用法:
  # 快速模式：只测 Recall，不重灌数据（使用当前 chroma_db）
  uv run python tests/benchmark_chunk.py --quick

  # 完整模式：依次用不同 chunk_size 重灌数据后测试（⚠️ 会清空 chroma_db）
  uv run python tests/benchmark_chunk.py --full
"""

import argparse
import shutil
import sys
import time
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


# ============================================================
# 评测集：问题 → 黄金答案关键词（用于判断检索到的 chunk 是否命中）
# ============================================================

EVAL_CASES = [
    {
        "id": "eval_001",
        "question": "机器人开机后一直滴滴响，也不动了，怎么办？",
        "golden_keywords": ["滴滴滴", "报警", "尘盒", "滤网"],
    },
    {
        "id": "eval_002",
        "question": "我的扫地机连不上WiFi了，试了好几次都不行",
        "golden_keywords": ["WiFi", "2.4G", "配网"],
    },
    {
        "id": "eval_003",
        "question": "机器人吸力变小了很多，扫不干净",
        "golden_keywords": ["吸力", "尘盒", "滤网", "堵塞"],
    },
    {
        "id": "eval_004",
        "question": "机器人找不到充电座，一直在转圈",
        "golden_keywords": ["充电座", "回充", "传感器"],
    },
    {
        "id": "eval_005",
        "question": "小户型60平米，养了一只猫，预算2000左右，推荐哪款？",
        "golden_keywords": ["小户型", "宠物", "预算"],
    },
    {
        "id": "eval_006",
        "question": "科沃斯和小米哪个好？家里有地毯和木地板",
        "golden_keywords": ["科沃斯", "小米", "对比", "品牌"],
    },
    {
        "id": "eval_007",
        "question": "扫拖一体的机器人和单独扫地的比，值得多花钱吗？",
        "golden_keywords": ["扫拖一体", "单独", "对比"],
    },
    {
        "id": "eval_008",
        "question": "机器人的滤芯和边刷多久换一次？",
        "golden_keywords": ["滤芯", "边刷", "更换", "多久"],
    },
    {
        "id": "eval_009",
        "question": "扫地机器人日常要怎么保养？",
        "golden_keywords": ["保养", "清洁", "维护"],
    },
    {
        "id": "eval_010",
        "question": "尘盒怎么清理？可以用水洗吗？",
        "golden_keywords": ["尘盒", "清理", "水洗"],
    },
    {
        "id": "eval_011",
        "question": "滚刷用了8个月了，要不要换？换原厂还是第三方的？",
        "golden_keywords": ["滚刷", "更换", "原厂", "第三方"],
    },
    {
        "id": "eval_012",
        "question": "拖布发黄洗不干净了，需要更换吗？",
        "golden_keywords": ["拖布", "更换", "发黄"],
    },
    {
        "id": "eval_013",
        "question": "扫拖一体机器人可以只扫地不拖地吗？",
        "golden_keywords": ["只扫地", "不拖地", "模式"],
    },
    {
        "id": "eval_014",
        "question": "拖地时会不会把脏东西抹得到处都是？",
        "golden_keywords": ["拖地", "脏", "抹"],
    },
    {
        "id": "eval_019",
        "question": "机器人电池鼓包了还能用吗？",
        "golden_keywords": ["电池鼓包", "更换", "安全"],
    },
    {
        "id": "eval_020",
        "question": "我家500平大别墅，推荐什么机器人？",
        "golden_keywords": ["大面积", "大户型", "推荐"],
    },
]


# ============================================================
# 命中判断
# ============================================================


def is_hit(retrieved_chunks: list[str], keywords: list[str]) -> bool:
    """判断检索结果是否命中：任意 chunk 包含至少 2 个关键词"""
    for chunk in retrieved_chunks:
        match_count = sum(1 for kw in keywords if kw in chunk)
        if match_count >= 2:
            return True
    return False


# ============================================================
# Recall@K 计算
# ============================================================


def compute_recall_at_k(chunks_per_query: list[list[str]], k: int) -> float:
    """计算 Recall@K"""
    hits = 0
    for retrieved, case in zip(chunks_per_query, EVAL_CASES):
        top_k_chunks = retrieved[:k]
        if is_hit(top_k_chunks, case["golden_keywords"]):
            hits += 1

    recall = hits / len(EVAL_CASES) if EVAL_CASES else 0
    return recall


# ============================================================
# 检索函数
# ============================================================


def retrieve_for_queries(rag_service, queries: list[str], top_k: int = 10):
    """对一批查询执行检索，返回每个查询的 Top-K chunk 文本列表"""
    results = []
    for q in queries:
        try:
            docs = rag_service.enhanced_retrieve(q)
            chunks = [doc.page_content for doc in docs[:top_k]]
            results.append(chunks)
        except Exception as e:
            print(f"  ⚠️ 检索失败 [{q[:30]}...]: {e}")
            results.append([])
    return results


# ============================================================
# 快速模式：使用当前 chroma_db
# ============================================================


def run_quick():
    """快速模式：不重灌数据，直接测试当前 chunk 配置"""
    from rag.rag_service import RagSummarizeService

    print("=" * 60)
    print("📊 Chunk 召回率基准测试（快速模式）")
    print("   使用当前 chroma_db，不重灌数据")
    print("=" * 60)

    rag = RagSummarizeService()
    queries = [c["question"] for c in EVAL_CASES]

    start = time.time()
    chunks_per_query = retrieve_for_queries(rag, queries, top_k=10)
    elapsed = time.time() - start

    print(f"\n⏱️  检索耗时: {elapsed:.2f}s ({elapsed/len(queries):.2f}s/query)\n")

    for k in [1, 3, 5, 10]:
        recall = compute_recall_at_k(chunks_per_query, k)
        print(f"  Recall@{k:2d} = {recall:.1%}")

    # 逐条详情
    print(f"\n{'='*60}")
    print("📋 逐条命中详情 (Recall@3):")
    for i, (case, retrieved) in enumerate(zip(EVAL_CASES, chunks_per_query)):
        hit = is_hit(retrieved[:3], case["golden_keywords"])
        status = "✅" if hit else "❌"
        print(f"  {status} {case['id']}: {case['question'][:40]}...")
        if not hit:
            print(f"     检索到: {[c[:60] for c in retrieved[:3]]}")

    # 最终平均 Recall
    recall3 = compute_recall_at_k(chunks_per_query, 3)
    print(f"\n{'='*60}")
    print(f"🎯 最终 Recall@3 = {recall3:.1%}")


# ============================================================
# 完整模式：对比不同 chunk_size
# ============================================================


def run_full():
    """完整模式：依次用不同 chunk_size 重灌数据，对比 Recall"""
    import importlib

    from utils.config_handler import get_config

    CHUNK_SIZES = [200, 400, 600, 800, 1000]

    print("=" * 60)
    print("📊 Chunk 召回率全面基准测试")
    print(f"   对比 chunk_size: {CHUNK_SIZES}")
    print("=" * 60)

    results = {}

    for cs in CHUNK_SIZES:
        overlap = max(cs // 10, 20)
        print(f"\n--- chunk_size={cs}, overlap={overlap} ---")

        # 1. 修改配置
        cfg = get_config()
        cfg.chroma.chunk_size = cs
        cfg.chroma.chunk_overlap = overlap

        # 2. 清空 chroma_db
        chroma_path = Path(cfg.chroma.persist_directory)
        if chroma_path.exists():
            shutil.rmtree(chroma_path)
            print(f"  🗑️  已清空 {chroma_path}")

        # 3. 清空 MD5 缓存（否则不会重新灌入）
        md5_path = Path(cfg.chroma.md5_hex_store)
        if md5_path.exists():
            md5_path.unlink()

        # 4. 重新加载 RAG 服务（触发 load_document）
        #    需要 invalidate 单例缓存
        importlib.reload(
            sys.modules.get(
                "rag.vector_store", importlib.import_module("rag.vector_store")
            )
        )
        from rag.rag_service import RagSummarizeService

        rag = RagSummarizeService()
        rag.vector_store.load_document()
        print(f"  📥 数据已重新灌入")

        # 5. 检索 + 评估
        queries = [c["question"] for c in EVAL_CASES]
        start = time.time()
        chunks_per_query = retrieve_for_queries(rag, queries, top_k=10)
        elapsed = time.time() - start

        row = {
            "chunk_size": cs,
            "overlap": overlap,
            "time": f"{elapsed:.2f}s",
            "time_per_query": f"{elapsed/len(queries):.2f}s",
        }
        for k in [1, 3, 5, 10]:
            row[f"Recall@{k}"] = f"{compute_recall_at_k(chunks_per_query, k):.1%}"

        results[cs] = row

    # ============================================================
    # 汇总表格
    # ============================================================
    print(f"\n{'='*80}")
    print("📊 汇总对比")
    print(f"{'='*80}")
    header = f"{'chunk':>7} {'overlap':>8} {'R@1':>7} {'R@3':>7} {'R@5':>7} {'R@10':>7} {'耗时':>10}"
    print(header)
    print("-" * 80)
    for cs in CHUNK_SIZES:
        r = results[cs]
        print(
            f"{r['chunk_size']:>7} {r['overlap']:>8} "
            f"{r['Recall@1']:>7} {r['Recall@3']:>7} {r['Recall@5']:>7} "
            f"{r['Recall@10']:>7} {r['time']:>10}"
        )

    # 找最优
    best = max(results.items(), key=lambda x: float(x[1]["Recall@3"].rstrip("%")))
    print(f"\n🏆 最优 chunk_size = {best[0]} (Recall@3 = {best[1]['Recall@3']})")


# ============================================================
# 入口
# ============================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Chunk 召回率基准测试")
    parser.add_argument(
        "--quick",
        action="store_true",
        default=True,
        help="快速模式：使用当前 chroma_db（默认）",
    )
    parser.add_argument(
        "--full", action="store_true", help="完整模式：重灌数据，对比多种 chunk_size"
    )
    args = parser.parse_args()

    if args.full:
        run_full()
    else:
        run_quick()
