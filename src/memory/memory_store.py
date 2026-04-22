"""
Memory 存储模块
管理交互历史、规则记忆、标注用例库
"""
import json
from pathlib import Path
from typing import Dict, List, Any, Optional


class MemoryStore:
    """记忆存储管理器"""

    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.memory_dir = self.data_dir / "memory"
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        self.rules_path = self.memory_dir / "rules.json"
        self.annotated_path = self.memory_dir / "annotated_cases.json"
        self.interactions_dir = self.memory_dir / "interactions"

    def load_rules(self) -> List[Dict]:
        """加载规则记忆"""
        if not self.rules_path.exists():
            return []
        try:
            return json.loads(self.rules_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []

    def save_rules(self, rules: List[Dict]):
        """保存规则记忆"""
        self.rules_path.write_text(
            json.dumps(rules, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )

    def add_rule(self, rule: Dict):
        """添加单条规则"""
        rules = self.load_rules()
        rules.append(rule)
        self.save_rules(rules)

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
