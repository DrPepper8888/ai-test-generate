"""
规则注入器 - 将已学习规则注入到 system prompt

支持两种模式：
1. 文件模式（推荐）：使用 RuleFileManager 渐进式加载
2. 兼容模式：使用 MemoryStore 兼容旧代码
"""

from typing import List, Optional
from pathlib import Path

from src.harness.models import Rule
from src.harness.rule_file_manager import RuleFileManager


SYSTEM_RULE_PREFIX = """
---
【已学习规则】（来自历史反馈，越用越准）
"""

SYSTEM_RULE_SUFFIX = """
---
"""


class RuleInjector:
    """
    规则注入器

    支持两种模式：
    1. 文件模式（默认）：使用文件管理器，渐进式加载
    2. 兼容模式：使用旧版 MemoryStore
    """

    def __init__(
        self,
        rules_dir: Optional[str] = None,
        use_file_mode: bool = True,
    ):
        """
        初始化规则注入器

        Args:
            rules_dir: 规则文件目录，默认 data/rules
            use_file_mode: 是否使用文件模式（推荐）
        """
        if rules_dir is None:
            rules_dir = Path("rules")
        self.rules_dir = Path(rules_dir)

        if use_file_mode:
            self.file_manager = RuleFileManager(self.rules_dir)
        else:
            self.file_manager = None

    def inject(
        self,
        system_prompt: str,
        rules: List[Rule] = None,
        requirement: str = "",
        top_n: int = 5,
        include_skill: bool = True,
    ) -> str:
        """
        将规则注入到 system prompt

        注入顺序：
        1. 自定义规则（skill.md）
        2. 已学习规则（渐进式加载）

        Args:
            system_prompt: 原始 system prompt
            rules: 规则列表（兼容模式使用）
            requirement: 需求描述（用于关键词匹配）
            top_n: 最大注入规则数
            include_skill: 是否包含自定义规则

        Returns:
            注入规则后的 system prompt
        """
        injected_parts = []

        # 1. 注入自定义规则（优先）
        if include_skill:
            skill_path = Path("prompts/skill.md")
            if skill_path.exists():
                skill_content = skill_path.read_text(encoding="utf-8")
                # 过滤注释
                lines = [l for l in skill_content.split("\n")
                          if not l.strip().startswith("#")]
                skill_text = "\n".join(lines).strip()
                if skill_text:
                    injected_parts.append(f"""
---
【自定义规则】（来自 skill.md）
{skill_text}
---
""")

        # 2. 注入已学习规则（文件模式：渐进式加载）
        if self.file_manager:
            # 渐进式加载相关规则
            rules_text = self.file_manager.load_rules_for_context(
                requirement=requirement,
                limit=top_n,
            )
            if rules_text:
                injected_parts.append(rules_text)
        elif rules:
            # 兼容模式
            sorted_rules = sorted(rules, key=lambda r: r.use_count, reverse=True)
            selected = sorted_rules[:top_n]

            rules_text = SYSTEM_RULE_PREFIX
            for i, rule in enumerate(selected, 1):
                rules_text += f"\n{i}. {rule.rule_text}（类型：{rule.type.value}）"
            rules_text += SYSTEM_RULE_SUFFIX
            injected_parts.append(rules_text)

        if not injected_parts:
            return system_prompt

        # 合并到 system_prompt 开头
        injection = "\n".join(injected_parts) + "\n\n"
        return injection + system_prompt

    @staticmethod
    def get_display_text(rules: List[Rule] = None, rules_dir: str = None) -> str:
        """
        获取展示文本（用于前端显示）

        Args:
            rules: 规则列表（兼容模式）
            rules_dir: 规则目录（文件模式）

        Returns:
            格式化后的展示文本
        """
        if rules_dir:
            manager = RuleFileManager(Path(rules_dir))
            all_rules = manager.list_rules()
            if not all_rules:
                return "暂无已学习规则，继续生成用例来培养它吧！"
            lines = []
            for i, rule in enumerate(all_rules[:10], 1):
                lines.append(f"{i}. {rule.content[:50]}...")
            return "\n".join(lines)

        if not rules:
            return "暂无已学习规则，继续生成用例来培养它吧！"

        lines = []
        for i, rule in enumerate(rules, 1):
            lines.append(f"{i}. {rule.rule_text}")
        return "\n".join(lines)
