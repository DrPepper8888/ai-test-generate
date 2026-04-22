"""
Memory 存储模块
管理交互历史、规则记忆、标注用例库

规则分层架构：
- global: 全局通用规则（所有项目都适用）
- project: 项目级规则（特定业务域）
- user: 用户个人偏好规则

每条规则带统计：使用次数、有效次数、最后使用时间
"""
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional


# 规则层级
RULE_LEVEL_GLOBAL = "global"
RULE_LEVEL_PROJECT = "project"
RULE_LEVEL_USER = "user"

# 规则有效率阈值（低于此的自动降级或淘汰）
EFFECTIVE_RATE_THRESHOLD = 0.3


class MemoryStore:
    """记忆存储管理器"""

    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.memory_dir = self.data_dir / "memory"
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        self.rules_path = self.memory_dir / "rules.json"
        self.annotated_path = self.memory_dir / "annotated_cases.json"
        self.interactions_dir = self.memory_dir / "interactions"

    def load_rules(self, level: str = None) -> List[Dict]:
        """加载规则记忆
        Args:
            level: 规则层级，None 表示加载所有
        """
        if not self.rules_path.exists():
            return []
        try:
            rules = json.loads(self.rules_path.read_text(encoding="utf-8"))
            if level:
                return [r for r in rules if r.get("level") == level]
            return rules
        except (json.JSONDecodeError, OSError):
            return []

    def save_rules(self, rules: List[Dict]):
        """保存规则记忆"""
        self.rules_path.write_text(
            json.dumps(rules, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )

    def add_rule(
        self,
        rule_text: str,
        rule_type: str = "general",
        level: str = RULE_LEVEL_GLOBAL,
        source: str = "",
    ) -> str:
        """添加单条规则
        Returns:
            rule_id: 新生成的规则ID
        """
        rules = self.load_rules()

        # 生成唯一规则ID
        rule_id = f"RULE_{len(rules) + 1:04d}"

        # 检查是否已存在相同规则
        existing_ids = {r["rule_text"] for r in rules}
        if rule_text in existing_ids:
            # 已存在，不重复添加，返回原ID
            for r in rules:
                if r["rule_text"] == rule_text:
                    return r["rule_id"]

        rule = {
            "rule_id": rule_id,
            "rule_text": rule_text,
            "type": rule_type,
            "level": level,
            "source": source,
            "created_at": self._now(),
            "use_count": 0,           # 使用次数
            "effective_count": 0,     # 有效次数（用户反馈好）
            "last_used_at": None,
            "is_deprecated": False,   # 是否被淘汰
        }
        rules.append(rule)
        self.save_rules(rules)
        return rule_id

    def record_rule_usage(self, rule_id: str, is_effective: bool = False):
        """记录规则使用情况
        Args:
            rule_id: 规则ID
            is_effective: 这次使用是否有效（用户反馈好）
        """
        rules = self.load_rules()
        for rule in rules:
            if rule.get("rule_id") == rule_id:
                rule["use_count"] = rule.get("use_count", 0) + 1
                if is_effective:
                    rule["effective_count"] = rule.get("effective_count", 0) + 1
                rule["last_used_at"] = self._now()
                break
        self.save_rules(rules)

    def get_effective_rules(self, top_k: int = 10) -> List[Dict]:
        """获取最有效的规则（按有效率排序）
        Args:
            top_k: 返回前K条
        """
        rules = self.load_rules()
        valid_rules = [r for r in rules if not r.get("is_deprecated", False)]

        # 计算有效率并排序
        for r in valid_rules:
            use_count = r.get("use_count", 0)
            if use_count > 0:
                r["_effective_rate"] = r.get("effective_count", 0) / use_count
            else:
                r["_effective_rate"] = 0.5  # 新规则默认中等有效率

        # 按有效率降序，使用次数降序
        valid_rules.sort(
            key=lambda x: (-x["_effective_rate"], -x.get("use_count", 0))
        )

        return valid_rules[:top_k]

    def cleanup_deprecated_rules(self) -> int:
        """清理低效率规则
        Returns:
            被淘汰的规则数量
        """
        rules = self.load_rules()
        deprecated_count = 0

        for rule in rules:
            use_count = rule.get("use_count", 0)
            if use_count >= 5:  # 使用次数足够多才评估
                effective_rate = rule.get("effective_count", 0) / use_count
                if effective_rate < EFFECTIVE_RATE_THRESHOLD:
                    rule["is_deprecated"] = True
                    deprecated_count += 1

        self.save_rules(rules)
        return deprecated_count

    def get_rules_by_project(self, project_tag: str) -> List[Dict]:
        """获取特定项目的规则"""
        rules = self.load_rules(level=RULE_LEVEL_PROJECT)
        return [r for r in rules if project_tag in r.get("tags", [])]

    def get_rules_by_user(self, user_id: str) -> List[Dict]:
        """获取特定用户的偏好规则"""
        rules = self.load_rules(level=RULE_LEVEL_USER)
        return [r for r in rules if r.get("user_id") == user_id]

    def load_annotated_cases(self) -> List[Dict]:
        """加载标注用例库"""
        if not self.annotated_path.exists():
            return []
        try:
            return json.loads(self.annotated_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []

    def save_annotated_cases(self, cases: List[Dict]):
        """保存标注用例库"""
        self.annotated_path.write_text(
            json.dumps(cases, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )

    def add_annotated_case(self, case: Dict, feedback: str, label: str):
        """添加标注用例"""
        cases = self.load_annotated_cases()
        cases.append({
            "case": case,
            "feedback": feedback,
            "label": label,
            "timestamp": self._now()
        })
        self.save_annotated_cases(cases)

    def load_interaction(self, session_id: str) -> Optional[Dict]:
        """加载交互历史"""
        path = self.interactions_dir / f"{session_id}.json"
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None

    def save_interaction(self, session_id: str, interaction: Dict):
        """保存交互历史"""
        path = self.interactions_dir / f"{session_id}.json"
        path.write_text(
            json.dumps(interaction, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )

    @staticmethod
    def _now() -> str:
        from datetime import datetime
        return datetime.now().isoformat()
