"""
规则注入器 - 将已学习规则和自定义规则注入到 system prompt

完全使用 Python 标准库，无第三方依赖
"""

from typing import List, Optional

from src.harness.models import Rule
from src.harness.skill_loader import SkillLoader


SYSTEM_RULE_PREFIX = """
---
【已学习规则】（来自历史反馈，越用越准）
"""

SYSTEM_RULE_SUFFIX = """
---
"""


class RuleInjector:
    """规则注入器"""

    def __init__(self, skill_path: Optional[str] = None):
        """
        初始化规则注入器
        
        Args:
            skill_path: 自定义规则文件路径，默认 prompts/skill.md
        """
        self.skill_loader = SkillLoader(skill_path) if skill_path else SkillLoader()

    def inject(
        self,
        system_prompt: str,
        rules: List[Rule],
        top_n: int = 5,
        include_skill: bool = True,
    ) -> str:
        """
        将规则注入到 system prompt
        
        注入顺序：
        1. 自定义规则（skill.md）
        2. 已学习规则（Harness 积累的规则）
        
        Args:
            system_prompt: 原始 system prompt
            rules: 规则列表
            top_n: 只注入前 N 条规则
            include_skill: 是否包含自定义规则
            
        Returns:
            注入规则后的 system prompt
        """
        injected_parts = []

        # 1. 注入自定义规则（优先）
        if include_skill:
            skill_text = self.skill_loader.get_inject_text()
            if skill_text:
                injected_parts.append(skill_text)

        # 2. 注入已学习规则
        if rules:
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
    def get_display_text(rules: List[Rule]) -> str:
        """
        获取展示文本（用于前端显示）
        
        Args:
            rules: 规则列表
            
        Returns:
            格式化后的展示文本
        """
        if not rules:
            return "暂无已学习规则，继续生成用例来培养它吧！"

        lines = []
        for i, rule in enumerate(rules, 1):
            lines.append(f"{i}. {rule.rule_text}")

        return "\n".join(lines)
