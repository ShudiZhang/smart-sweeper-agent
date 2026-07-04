"""
验证脚本 — 测试 MCP 加载、Skill 解析/匹配/注入、Agent 初始化
用法: uv run python verify_all.py
"""

import sys
from pathlib import Path

# 确保项目根目录在 sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent))


# ============================================================
# 测试 1: Skill 加载与 Frontmatter 解析
# ============================================================
def test_skill_loading():
    print("=" * 60)
    print("测试 1: Skill 加载与 Frontmatter 解析")
    print("=" * 60)

    from utils.skill_loader import get_skill_manager

    mgr = get_skill_manager()
    skills = mgr.list_all()

    assert len(skills) >= 4, f"期望至少 4 个 Skill，实际 {len(skills)}"
    print(f"  ✅ 加载了 {len(skills)} 个 Skill")

    for name, desc in skills.items():
        content = mgr.get_content(name)
        assert content, f"Skill '{name}' 内容为空"
        print(f"     📌 {name}: {desc} ({len(content)} 字符)")

    print()


# ============================================================
# 测试 2: Skill 关键词自动匹配
# ============================================================
def test_skill_matching():
    print("=" * 60)
    print("测试 2: Skill 关键词自动匹配")
    print("=" * 60)

    from utils.skill_loader import get_skill_manager

    mgr = get_skill_manager()

    test_cases = [
        # (用户输入, 期望匹配的 Skill)
        ("我的机器人突然不工作了，怎么办？", "troubleshooting"),
        ("机器人扫地的时候发出异响", "troubleshooting"),
        ("帮我生成上个月的使用报告", "report_generation"),
        ("看看我的扫地机使用情况", "report_generation"),
        ("100平米小户型，推荐哪款扫地机器人？", "purchase_guide"),
        ("科沃斯和小米哪个性价比高", "purchase_guide"),
        ("滤芯多久换一次？", "accessory_recommend"),
        ("边刷该换了，买什么牌子的好", "accessory_recommend"),
        ("今天天气怎么样", None),  # 无匹配
        ("你好", None),  # 无匹配
    ]

    all_passed = True
    for query, expected in test_cases:
        matched = mgr.match(query, top_k=1)
        matched_name = matched[0] if matched else None

        if expected is None:
            if matched:
                print(f"  ❌ '{query}' → 不应匹配，但匹配到 {matched_name}")
                all_passed = False
            else:
                print(f"  ✅ '{query}' → 无匹配（正确）")
        else:
            if matched_name == expected:
                print(f"  ✅ '{query}' → {matched_name}")
            else:
                print(f"  ❌ '{query}' → 期望 {expected}，实际 {matched_name}")
                all_passed = False

    if all_passed:
        print("  🎉 全部匹配正确！")
    print()


# ============================================================
# 测试 3: Skill 注入到 Prompt
# ============================================================
def test_skill_injection():
    print("=" * 60)
    print("测试 3: Skill 注入到 Prompt")
    print("=" * 60)

    from utils.skill_loader import get_skill_manager

    mgr = get_skill_manager()
    base_prompt = "你是一个客服助手。"

    for skill_name in ["troubleshooting", "purchase_guide"]:
        injected = mgr.inject(base_prompt, [skill_name])
        assert len(injected) > len(
            base_prompt
        ), f"Skill '{skill_name}' 注入后长度未增加"
        assert "技能模板" in injected, f"Skill '{skill_name}' 未找到注入标记"
        assert skill_name in injected, f"Skill '{skill_name}' 名称未出现在 prompt 中"
        print(
            f"  ✅ {skill_name}: base={len(base_prompt)} → injected={len(injected)} 字符"
        )

    print()


# ============================================================
# 测试 4: MCP 工具加载
# ============================================================
def test_mcp_loading():
    print("=" * 60)
    print("测试 4: MCP 工具加载")
    print("=" * 60)

    try:
        from langchain_mcp import load_mcp_tools

        print("  ✅ langchain_mcp 已安装")
    except ImportError:
        print("  ⚠️  langchain_mcp 未安装，跳过 MCP 加载测试")
        print("     安装: uv pip install langchain-mcp")
        print()
        return

    import os

    server_path = os.path.join(
        os.path.dirname(__file__), "mcp_servers", "amap_server.py"
    )

    try:
        mcp_tools = load_mcp_tools(f"{sys.executable} {server_path}")
        if mcp_tools:
            print(f"  ✅ 成功加载 {len(mcp_tools)} 个 MCP 工具:")
            for tool in mcp_tools:
                print(f"     🔧 {tool.name}: {tool.description[:50]}...")
        else:
            print("  ⚠️  MCP 工具列表为空（可能 AMAP_API_KEY 未设置）")
    except Exception as e:
        print(f"  ❌ MCP 加载失败: {e}")

    print()


# ============================================================
# 测试 5: SmartAgent 初始化
# ============================================================
def test_agent_init():
    print("=" * 60)
    print("测试 5: SmartAgent 初始化")
    print("=" * 60)

    from agent.smart_agent import SmartAgent

    # 5a: 基础初始化（自动匹配模式）
    agent1 = SmartAgent()
    print("  ✅ SmartAgent() — 默认自动匹配模式")

    # 5b: 手动指定 Skill
    agent2 = SmartAgent(active_skill="report_generation", auto_match_skill=False)
    print("  ✅ SmartAgent(active_skill='report_generation') — 手动指定 Skill")

    # 5c: 禁用自动匹配
    agent3 = SmartAgent(auto_match_skill=False)
    print("  ✅ SmartAgent(auto_match_skill=False) — 纯通用模式")

    print()


# ============================================================
# 测试 6: Agent 流式响应（仅测试不报错）
# ============================================================
def test_agent_stream():
    print("=" * 60)
    print("测试 6: Agent 流式响应（快速冒烟测试）")
    print("=" * 60)

    from agent.smart_agent import SmartAgent

    agent = SmartAgent()

    test_queries = [
        "你好",
        "扫地机器人怎么保养",
    ]

    for query in test_queries:
        try:
            chunks = list(agent.execute_stream(query))
            response = "".join(chunks)
            print(f"  ✅ '{query}' → {len(chunks)} chunks, {len(response)} 字符")
        except Exception as e:
            print(f"  ❌ '{query}' → 异常: {e}")

    print()


# ============================================================
# 主入口
# ============================================================
if __name__ == "__main__":
    print()
    print("🚀 智扫通 — 全功能验证")
    print()

    test_skill_loading()
    test_skill_matching()
    test_skill_injection()
    test_mcp_loading()
    test_agent_init()
    test_agent_stream()

    print("=" * 60)
    print("🎉 验证完成！")
    print("=" * 60)
