"""
规则管理器
提供规则的智能管理、一键优化等功能
"""
from pathlib import Path
from typing import Dict, List
from datetime import datetime

from src.api.llm_client import LLMClient
from src.memory.memory_store import MemoryStore
from src.memory.rule_extractor import RuleExtractor


class RuleManager:
    """规则智能管理器"""

    def __init__(self, config: dict, project_root: Path):
        self.config = config
        self.project_root = project_root
        self.llm = LLMClient.from_config(config)
        self.memory_store = MemoryStore(project_root / "data")
        self.extractor = RuleExtractor(self.llm)

    def optimize_all_rules(self) -> Dict:
        """一键优化：分析所有历史，更新规则库
        Returns:
            优化结果统计
        """
        result = {
            "total_rules": 0,
            "new_rules": 0,
            "deprecated_rules": 0,
            "good_cases_analyzed": 0,
        }

        # 1. 清理低效率规则
        deprecated = self.memory_store.cleanup_deprecated_rules()
        result["deprecated_rules"] = deprecated

        # 2. 从优质用例反向学习
        good_cases = self._get_all_good_cases()
        result["good_cases_analyzed"] = len(good_cases)

        if len(good_cases) >= 3:
            new_rules = self.extractor.extract_from_good_cases(good_cases)
            for rule in new_rules:
                rule_id = self.memory_store.add_rule(
                    rule_text=rule["rule_text"],
                    rule_type=rule.get("type", "general"),
                    level="global",
                    source=rule.get("source", "优质用例反向学习"),
                )
                if rule_id.startswith("RULE_") and int(rule_id.split("_")[1]) > len(self.memory_store.load_rules()) - len(new_rules):
                    result["new_rules"] += 1

        # 3. 统计总数
        result["total_rules"] = len(self.memory_store.load_rules())

        return result

    def _get_all_good_cases(self) -> List[Dict]:
        """获取所有被标记为"可投产"的优质用例"""
        annotated = self.memory_store.load_annotated_cases()
        good_cases = []
        for item in annotated:
            if item.get("label") == "good" or item.get("label") == "✅可投产":
                good_cases.append(item.get("case", {}))
        return good_cases

    def get_rule_stats(self) -> Dict:
        """获取规则库统计信息"""
        rules = self.memory_store.load_rules()

        level_counts = {
            "global": 0,
            "project": 0,
            "user": 0,
        }

        deprecated = 0
        total_use_count = 0
        total_effective = 0

        for r in rules:
            level = r.get("level", "global")
            if level in level_counts:
                level_counts[level] += 1

            if r.get("is_deprecated", False):
                deprecated += 1

            total_use_count += r.get("use_count", 0)
            total_effective += r.get("effective_count", 0)

        overall_rate = total_effective / total_use_count if total_use_count > 0 else 0

        top_rules = self.memory_store.get_effective_rules(top_k=5)

        return {
            "total": len(rules),
            "active": len(rules) - deprecated,
            "deprecated": deprecated,
            "by_level": level_counts,
            "total_use_count": total_use_count,
            "total_effective": total_effective,
            "overall_effective_rate": round(overall_rate, 2),
            "top_rules": top_rules,
        }

    def report_effective(self, rule_ids: List[str], is_effective: bool = True):
        """批量报告规则有效性"""
        for rule_id in rule_ids:
            self.memory_store.record_rule_usage(rule_id, is_effective)