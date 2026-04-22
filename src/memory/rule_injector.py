"""
规则注入模块
将学到的规则注入到 system prompt 中
"""
from typing import List, Dict


SYSTEM_RULE_PREFIX = """
---
【已学习规则】
以下是从历史反馈中学到的测试规则，请严格遵守：
"""

SYSTEM_RULE_SUFFIX = """
---
"""


class RuleInjector:
    """规则注入器"""

    @staticmethod
    def inject(system_prompt: str, rules: List[Dict], top_n: int = 5) -> str:
        """
        将规则注入到 system prompt 中

        Args:
            system_prompt: 原始 system prompt
            rules: 规则列表
            top_n: 只注入最近/使用最多的 N 条

        Returns:
            注入规则后的 system prompt
        """
        if not rules:
            return system_prompt

        # 排序规则（按使用次数或直接取前 N）
        sorted_rules = sorted(rules, key=lambda r: r.get("use_count", 0), reverse=True)
        selected_rules = sorted_rules[:top_n]

        # 构建规则文本
        rules_text = SYSTEM_RULE_PREFIX
        for i, rule in enumerate(selected_rules, 1):
            rules_text += f"\n{i}. {rule['rule_text']}"
        rules_text += SYSTEM_RULE_SUFFIX

        # 注入到 system_prompt 开头（或者某个合适位置）
        return rules_text + "\n\n" + system_prompt

    @staticmethod
    def get_instruction_text(rules: List[Dict]) -> str:
        """获取规则文本，用于 UI 展示"""
        if not rules:
            return "暂无已学习规则"
        lines = []
        for i, rule in enumerate(rules, 1):
            lines.append(f"{i}. {rule['rule_text']}")
        return "\n".join(lines)
