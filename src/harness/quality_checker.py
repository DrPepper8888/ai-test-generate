# -*- coding: utf-8 -*-
"""
AI 规则质量审核器 - 学习前的质量把关

在规则入库前，先让 AI 评估规则质量，过滤明显错误的规则。

完全使用 Python 标准库，无第三方依赖
"""

import json
import re
from typing import Dict, List, Any, Tuple
from src.api.llm_client import LLMClient


# AI 自审 Prompt
QUALITY_CHECK_PROMPT = """你是一位严格的测试规则质量审核员。请评估以下规则是否值得入库。

【候选规则】
{rule_text}

【评估维度】（每项 0-1 分）
1. 可执行性：规则是否可以指导生成动作？（不能是模糊的"要好"）
2. 可复用性：规则是否通用，不是针对具体案例？
3. 清晰度：规则表述是否清晰无歧义？

【输出格式】（必须是有效 JSON）
```json
{{
  "approve": true或false,
  "quality_score": 0.0到1.0,
  "reason": "审核理由（50字以内）",
  "improved_text": "如果表述不清，给出改进版本；否则为空字符串"
}}
```

请只输出 JSON，不要添加任何解释。
"""

# 批量审核 Prompt
BATCH_QUALITY_CHECK_PROMPT = """你是一位严格的测试规则质量审核员。请评估以下规则列表中每条规则是否值得入库。

【候选规则列表】
{rules_json}

【评估维度】
1. 可执行性：规则是否可以指导生成动作？
2. 可复用性：规则是否通用？
3. 清晰度：规则表述是否清晰？

【输出格式】（必须是有效 JSON 数组）
```json
[
  {{
    "rule_text": "规则原文",
    "approve": true或false,
    "quality_score": 0.0到1.0,
    "reason": "审核理由",
    "improved_text": "改进版本或空字符串"
  }}
]
```

请只输出 JSON 数组。
"""


class QualityChecker:
    """AI 规则质量审核器"""

    def __init__(self, llm_client: LLMClient):
        self.llm = llm_client

    def check(self, rule_text: str) -> Dict[str, Any]:
        """
        审核单条规则
        
        Args:
            rule_text: 规则文本
            
        Returns:
            {
                "approve": bool,          # 是否通过
                "quality_score": float,   # 质量评分 0-1
                "reason": str,            # 审核理由
                "improved_text": str     # 改进版本
            }
        """
        # 基础检查：太短或太长的规则直接过滤
        rule_text = rule_text.strip()
        if len(rule_text) < 5:
            return {
                "approve": False,
                "quality_score": 0.0,
                "reason": "规则太短，无法评估",
                "improved_text": ""
            }
        
        if len(rule_text) > 500:
            return {
                "approve": False,
                "quality_score": 0.0,
                "reason": "规则太长，需要精简",
                "improved_text": ""
            }

        # 调用 AI 审核
        prompt = QUALITY_CHECK_PROMPT.format(rule_text=rule_text)
        try:
            raw = self.llm.chat(prompt, "")
            return self._parse_response(raw, rule_text)
        except Exception as e:
            # API 失败时保守处理：通过但低分
            return {
                "approve": True,  # 默认通过，避免阻止学习
                "quality_score": 0.5,
                "reason": f"AI审核失败，默认通过：{str(e)[:50]}",
                "improved_text": ""
            }

    def check_batch(self, rules: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        批量审核规则
        
        Args:
            rules: [{"rule_text": "...", "type": "...", ...}]
            
        Returns:
            {
                "approved": [Dict],  # 通过的规则
                "rejected": [Dict],  # 拒绝的规则
                "total_score": float # 平均分
            }
        """
        if not rules:
            return {"approved": [], "rejected": [], "total_score": 0.0}

        # 先尝试批量审核
        rules_json = json.dumps(rules, ensure_ascii=False, indent=2)
        prompt = BATCH_QUALITY_CHECK_PROMPT.format(rules_json=rules_json)
        
        try:
            raw = self.llm.chat(prompt, "")
            results = self._parse_batch_response(raw)
            
            if results:
                approved = []
                rejected = []
                total_score = 0.0
                
                for i, result in enumerate(results):
                    if i < len(rules):
                        rule = rules[i].copy()
                        rule["quality_score"] = result.get("quality_score", 0.5)
                        rule["quality_reason"] = result.get("reason", "")
                        rule["improved_text"] = result.get("improved_text", "")
                        
                        if result.get("approve", True):
                            approved.append(rule)
                        else:
                            rejected.append(rule)
                        
                        total_score += result.get("quality_score", 0.5)
                
                return {
                    "approved": approved,
                    "rejected": rejected,
                    "total_score": total_score / len(rules) if rules else 0.0
                }
        except Exception:
            pass
        
        # 批量审核失败，逐条审核
        return self._check_one_by_one(rules)

    def _check_one_by_one(self, rules: List[Dict[str, Any]]) -> Dict[str, Any]:
        """逐条审核（批量失败时的降级方案）"""
        approved = []
        rejected = []
        total_score = 0.0
        
        for rule in rules:
            result = self.check(rule.get("rule_text", ""))
            rule_copy = rule.copy()
            rule_copy["quality_score"] = result["quality_score"]
            rule_copy["quality_reason"] = result["reason"]
            rule_copy["improved_text"] = result["improved_text"]
            
            if result["approve"]:
                approved.append(rule_copy)
            else:
                rejected.append(rule_copy)
            
            total_score += result["quality_score"]
        
        return {
            "approved": approved,
            "rejected": rejected,
            "total_score": total_score / len(rules) if rules else 0.0
        }

    def _parse_response(self, raw: str, original_text: str) -> Dict[str, Any]:
        """解析 AI 审核结果"""
        try:
            # 尝试直接解析
            data = json.loads(raw.strip())
            return {
                "approve": bool(data.get("approve", True)),
                "quality_score": float(data.get("quality_score", 0.5)),
                "reason": str(data.get("reason", "")),
                "improved_text": str(data.get("improved_text", ""))
            }
        except (json.JSONDecodeError, ValueError, TypeError):
            pass
        
        # 尝试提取 JSON 块
        match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", raw, re.IGNORECASE)
        if match:
            try:
                data = json.loads(match.group(1).strip())
                return {
                    "approve": bool(data.get("approve", True)),
                    "quality_score": float(data.get("quality_score", 0.5)),
                    "reason": str(data.get("reason", "")),
                    "improved_text": str(data.get("improved_text", ""))
                }
            except (json.JSONDecodeError, ValueError, TypeError):
                pass
        
        # 解析失败，保守处理
        return {
            "approve": True,
            "quality_score": 0.5,
            "reason": "解析失败，默认通过",
            "improved_text": ""
        }

    def _parse_batch_response(self, raw: str) -> List[Dict[str, Any]]:
        """解析批量审核结果"""
        try:
            data = json.loads(raw.strip())
            if isinstance(data, list):
                return data
        except json.JSONDecodeError:
            pass
        
        # 尝试提取 JSON 块
        match = re.search(r"\[[\s\S]*\]", raw)
        if match:
            try:
                data = json.loads(match.group(0))
                if isinstance(data, list):
                    return data
            except json.JSONDecodeError:
                pass
        
        return []
