# -*- coding: utf-8 -*-
"""
自动学习器 - 从用户反馈和优质用例中自动学习规则

完全使用 Python 标准库，无第三方依赖

功能：
1. 从反馈文本学习规则
2. 从优质用例反向学习规则
3. AI 自审过滤错误规则
4. 自动入库 + 记录统计
"""

import json
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional

from src.api.llm_client import LLMClient
from src.harness.models import Rule, RuleType, RuleLevel
from src.harness.memory_store import MemoryStore
from src.harness.rule_extractor import RuleExtractor
from src.harness.quality_checker import QualityChecker


# 从反馈学习的 Prompt
LEARN_FROM_FEEDBACK_PROMPT = """
你是一位测试规则学习专家。请从用户反馈中提取可复用的测试用例编写规则。

【用户反馈】
{feedback}

【要求】
- 提取 1-5 条可复用的规则
- 每条规则要简洁、可执行
- 关注：字段完整性、边界值、描述清晰度

【输出格式】（必须是有效 JSON 数组）
```json
[
  {{
    "rule_text": "规则内容",
    "type": "field_format|scenario_coverage|boundary_value|writing_style|general"
  }}
]
```

请只输出 JSON 数组。
"""

# 从优质用例学习的 Prompt
LEARN_FROM_CASES_PROMPT = """
你是一位测试规则学习专家。请从以下被标记为"可投产"的优质用例中，反向提取可复用的编写规则。

【优质用例】
{cases_json}

【要求】
- 提取 3-5 条最有价值的通用规则
- 关注：字段填写规范、描述粒度、场景覆盖、预期结果写法
- 规则要可复用，不是针对具体业务

【输出格式】（必须是有效 JSON 数组）
```json
[
  {{
    "rule_text": "规则内容",
    "type": "field_format|scenario_coverage|boundary_value|writing_style|general"
  }}
]
```

请只输出 JSON 数组。
"""


