"""
规则提取器 - 从用户反馈和优质用例中学习规则

完全使用 Python 标准库，无第三方依赖
"""

import json
import re
from typing import List, Dict, Any, Optional

from src.api.llm_client import LLMClient
from src.harness.models import RuleType


# =============================================================================
# Prompt 模板
# =============================================================================

EXTRACT_FROM_FEEDBACK_PROMPT = """# 规则提取专家

你是一位专业的测试规则提取工程师。你的任务是从用户反馈中提取可复用的测试规则。

## 用户反馈

```
{feedback}
```

## 任务

1. 仔细阅读用户反馈，判断这是否是可复用的规则
2. 提取 1-3 条可复用的规则

## 输出格式

```json
[
  {{
    "rule_text": "规则内容（简洁、可执行）",
    "type": "field_format | scenario_coverage | business_logic | boundary_value | general",
    "reasoning": "为什么提取这条规则"
  }}
]
```

请只输出 JSON，不要添加任何解释。
"""

EXTRACT_FROM_GOOD_CASES_PROMPT = """# 优质用例反向学习

你是一位测试规则提取专家。请分析以下被标记为"优质"的测试用例，提取可复用的编写规则。

## 优质用例

```json
{cases_json}
```

## 任务

提取 3-5 条最有价值的通用规则，关注：
- 字段填写规范
- 描述粒度
- 场景覆盖方法
- 预期结果写法

## 输出格式

```json
[
  {{
    "rule_text": "规则内容",
    "type": "writing_style | scenario_coverage | general",
    "reasoning": "为什么提取这条规则"
  }}
]
```

请只输出 JSON，不要添加任何解释。
"""


class RuleExtractor:
    """规则提取器"""

    def __init__(self, llm_client: LLMClient):
        """
        初始化规则提取器
        
        Args:
            llm_client: LLM 客户端
        """
        self.llm = llm_client

    def extract_from_feedback(self, feedback: str) -> List[Dict[str, Any]]:
        """
        从用户反馈提取规则
        
        Args:
            feedback: 用户反馈内容
            
        Returns:
            提取的规则列表
        """
        prompt = EXTRACT_FROM_FEEDBACK_PROMPT.format(feedback=feedback)
        raw = self.llm.chat(prompt, "")
        return self._parse_json(raw)

    def extract_from_good_cases(self, cases: List[Dict]) -> List[Dict[str, Any]]:
        """
        从优质用例反向学习规则
        
        Args:
            cases: 优质用例列表
            
        Returns:
            提取的规则列表
        """
        if len(cases) < 3:
            return []

        cases_json = json.dumps(cases, ensure_ascii=False, indent=2)
        prompt = EXTRACT_FROM_GOOD_CASES_PROMPT.format(cases_json=cases_json)
        raw = self.llm.chat(prompt, "")
        return self._parse_json(raw)

    def _parse_json(self, raw: str) -> List[Dict[str, Any]]:
        """
        解析 LLM 返回的 JSON
        
        Args:
            raw: LLM 原始输出
            
        Returns:
            解析后的 JSON 列表，解析失败返回空列表
        """
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            # 尝试提取 JSON 块
            match = re.search(r"\[[\s\S]*\]", raw)
            if match:
                try:
                    return json.loads(match.group(0))
                except json.JSONDecodeError:
                    pass
        return []
