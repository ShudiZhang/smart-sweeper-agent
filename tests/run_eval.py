"""
Agent 效果测评脚本
==================
两种模式:
  1. 快速模式: 仅测 Skill 匹配准确率（不调用 LLM，零成本）
     uv run python tests/run_eval.py --quick

  2. 完整模式: 测试 Skill + 工具调用（调用 LLM，产生 API 费用）
     uv run python tests/run_eval.py --full

  3. 单条测试:
     uv run python tests/run_eval.py --id eval_001
"""

import argparse
import re
import sys
import time
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def load_dataset(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


# ============================================================
# 快速模式：仅测 Skill 匹配
# ============================================================


def eval_skill_matching(dataset: list[dict]) -> dict:
    """测试 Skill 自动匹配准确率"""
    from utils.skill_loader import get_skill_manager

    mgr = get_skill_manager()

    correct = 0
    total = 0
    detail: list[dict] = []

    for case in dataset:
        expected = case.get("expected_skill")
        if expected is None:
            continue  # 跳过无期望 Skill 的用例

        total += 1
        matched = mgr.match(case["question"], top_k=1)
        actual = matched[0] if matched else None
        is_correct = actual == expected

        if is_correct:
            correct += 1

        detail.append(
            {
                "id": case["id"],
                "question": case["question"],
                "expected": expected,
                "actual": actual,
                "correct": is_correct,
            }
        )

    return {
        "metric": "Skill 匹配准确率",
        "correct": correct,
        "total": total,
        "accuracy": f"{correct / total * 100:.1f}%" if total > 0 else "N/A",
        "detail": detail,
    }


# ============================================================
# 完整模式：测试 Skill + 工具调用
# ============================================================


def _extract_tool_calls_from_chunks(chunks: list[str]) -> list[str]:
    """从 Agent 输出中提取工具调用名称（通过日志标记）"""
    tools_called = set()
    for chunk in chunks:
        # 匹配日志中的 "执行工具：xxx"
        match = re.search(r"执行工具：(\w+)", chunk)
        if match:
            tools_called.add(match.group(1))
    return sorted(tools_called)


def _extract_skill_from_chunks(chunks: list[str]) -> str | None:
    """从 Agent 输出中提取自动匹配的 Skill"""
    for chunk in chunks:
        match = re.search(r"自动匹配.*?Skill:\s*\[['\"](\w+)['\"]", chunk)
        if match:
            return match.group(1)
        match = re.search(r"输入匹配到 Skill:\s*\[['\"](\w+)['\"]", chunk)
        if match:
            return match.group(1)
    return None


def eval_full(dataset: list[dict], limit: int = 0) -> dict:
    """完整测试：Skill 匹配 + 工具调用（调用 LLM）"""
    from agent.smart_agent import SmartAgent

    cases = dataset[:limit] if limit > 0 else dataset

    skill_correct = 0
    skill_total = 0
    tool_correct = 0
    tool_total = 0
    detail: list[dict] = []

    for case in cases:
        print(f"\n  [{case['id']}] {case['question'][:50]}...", end=" ", flush=True)

        agent = SmartAgent()
        chunks = []
        try:
            for chunk in agent.execute_stream(case["question"]):
                chunks.append(chunk)
        except Exception as e:
            chunks.append(f"[ERROR: {e}]")

        full_output = "".join(chunks)

        # 检查 Skill 匹配
        expected_skill = case.get("expected_skill")
        if expected_skill is not None:
            skill_total += 1
            actual_skill = _extract_skill_from_chunks(chunks)
            if actual_skill == expected_skill:
                skill_correct += 1
                print("✅ Skill", end=" ")
            else:
                print(f"❌ Skill(期望{expected_skill},实际{actual_skill})", end=" ")

        # 检查工具调用
        expected_tools = set(case.get("expected_tools", []))
        if expected_tools:
            tool_total += 1
            actual_tools = set(_extract_tool_calls_from_chunks(chunks))
            if expected_tools.issubset(actual_tools):
                tool_correct += 1
                print("✅ Tools", end="")
            else:
                missing = expected_tools - actual_tools
                print(f"❌ Tools(缺少{missing})", end="")

        detail.append(
            {
                "id": case["id"],
                "question": case["question"],
                "expected_skill": expected_skill,
                "actual_skill": _extract_skill_from_chunks(chunks),
                "expected_tools": list(expected_tools),
                "actual_tools": _extract_tool_calls_from_chunks(chunks),
                "output_preview": full_output[:200],
            }
        )

        time.sleep(0.5)  # 避免 API 限流

    print()
    return {
        "skill_accuracy": (
            f"{skill_correct / skill_total * 100:.1f}% ({skill_correct}/{skill_total})"
            if skill_total > 0
            else "N/A"
        ),
        "tool_accuracy": (
            f"{tool_correct / tool_total * 100:.1f}% ({tool_correct}/{tool_total})"
            if tool_total > 0
            else "N/A"
        ),
        "detail": detail,
    }


# ============================================================
# 报告输出
# ============================================================


def print_quick_report(result: dict):
    print("\n" + "=" * 60)
    print(f"📊 {result['metric']}")
    print(f"   正确: {result['correct']} / 总计: {result['total']}")
    print(f"   准确率: {result['accuracy']}")
    print("-" * 60)

    # 按类别统计
    from collections import Counter

    by_cat = Counter()
    cat_correct = Counter()
    for d in result["detail"]:
        # 从 ID 推断类别
        cat = d["id"].rsplit("_", 1)[0]
        by_cat[cat] += 1
        if d["correct"]:
            cat_correct[cat] += 1

    for cat in sorted(by_cat):
        acc = cat_correct[cat] / by_cat[cat] * 100 if by_cat[cat] > 0 else 0
        bar = "█" * int(acc / 10) + "░" * (10 - int(acc / 10))
        print(f"   {cat:12s}  {bar}  {acc:.0f}% ({cat_correct[cat]}/{by_cat[cat]})")

    # 打印错误用例
    errors = [d for d in result["detail"] if not d["correct"]]
    if errors:
        print("-" * 60)
        print(f"⚠️  匹配错误 ({len(errors)} 条):")
        for d in errors:
            print(f"   [{d['id']}] {d['question'][:40]}")
            print(f"       期望: {d['expected']} → 实际: {d['actual']}")


def print_full_report(result: dict):
    print("\n" + "=" * 60)
    print("📊 完整测评结果")
    print(f"   Skill 准确率: {result['skill_accuracy']}")
    print(f"   工具调用准确率: {result['tool_accuracy']}")


# ============================================================
# RAG 质量评估模式（LLM-as-Judge）
# ============================================================


def eval_rag_quality(dataset: list[dict], limit: int = 0) -> None:
    """RAG 质量评估：忠实度 + 相关性 + 检索精度
    仅评估 expected_tools 中包含 rag_summarize 的用例
    """
    from tests.eval_metrics import EvalReport, get_evaluator
    from rag.rag_service import RagSummarizeService

    evaluator = get_evaluator()
    rag = RagSummarizeService()

    # 只评估需要 RAG 的用例
    rag_cases = [c for c in dataset if "rag_summarize" in c.get("expected_tools", [])]
    skipped = len(dataset) - len(rag_cases)
    if skipped:
        print(f"⏭️  跳过 {skipped} 条非 RAG 用例（闲聊/天气等）\n")

    cases = rag_cases[:limit] if limit > 0 else rag_cases
    report = EvalReport()

    start = time.time()

    for i, case in enumerate(cases):
        qid = case["id"]
        question = case["question"]
        print(f"  [{i+1}/{len(cases)}] {qid}: {question[:40]}...", end=" ", flush=True)

        answer = rag.rag_summarize(question)
        context_docs = rag.enhanced_retrieve(question)
        scores = evaluator.evaluate(question, answer, context_docs)
        report.scores.append(scores)

        print(f"综合={scores.overall:.2f} {scores.grade}")

    report.total_time = time.time() - start
    report.print_summary()

    print(f"\n📋 明细:")
    for s in report.scores:
        print(
            f"  {s.grade} | F={s.faithfulness:.2f} R={s.relevancy:.2f} P={s.context_precision:.2f} | {s.question[:50]}"
        )


# ============================================================
# 主入口
# ============================================================


def main():
    parser = argparse.ArgumentParser(description="智扫通 Agent 效果测评")
    parser.add_argument(
        "--quick", action="store_true", help="快速模式（仅 Skill 匹配）"
    )
    parser.add_argument("--full", action="store_true", help="完整模式（含工具调用）")
    parser.add_argument(
        "--rag", action="store_true", help="RAG质量评估（忠实度+相关性+检索精度）"
    )
    parser.add_argument("--id", type=str, help="测试单条用例")
    parser.add_argument("--limit", type=int, default=0, help="限制用例数量")
    args = parser.parse_args()

    dataset_path = Path(__file__).parent / "eval_dataset.yml"
    dataset = load_dataset(str(dataset_path))
    print(f"📋 加载测评集: {len(dataset)} 条用例\n")

    if args.id:
        case = next((c for c in dataset if c["id"] == args.id), None)
        if not case:
            print(f"错误：未找到用例 {args.id}")
            return
        dataset = [case]

    if args.rag:
        print("🧪 RAG 质量评估模式（LLM-as-Judge）\n")
        eval_rag_quality(dataset, args.limit)
    elif args.full:
        print("🔬 完整测评模式（将调用 LLM，产生 API 费用）")
        result = eval_full(dataset, limit=args.limit)
        quick_result = eval_skill_matching(dataset)
        print_quick_report(quick_result)
        print_full_report(result)
    else:
        result = eval_skill_matching(dataset)
        print_quick_report(result)


if __name__ == "__main__":
    main()
