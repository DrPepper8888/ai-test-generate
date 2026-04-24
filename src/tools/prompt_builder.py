"""
提示词构建器
支持模块化加载、动态拼接、规则注入
"""
from pathlib import Path
from typing import List, Dict


class PromptBuilder:
    """模块化提示词构建器"""

    def __init__(self, prompts_root: Path):
        self.prompts_root = Path(prompts_root)
        self._modules = {}

    def load_module(self, module_path: str) -> str:
        """加载单个提示词模块"""
        if module_path in self._modules:
            return self._modules[module_path]

        path = self.prompts_root / module_path
        if path.exists():
            content = path.read_text(encoding="utf-8")
            self._modules[module_path] = content
            return content

        raise FileNotFoundError(f"找不到提示词模块：{module_path}")

    def build_base_prompt(self, modules: List[str] = None) -> str:
        """构建基础提示词
        Args:
            modules: 要加载的模块列表，默认加载全部标准模块
        """
        if modules is None:
            modules = [
                "roles/base_tester.md",
                "rules/steps.md",
                "rules/format.md",
                "guards/prohibited.md",
            ]

        parts = []
        for module in modules:
            try:
                content = self.load_module(module)
                parts.append(content)
            except FileNotFoundError:
                pass

        return "\n\n---\n\n".join(parts)

    def inject_learned_rules(self, base_prompt: str, rules: List[Dict]) -> str:
        """注入已学习的规则到提示词中"""
        if not rules:
            return base_prompt

        rules_section = ["# 【已学习的规则】\n"]
        rules_section.append("请遵循以下从历史反馈中学习到的规则：\n")

        for i, rule in enumerate(rules[:10], 1):  # 最多注入10条
            rule_text = rule.get("rule_text", "")
            if rule_text:
                rules_section.append(f"{i}. {rule_text}")

        rules_section.append("\n---\n\n")
        injected_prompt = base_prompt.replace(
            "# 【角色定义】",
            "\n".join(rules_section) + "# 【角色定义】"
        )

        return injected_prompt

    @staticmethod
    def build_user_message(
        requirement: str,
        example: str,
        count: int,
        start_id: int = 2,
    ) -> str:
        """构建发给LLM的用户消息"""
        id_hint = f"（ID 从 TC_{start_id:03d} 开始编号）" if start_id != 2 else ""
        
        # 检测示例格式，避免误判
        example_hint = ""
        example_stripped = example.strip()
        if example_stripped.startswith("{"):
            example_hint = "（JSON对象格式，仅1条用例）"
        elif example_stripped.startswith("["):
            example_hint = "（JSON数组格式）"
        elif "\n" in example_stripped and "," in example_stripped[:100]:
            example_hint = "（注意：这只是1条示例用例，行号不代表用例数量）"
        
        return (
            f"【测试需求描述】\n{requirement}\n\n"
            f"【示例用例】{example_hint}\n{example}\n\n"
            f"【生成数量】\n{count} 条{id_hint}\n\n"
            f"请严格按照示例用例的字段结构生成，输出纯 JSON 数组。"
        )