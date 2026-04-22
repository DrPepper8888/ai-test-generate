"""
规则提取模块
从用户反馈中学习并总结成规则
"""
import json
from typing import Dict, List, Optional
from src.api.llm_client import LLMClient


EXTRACT_RULE_PROMPT = """
你是一位规则提取专家。

请从以下用户反馈中提取测试规则。

【用户反馈】
{feedback}

【要求】
- 提取可复用的规则，不要具体案例
- 规则格式：JSON数组
- 每条规则包含：rule_id（RULE_XXX）、type、rule_text、source

【输出示例】
```json
[
  {
    "rule_id": "RULE_001",
    "type": "field_value",
    "rule_text": "前置条件必须包含用户登录状态",
    "source": "用户反馈"
  }
]
```

请直接输出JSON，不要添加其他文字。
"""


class RuleExtractor:
    """规则提取器"""

    def __init__(self, llm_client: LLMClient):
        self.llm = llm_client

    def extract_from_feedback(self, feedback: str) -> List[Dict]:
        """从用户反馈提取规则"""
        prompt = EXTRACT_RULE_PROMPT.format(feedback=feedback)
        raw = self.llm.chat(prompt, "")

        # 尝试解析 JSON
        try:
            data = json.loads(raw)
            if isinstance(data, list):
                return data
        except json.JSONDecodeError:
            # 尝试提取 JSON 块
            import re
            match = re.search(r"\[[\s\S]*\]", raw)
            if match:
                try:
                    data = json.loads(match.group(0))
                    if isinstance(data, list):
                        return data
                except json.JSONDecodeError:
                    pass

        return []

    def merge_rules(self, existing: List[Dict], new_rules: List[Dict]) -> List[Dict]:
        """合并规则，去重"""
        rule_texts = set(r["rule_text"] for r in existing)
        merged = existing.copy()
        for rule in new_rules:
            if rule["rule_text"] not in rule_texts:
                merged.append(rule)
        return merged
