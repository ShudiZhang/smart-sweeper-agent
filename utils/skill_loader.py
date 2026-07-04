"""Skill 加载器 — 支持 YAML frontmatter 解析、关键词自动匹配、多 Skill 组合"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from utils.logger_handler import logger
from utils.path_tool import get_abs_path

SKILLS_DIR = Path(get_abs_path("skills"))

# 匹配 YAML frontmatter: 以 --- 开头和结尾的块
_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


@dataclass
class SkillMeta:
    """Skill 元数据（从 frontmatter 解析）"""

    name: str
    description: str = ""
    triggers: dict = field(default_factory=dict)
    # triggers.keywords: 触发关键词列表
    # triggers.priority: 匹配优先级（数字越大越优先）

    @property
    def keywords(self) -> list[str]:
        return self.triggers.get("keywords", [])

    @property
    def priority(self) -> int:
        return self.triggers.get("priority", 0)

    @classmethod
    def from_frontmatter(cls, raw_content: str) -> tuple["SkillMeta", str]:
        """解析 YAML frontmatter，返回 (元数据, 正文)"""
        m = _FRONTMATTER_RE.match(raw_content)
        if not m:
            # 无 frontmatter，用文件名作为 name
            return cls(name="unknown", description=""), raw_content

        data = yaml.safe_load(m.group(1)) or {}
        body = raw_content[m.end() :]
        return (
            cls(
                name=data.get("name", "unknown"),
                description=data.get("description", ""),
                triggers=data.get("triggers", {}),
            ),
            body,
        )


class SkillManager:
    """Skill 管理器：加载、匹配、注入"""

    def __init__(self) -> None:
        self._skills: dict[str, tuple[SkillMeta, str]] = {}  # name -> (meta, content)
        self._reload()

    def _reload(self) -> None:
        """重新加载所有 Skill"""
        self._skills.clear()
        if not SKILLS_DIR.is_dir():
            return
        for f in sorted(SKILLS_DIR.glob("*.md")):
            raw = f.read_text(encoding="utf-8")
            meta, body = SkillMeta.from_frontmatter(raw)
            # fallback: 用文件名作为 name
            if meta.name == "unknown":
                meta.name = f.stem
            self._skills[meta.name] = (meta, body)
        logger.info(
            f"[SkillManager] 已加载 {len(self._skills)} 个 Skill: {list(self._skills)}"
        )

    def list_all(self) -> dict[str, str]:
        """返回 {name: description}，供 UI 展示"""
        return {meta.name: meta.description for meta, _ in self._skills.values()}

    def get_content(self, name: str) -> str | None:
        """获取指定 Skill 的正文内容"""
        entry = self._skills.get(name)
        return entry[1] if entry else None

    def match(self, user_query: str, top_k: int = 1) -> list[str]:
        """根据用户输入匹配最合适的 Skill（按优先级排序）"""
        scored: list[tuple[int, str]] = []
        query_lower = user_query.lower()

        for name, (meta, _) in self._skills.items():
            score = 0
            for kw in meta.keywords:
                if kw.lower() in query_lower:
                    score += 1
            if score > 0:
                # 命中关键词数量 + 基础优先级
                scored.append((score * 10 + meta.priority, name))

        scored.sort(key=lambda x: x[0], reverse=True)
        matched = [name for _, name in scored[:top_k]]
        if matched:
            logger.info(
                f"[SkillManager] 输入匹配到 Skill: {matched} (query={user_query[:40]})"
            )
        return matched

    def inject(self, system_prompt: str, skill_names: list[str]) -> str:
        """将指定 Skill 注入到系统提示词末尾"""
        for name in skill_names:
            content = self.get_content(name)
            if content:
                system_prompt += f"\n\n---\n## 技能模板：{name}\n{content}"
        return system_prompt


# ---- 全局单例 ----
_skill_manager: SkillManager | None = None


def get_skill_manager() -> SkillManager:
    """获取 SkillManager 单例"""
    global _skill_manager
    if _skill_manager is None:
        _skill_manager = SkillManager()
    return _skill_manager


# ---- 向后兼容接口 ----


def load_skill(name: str) -> str:
    """加载单个 Skill 模板内容（兼容旧接口）"""
    return get_skill_manager().get_content(name) or ""


def load_all_skills() -> dict[str, str]:
    """加载 skills/ 目录下所有 Skill（兼容旧接口，返回 {name: description}）"""
    return get_skill_manager().list_all()


def inject_skill(system_prompt: str, skill_name: str) -> str:
    """将指定 Skill 注入到系统提示词末尾（兼容旧接口）"""
    return get_skill_manager().inject(system_prompt, [skill_name])
