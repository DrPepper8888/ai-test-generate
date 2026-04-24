"""
记忆存储管理器 - Harness 的核心数据层

完全使用 Python 标准库，无第三方依赖
"""

import json
from pathlib import Path
from typing import List, Optional, Dict, Any
from datetime import datetime

from src.harness.models import Rule, RuleType, RuleLevel


class MemoryStore:
    """
    记忆存储管理器
    
    职责：
    1. 持久化规则、交互历史
    2. 提供规则查询、统计、淘汰能力
    3. 支持规则来源追溯
    """

    def __init__(self, data_dir: Path):
        """
        初始化记忆存储
        
        Args:
            data_dir: 数据目录根路径
        """
        self.data_dir = Path(data_dir)
        self.memory_dir = self.data_dir / "memory"
        self.memory_dir.mkdir(parents=True, exist_ok=True)

        self.rules_path = self.memory_dir / "rules.json"
        self.interactions_dir = self.memory_dir / "interactions"
        self.annotated_path = self.memory_dir / "annotated_cases.json"

        self.interactions_dir.mkdir(exist_ok=True)

    # =====================================================================
    # 规则管理
    # =====================================================================

    def load_rules(self, level: RuleLevel = None) -> List[Rule]:
        """
        加载规则
        
        Args:
            level: 规则层级过滤，None 表示加载所有
            
        Returns:
            规则列表
        """
        if not self.rules_path.exists():
            return []

        try:
            data = json.loads(self.rules_path.read_text(encoding="utf-8"))
            rules = [Rule.from_dict(r) for r in data]

            if level:
                rules = [r for r in rules if r.level == level]

            return rules
        except (json.JSONDecodeError, OSError, TypeError):
            return []

    def save_rules(self, rules: List[Rule]):
        """
        保存规则到文件
        
        Args:
            rules: 规则列表
        """
        data = [r.to_dict() for r in rules]
        self.rules_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )

    def add_rule(
        self,
        rule_text: str,
        rule_type: RuleType,
        source: str,
        source_detail: str = "",
        tags: List[str] = None,
        quality_score: float = 0.0,
        quality_reason: str = "",
        improved_text: str = ""
    ) -> str:
        """
        添加新规则
        
        Args:
            rule_text: 规则内容
            rule_type: 规则类型
            source: 来源
            source_detail: 来源详情
            tags: 标签列表
            quality_score: AI 审核评分 (0-1)
            quality_reason: AI 审核理由
            improved_text: AI 改进后的文本
            
        Returns:
            rule_id: 新规则ID，若已存在则返回原ID
        """
        rules = self.load_rules()

        # 检查是否已存在相同规则（防止重复）
        for existing in rules:
            if existing.rule_text == rule_text:
                return existing.rule_id

        # 生成新ID
        max_id = 0
        for r in rules:
            try:
                if r.rule_id.startswith("RULE_"):
                    num = int(r.rule_id.replace("RULE_", ""))
                    max_id = max(max_id, num)
            except ValueError:
                pass

        rule = Rule(
            rule_id=f"RULE_{max_id + 1:04d}",
            rule_text=rule_text,
            type=rule_type,
            level=RuleLevel.GLOBAL,  # P1 统一 global，预留多租户
            tags=tags or [],
            source=source,
            source_detail=source_detail,
            created_at=self._now(),
            quality_score=quality_score,
            quality_reason=quality_reason,
            improved_text=improved_text
        )

        rules.append(rule)
        self.save_rules(rules)

        return rule.rule_id

    def record_feedback(
        self,
        rule_id: str,
        is_effective: bool,
        feedback: str = "",
        auto_check_deprecation: bool = True
    ):
        """
        记录规则使用反馈
        
        Args:
            rule_id: 规则ID
            is_effective: 这次使用是否有效（正向反馈）
            feedback: 反馈内容（可选）
            auto_check_deprecation: 是否自动检查并淘汰低质量规则
        """
        rules = self.load_rules()

        for rule in rules:
            if rule.rule_id == rule_id:
                rule.use_count += 1
                if is_effective:
                    rule.effective_count += 1
                else:
                    rule.ineffective_count += 1
                    # 记录无效反馈详情（用于分析）
                    if feedback:
                        self._save_ineffective_feedback(rule_id, feedback)
                rule.last_used_at = self._now()
                
                # 自动检查是否应该淘汰
                if auto_check_deprecation and rule.should_auto_deprecate():
                    rule.is_deprecated = True
                    rule.auto_deprecated = True
                    rule.deprecate_reason = f"使用 {rule.use_count} 次后有效率仅 {rule.effective_rate * 100:.0f}%"
                
                break

        self.save_rules(rules)

    def get_effective_rules(self, top_k: int = 5) -> List[Rule]:
        """
        获取最有效的规则（用于注入 prompt）
        
        排序规则：
        1. 优先有效率高的
        2. 其次使用次数多的（新规则有公平机会）
        
        Args:
            top_k: 返回前K条
            
        Returns:
            最有效的规则列表
        """
        rules = [r for r in self.load_rules() if not r.is_deprecated]

        # 计算有效率并排序
        scored = []
        for r in rules:
            rate = r.effective_rate
            # 新规则加权（新规则有效率低于 0.5 也保留）
            if r.use_count < 3:
                rate = max(rate, 0.3)
            scored.append((r, rate))

        scored.sort(key=lambda x: (-x[1], -x[0].use_count))

        return [r for r, _ in scored[:top_k]]

    def get_rules_for_display(self, limit: int = 20) -> List[Dict[str, Any]]:
        """
        获取展示用的规则列表（半透明模式）
        
        Returns:
            包含统计信息的规则列表
        """
        rules = self.get_effective_rules(top_k=limit)

        return [
            {
                "id": r.rule_id,
                "text": r.rule_text,
                "type": r.type.value,
                "source": r.source,
                "stats": {
                    "used": r.use_count,
                    "effective": r.effective_count,
                    "rate": round(r.effective_rate * 100, 1),
                }
            }
            for r in rules
        ]

    def cleanup_rules(self) -> int:
        """
        清理低质量规则
        
        淘汰条件：
        - 使用次数 >= 5 且 有效率 < 30%
        
        Returns:
            被淘汰的规则数量
        """
        rules = self.load_rules()
        deprecated = 0

        for rule in rules:
            if rule.use_count >= 5 and rule.effective_rate < 0.3:
                rule.is_deprecated = True
                deprecated += 1

        if deprecated > 0:
            self.save_rules(rules)

        return deprecated

    # =====================================================================
    # 交互历史
    # =====================================================================

    def save_interaction(
        self,
        requirement: str,
        cases: List[Dict],
        feedback: Dict = None,
    ) -> str:
        """
        保存一次交互
        
        Args:
            requirement: 需求描述
            cases: 生成的用例列表
            feedback: 用户反馈
            
        Returns:
            session_id: 会话ID
        """
        import uuid
        session_id = str(uuid.uuid4())[:8]

        interaction = {
            "session_id": session_id,
            "timestamp": self._now(),
            "requirement": requirement[:200],
            "cases_count": len(cases),
            "feedback": feedback,
        }

        path = self.interactions_dir / f"{session_id}.json"
        path.write_text(
            json.dumps(interaction, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )

        return session_id

    # =====================================================================
    # 工具方法
    # =====================================================================

    @staticmethod
    def _now() -> str:
        """返回当前时间 ISO 格式"""
        return datetime.now().isoformat()

    def _save_ineffective_feedback(self, rule_id: str, feedback: str):
        """
        保存无效反馈用于分析
        
        Args:
            rule_id: 规则ID
            feedback: 反馈内容
        """
        path = self.memory_dir / "ineffective_feedback.json"
        data = []

        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                data = []

        data.append({
            "rule_id": rule_id,
            "feedback": feedback,
            "timestamp": self._now(),
        })

        # 只保留最近 100 条
        data = data[-100:]

        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
