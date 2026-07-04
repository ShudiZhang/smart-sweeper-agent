"""
功能效果测试 — 逐一验证各 Skill 和 MCP 工具的实际效果
用法: uv run python test_features.py [测试编号]

测试编号:
  1  - 自动匹配：故障排查
  2  - 自动匹配：选购指南
  3  - 自动匹配：配件推荐
  4  - 自动匹配：报告生成
  5  - 手动指定 Skill
  6  - 通用模式（无 Skill）
  7  - MCP 工具（天气+定位）
  all - 全部测试（默认）
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def run_test(label: str, query: str, active_skill=None, use_mcp=False):
    """运行单个测试并打印结果"""
    print()
    print("=" * 70)
    print(f"🧪 {label}")
    print(f"📝 用户输入: {query}")
    if active_skill:
        print(f"🎯 手动激活 Skill: {active_skill}")
    else:
        print(f"🤖 Skill 模式: 自动匹配")
    if use_mcp:
        print(f"🔌 MCP 工具: 已启用")
    print("-" * 70)

    from agent.smart_agent import SmartAgent

    # 加载 MCP 工具（如果启用）
    mcp_tools = None
    if use_mcp:
        try:
            from app import _load_mcp_tools

            mcp_tools = _load_mcp_tools()
            if mcp_tools:
                print(f"🔧 已加载 {len(mcp_tools)} 个 MCP 工具")
        except Exception as e:
            print(f"⚠️ MCP 加载失败: {e}")

    agent = SmartAgent(
        mcp_tools=mcp_tools,
        active_skill=active_skill,
        auto_match_skill=(active_skill is None),
    )

    print("📤 Agent 回复:")
    print("-" * 70)
    try:
        for chunk in agent.execute_stream(query):
            print(chunk, end="", flush=True)
        print()
    except Exception as e:
        print(f"❌ 异常: {e}")
    print("-" * 70)


def test_auto_match():
    """测试 1-4: Skill 自动匹配"""
    test_cases = [
        (
            "测试 1: 故障排查 Skill（自动匹配）",
            "我的扫地机器人开机后一直滴滴响，也不扫地了，这是怎么回事？",
        ),
        (
            "测试 2: 选购指南 Skill（自动匹配）",
            "我家80平米小户型，养了一只猫，预算3000以内，推荐哪款扫地机器人？",
        ),
        (
            "测试 3: 配件推荐 Skill（自动匹配）",
            "机器人的边刷用了半年了，感觉扫不干净，是不是该换了？换什么牌子的好？",
        ),
        (
            "测试 4: 报告生成 Skill（自动匹配）",
            "帮我生成我这个月的使用报告",
        ),
    ]

    for label, query in test_cases:
        run_test(label, query)


def test_manual_skill():
    """测试 5: 手动指定 Skill"""
    run_test(
        "测试 5: 手动指定选购指南 Skill",
        "帮我推荐一款机器人",
        active_skill="purchase_guide",
    )


def test_no_skill():
    """测试 6: 通用模式"""
    run_test(
        "测试 6: 通用模式（无 Skill）",
        "扫地机器人适合木地板吗？会不会刮花？",
    )


def test_mcp():
    """测试 7: MCP 工具"""
    run_test(
        "测试 7: MCP 天气查询",
        "今天深圳天气怎么样？适合用扫地机器人吗？",
        use_mcp=True,
    )


if __name__ == "__main__":
    test_map = {
        "1": ("自动匹配-故障排查", test_auto_match),
        "2": ("自动匹配-选购指南", test_auto_match),
        "3": ("自动匹配-配件推荐", test_auto_match),
        "4": ("自动匹配-报告生成", test_auto_match),
        "5": ("手动指定Skill", test_manual_skill),
        "6": ("通用模式", test_no_skill),
        "7": ("MCP工具", test_mcp),
        "all": (
            "全部",
            lambda: (
                test_auto_match(),
                test_manual_skill(),
                test_no_skill(),
                test_mcp(),
            ),
        ),
    }

    choice = sys.argv[1] if len(sys.argv) > 1 else "all"
    if choice not in test_map:
        print(f"错误：未知测试编号 '{choice}'，可选: {list(test_map.keys())}")
        sys.exit(1)

    name, func = test_map[choice]
    print(f"\n🚀 智扫通 — 功能效果测试: {name}")
    func()
    print("\n🎉 测试完成！")
