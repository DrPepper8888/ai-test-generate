# -*- coding: utf-8 -*-
"""
Harness 数据模型 - 规则定义与类型

完全使用 Python 标准库，无第三方依赖
"""

from dataclasses import dataclass, field, asdict
from typing import List, Optional, Dict, Any
from enum import Enum
import json


class RuleType(Enum):
    """规则类型"""
    FIELD_FORMAT = "field_format"           # 字段格式规范
    SCENARIO_COVERAGE = "scenario_coverage" # 场景覆盖
    BUSINESS_LOGIC = "business_logic"        # 业务逻辑
    BOUNDARY_VALUE = "boundary_value"        # 边界值
    RISK_ASSESSMENT = "risk_assessment"     # 风险评估
    WRITING_STYLE = "writing_style"         # 书写风格
    GENERAL = "general"                     # 通用规则
    
    @classmethod
    def from_string(cls, s: str) -> "RuleType":
        """从字符串创建枚举"""
        try:
            return cls(s)
        except ValueError:
            return cls.GENERAL


class RuleLevel(Enum):
    """规则层级（预留多租户）"""
    GLOBAL = "global"      # 全局通用
    PROJECT = "project"   # 项目级
    USER = "user"         # 用户级


@dataclass
class Rule:
    """单条规则"""
    rule_id: str
    rule_text: str
    type: RuleType
    level: RuleLevel = RuleLevel.GLOBAL
    tags: List[str] = field(default_factory=list)
    source: str = ""
    source_detail: str = ""

    use_count: int = 0
    effective_count: int = 0
    ineffective_count: int = 0

    # AI 自审字段
    quality_score: float = 0.0   # AI 审核评分 (0-1)
    quality_reason: str = ""      # AI 审核理由
    improved_text: str = ""      # AI 改进后的文本（如果有）

    created_at: str = ""
    last_used_at: Optional[str] = None
    is_deprecated: bool = False      # 是否被淘汰
    deprecate_reason: str = ""        # 淘汰原因
    auto_deprecated: bool = False    # 是否被自动淘汰

    @property
    def effective_rate(self) -> float:
        """有效率"""
        if self.use_count == 0:
            return 0.5
        return self.effective_count / self.use_count

    def is_worthy(self, min_use: int = 3) -> bool:
        if self.use_count < min_use:
            return True
        return self.effective_rate >= 0.3

    def should_auto_deprecate(self, min_uses: int = 5, threshold: float = 0.3) -> bool:
        """判断是否应该自动淘汰"""
        return (
            self.use_count >= min_uses and
            self.effective_rate < threshold and
            not self.is_deprecated
        )

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典（用于 JSON 序列化）"""
        return {
            "rule_id": self.rule_id,
            "rule_text": self.rule_text,
            "type": self.type.value,  # Enum 转字符串
            "level": self.level.value,
            "tags": self.tags,
            "source": self.source,
            "source_detail": self.source_detail,
            "use_count": self.use_count,
            "effective_count": self.effective_count,
            "ineffective_count": self.ineffective_count,
            # AI 自审
            "quality_score": self.quality_score,
            "quality_reason": self.quality_reason,
            "improved_text": self.improved_text,
            # 状态
            "created_at": self.created_at,
            "last_used_at": self.last_used_at,
            "is_deprecated": self.is_deprecated,
            "deprecate_reason": self.deprecate_reason,
            "auto_deprecated": self.auto_deprecated,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Rule":
        """从字典创建（用于 JSON 反序列化）"""
        return cls(
            rule_id=data["rule_id"],
            rule_text=data["rule_text"],
            type=RuleType.from_string(data.get("type", "general")),
            level=RuleLevel(data.get("level", "global")),
            tags=data.get("tags", []),
            source=data.get("source", ""),
            source_detail=data.get("source_detail", ""),
            use_count=data.get("use_count", 0),
            effective_count=data.get("effective_count", 0),
            ineffective_count=data.get("ineffective_count", 0),
            # AI 自审
            quality_score=data.get("quality_score", 0.0),
            quality_reason=data.get("quality_reason", ""),
            improved_text=data.get("improved_text", ""),
            # 状态
            created_at=data.get("created_at", ""),
            last_used_at=data.get("last_used_at"),
            is_deprecated=data.get("is_deprecated", False),
            deprecate_reason=data.get("deprecate_reason", ""),
            auto_deprecated=data.get("auto_deprecated", False),
        )


class RuleEncoder(json.JSONEncoder):
    """JSON 编码器，支持 Rule 和 Enum"""
    def default(self, obj):
        if isinstance(obj, Rule):
            return obj.to_dict()
        if isinstance(obj, (RuleType, RuleLevel)):
            return obj.value
        return super().default(obj)
