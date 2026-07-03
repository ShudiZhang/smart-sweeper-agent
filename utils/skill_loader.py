"""Skill 加载器 — 从 skills/ 目录加载 Markdown 模板并注入到 Agent 上下文"""

from pathlib import Path

from utils.path_tool import get_abs_path

SKILLS_DIR = Path(get_abs_path("skills"))


def load_skill(name: str) -> str:
    """加载单个 Skill 模板内容"""
    skill_path = SKILLS_DIR / f"{name}.md"
    if not skill_path.exists():
        return ""
    return skill_path.read_text(encoding="utf-8")


def load_all_skills() -> dict[str, str]:
    """加载 skills/ 目录下所有 .md 文件"""
    skills: dict[str, str] = {}
    if not SKILLS_DIR.is_dir():
        return skills
    for f in SKILLS_DIR.glob("*.md"):
        skills[f.stem] = f.read_text(encoding="utf-8")
    return skills


def inject_skill(system_prompt: str, skill_name: str) -> str:
    """将指定 Skill 注入到系统提示词末尾"""
    skill_content = load_skill(skill_name)
    if not skill_content:
        return system_prompt
    return f"{system_prompt}\n\n---\n## 技能模板：{skill_name}\n{skill_content}"
