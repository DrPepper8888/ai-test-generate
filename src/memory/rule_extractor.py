"""
规则提取模块
从用户反馈、优质用例中学习并总结成规则
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
- 每条规则包含：rule_text（规则内容）、type（规则类型）、source（来源）

【输出示例】
```json
[
  {
    "type": "field_value",
    "rule_text": "前置条件必须包含用户登录状态",
    "source": "用户反馈"
  }
]
```

请直接输出JSON，不要添加其他文字。
"""


EXTRACT_FROM_GOOD_CASES_PROMPT = """
你是一位测试用例规则提取专家。

请分析以下被标记为"可投产"的优质测试用例，从中提取可复用的用例编写规则。

【优质用例】
{cases_json}

【要求】
- 提取 3-5 条最有价值的通用规则
- 关注：字段填写规范、描述粒度、场景覆盖方法、预期结果写法
- 规则要可复用，不要针对具体业务
- 输出 JSON 数组格式

【输出示例】
```json
[
  {
    "type": "writing_style",
    "rule_text": "测试步骤应采用动词开头，清晰描述操作动作",
    "source": "优质用例反向学习"
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

    def extract_from_good_cases(self, cases: List[Dict]) -> List[Dict]:
        """从优质（可投产）用例中反向学习规则"""
        if len(cases) < 3:
            return []

        cases_json = json.dumps(cases, ensure_ascii=False, indent=2)
        prompt = EXTRACT_FROM_GOOD_CASES_PROMPT.format(cases_json=cases_json)
        raw = self.llm.chat(prompt, "")

        try:
            data = json.loads(raw)
            if isinstance(data, list):
                return data
        except json.JSONDecodeError:
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