class AutoLearner:
    """自动学习器"""

    def __init__(
        self,
        llm_client: LLMClient,
        memory_store: MemoryStore
    ):
        self.llm = llm_client
        self.memory_store = memory_store
        self.extractor = RuleExtractor(llm_client)
        self.quality_checker = QualityChecker(llm_client)

    def learn_from_feedback(
        self,
        feedback: str,
        source: str = "用户反馈"
    ) -> Dict[str, Any]:
        """
        从反馈学习规则
        
        Args:
            feedback: 用户反馈文本
            source: 规则来源
            
        Returns:
            {
                "success": bool,
                "learned_count": int,
                "discarded_count": int,
                "rules": [Dict],      # 入库的规则
                "discarded": [Dict],  # 被过滤的规则
                "message": str
            }
        """
        if not feedback or not feedback.strip():
            return {
                "success": True,
                "learned_count": 0,
                "discarded_count": 0,
                "rules": [],
                "discarded": [],
                "message": "无反馈内容，跳过学习"
            }

        try:
            # 1. 调用 LLM 提取规则
            prompt = LEARN_FROM_FEEDBACK_PROMPT.format(feedback=feedback)
            raw = self.llm.chat(prompt, "")
            
            # 2. 解析 JSON
            candidate_rules = self._parse_rules(raw)
            
            if not candidate_rules:
                return {
                    "success": True,
                    "learned_count": 0,
                    "discarded_count": 0,
                    "rules": [],
                    "discarded": [],
                    "message": "未提取到有效规则，可能反馈内容不足"
                }
            
            # 3. AI 自审
            quality_result = self.quality_checker.check_batch(candidate_rules)
            
            # 4. 入库
            learned_rules = []
            for rule_data in quality_result["approved"]:
                rule_text = rule_data.get("improved_text") or rule_data["rule_text"]
                rule_type = RuleType.from_string(rule_data.get("type", "general"))
                
                rule_id = self.memory_store.add_rule(
                    rule_text=rule_text,
                    rule_type=rule_type,
                    source=source,
                    quality_score=rule_data.get("quality_score", 0.5),
                    quality_reason=rule_data.get("quality_reason", ""),
                    improved_text=rule_data.get("improved_text", "")
                )
                
                # 获取完整规则信息
                rules = self.memory_store.load_rules()
                rule = next((r for r in rules if r.rule_id == rule_id), None)
                if rule:
                    learned_rules.append(self._rule_to_display(rule))
            
            # 5. 记录被过滤的规则
            discarded_rules = []
            for rule_data in quality_result["rejected"]:
                discarded_rules.append({
                    "rule_text": rule_data["rule_text"],
                    "reason": rule_data.get("quality_reason", "AI审核未通过")
                })
            
            return {
                "success": True,
                "learned_count": len(learned_rules),
                "discarded_count": len(discarded_rules),
                "rules": learned_rules,
                "discarded": discarded_rules,
                "message": f"学习完成！入库 {len(learned_rules)} 条，过滤 {len(discarded_rules)} 条"
            }
            
        except Exception as e:
            return {
                "success": False,
                "learned_count": 0,
                "discarded_count": 0,
                "rules": [],
                "discarded": [],
                "message": f"学习失败：{str(e)}"
            }

    def learn_from_cases(
        self,
        cases: List[Dict],
        source: str = "优质用例反向学习"
    ) -> Dict[str, Any]:
        """
        从优质用例反向学习规则
        
        Args:
            cases: 优质用例列表
            source: 规则来源
            
        Returns:
            同 learn_from_feedback
        """
        if len(cases) < 3:
            return {
                "success": True,
                "learned_count": 0,
                "discarded_count": 0,
                "rules": [],
                "discarded": [],
                "message": f"用例数量不足（{len(cases)} < 3），跳过学习"
            }

        try:
            # 1. 序列化用例
            cases_json = json.dumps(cases, ensure_ascii=False, indent=2)
            
            # 2. 调用 LLM 提取规则
            prompt = LEARN_FROM_CASES_PROMPT.format(cases_json=cases_json)
            raw = self.llm.chat(prompt, "")
            
            # 3. 解析 JSON
            candidate_rules = self._parse_rules(raw)
            
            if not candidate_rules:
                return {
                    "success": True,
                    "learned_count": 0,
                    "discarded_count": 0,
                    "rules": [],
                    "discarded": [],
                    "message": "未提取到有效规则"
                }
            
            # 4. AI 自审
            quality_result = self.quality_checker.check_batch(candidate_rules)
            
            # 5. 入库
            learned_rules = []
            for rule_data in quality_result["approved"]:
                rule_text = rule_data.get("improved_text") or rule_data["rule_text"]
                rule_type = RuleType.from_string(rule_data.get("type", "general"))
                
                rule_id = self.memory_store.add_rule(
                    rule_text=rule_text,
                    rule_type=rule_type,
                    source=source,
                    quality_score=rule_data.get("quality_score", 0.5),
                    quality_reason=rule_data.get("quality_reason", ""),
                    improved_text=rule_data.get("improved_text", "")
                )
                
                rules = self.memory_store.load_rules()
                rule = next((r for r in rules if r.rule_id == rule_id), None)
                if rule:
                    learned_rules.append(self._rule_to_display(rule))
            
            # 6. 记录被过滤的规则
            discarded_rules = []
            for rule_data in quality_result["rejected"]:
                discarded_rules.append({
                    "rule_text": rule_data["rule_text"],
                    "reason": rule_data.get("quality_reason", "AI审核未通过")
                })
            
            return {
                "success": True,
                "learned_count": len(learned_rules),
                "discarded_count": len(discarded_rules),
                "rules": learned_rules,
                "discarded": discarded_rules,
                "message": f"从 {len(cases)} 条优质用例中学习完成！入库 {len(learned_rules)} 条"
            }
            
        except Exception as e:
            return {
                "success": False,
                "learned_count": 0,
                "discarded_count": 0,
                "rules": [],
                "discarded": [],
                "message": f"学习失败：{str(e)}"
            }

    def learn_from_session(
        self,
        cases: List[Dict],
        labels: Dict[str, str]
    ) -> Dict[str, Any]:
        """
        从整个会话学习（所有标注的用例 + 反馈）
        
        Args:
            cases: 所有用例
            labels: {case_id: label} 标注结果
            
        Returns:
            合并的学习结果
        """
        results = {
            "success": True,
            "learned_count": 0,
            "discarded_count": 0,
            "rules": [],
            "discarded": [],
            "messages": []
        }
        
        # 1. 收集反馈文本
        feedbacks = []
        for case in cases:
            case_id = case.get("id", "")
            label = labels.get(case_id, "")
            
            if label == "accepted":
                feedbacks.append(f"用例 {case_id} 标记为✅可投产（高质量）")
            elif label == "rejected":
                feedbacks.append(f"用例 {case_id} 标记为❌舍弃（低质量）")
            elif label == "needs_fix":
                feedbacks.append(f"用例 {case_id} 标记为⚠️待修改")
        
        if feedbacks:
            feedback_result = self.learn_from_feedback(
                "\n".join(feedbacks),
                source="会话标注学习"
            )
            results["learned_count"] += feedback_result["learned_count"]
            results["discarded_count"] += feedback_result["discarded_count"]
            results["rules"].extend(feedback_result["rules"])
            results["discarded"].extend(feedback_result["discarded"])
            results["messages"].append(feedback_result["message"])
        
        # 2. 从优质用例学习
        good_cases = [
            case for case in cases
            if labels.get(case.get("id", "")) == "accepted"
        ]
        
        if len(good_cases) >= 3:
            cases_result = self.learn_from_cases(
                good_cases,
                source="优质用例反向学习"
            )
            results["learned_count"] += cases_result["learned_count"]
            results["discarded_count"] += cases_result["discarded_count"]
            results["rules"].extend(cases_result["rules"])
            results["discarded"].extend(cases_result["discarded"])
            results["messages"].append(cases_result["message"])
        
        # 合并消息
        if results["messages"]:
            results["message"] = " | ".join(results["messages"])
        else:
            results["message"] = "无有效标注，跳过学习"
        
        return results

    def _parse_rules(self, raw: str) -> List[Dict[str, Any]]:
        """解析 LLM 返回的规则列表"""
        try:
            data = json.loads(raw.strip())
            if isinstance(data, list):
                return [r for r in data if isinstance(r, dict) and r.get("rule_text")]
        except json.JSONDecodeError:
            pass
        
        # 尝试提取 JSON 块
        import re
        match = re.search(r"\[[\s\S]*\]", raw)
        if match:
            try:
                data = json.loads(match.group(0))
                if isinstance(data, list):
                    return [r for r in data if isinstance(r, dict) and r.get("rule_text")]
            except json.JSONDecodeError:
                pass
        
        return []

    def _rule_to_display(self, rule: Rule) -> Dict[str, Any]:
        """将 Rule 转换为前端展示格式"""
        return {
            "rule_id": rule.rule_id,
            "rule_text": rule.rule_text,
            "type": rule.type.value,
            "source": rule.source,
            "quality_score": rule.quality_score,
            "quality_reason": rule.quality_reason,
            "use_count": rule.use_count,
            "effective_rate": f"{rule.effective_rate * 100:.0f}%",
            "is_deprecated": rule.is_deprecated
        }


# 向后兼容：保持原来的接口
def learn_from_feedback(
    llm_client: LLMClient,
    memory_store: MemoryStore,
    feedback: str,
    source: str = "用户反馈"
) -> Dict[str, Any]:
    """兼容旧接口"""
    learner = AutoLearner(llm_client, memory_store)
    return learner.learn_from_feedback(feedback, source)
