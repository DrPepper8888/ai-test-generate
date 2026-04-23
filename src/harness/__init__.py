"""
Harness 模块 - AI 测试用例生成器的记忆与学习系统

核心组件：
- models: 规则数据模型
- memory_store: 规则存储管理（兼容旧版）
- rule_file_manager: 规则文件管理器（新，支持渐进式加载）
- rule_extractor: 规则提取器
- rule_injector: 规则注入器
"""

from src.harness.models import Rule, RuleType, RuleLevel
from src.harness.memory_store import MemoryStore
from src.harness.rule_file_manager import RuleFileManager, RuleFile
from src.harness.rule_extractor import RuleExtractor
from src.harness.rule_injector import RuleInjector

__all__ = [
    # 模型
    "Rule",
    "RuleType",
    "RuleLevel",
    # 存储（兼容）
    "MemoryStore",
    # 文件管理（新）
    "RuleFileManager",
    "RuleFile",
    # 提取器
    "RuleExtractor",
    # 注入器
    "RuleInjector",
]
