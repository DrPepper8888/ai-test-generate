"""
规则文件管理器 - 基于文件系统的规则存储与渐进式加载

借鉴 ChromaFS 的设计：
1. 规则文件化存储（Markdown 格式，可读可维护）
2. 渐进式加载（按需加载相关规则）
3. 语义 + 关键词双通道检索
"""

import json
import re
import glob
from pathlib import Path
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field


# =============================================================================
# 数据结构
# =============================================================================

@dataclass
class RuleFile:
    """规则文件"""
    file_path: Path
    rule_id: str
    type: str           # 规则类型
    title: str          # 规则标题
    content: str        # 规则内容
    applicable: str     # 适用场景
    examples: Dict[str, str] = field(default_factory=dict)  # {"correct": "...", "wrong": "..."}
    source: str = ""    # 来源
    use_count: int = 0
    effective_count: int = 0
    created_at: str = ""
    updated_at: str = ""

    def to_prompt_text(self) -> str:
        """转换为 prompt 文本"""
        lines = [f"【规则】{self.title}"]
        lines.append(f"类型：{self.type}")
        if self.applicable:
            lines.append(f"适用场景：{self.applicable}")
        lines.append(f"\n{self.content}")
        if self.examples:
            lines.append("\n示例：")
            if "correct" in self.examples:
                lines.append(f"✅ {self.examples['correct']}")
            if "wrong" in self.examples:
                lines.append(f"❌ {self.examples['wrong']}")
        return "\n".join(lines)

    @classmethod
    def from_file(cls, file_path: Path) -> "RuleFile":
        """从文件解析"""
        content = file_path.read_text(encoding="utf-8")
        rule_id = file_path.stem
        rule_type = file_path.parent.name
        
        # 解析 frontmatter
        title = ""
        applicable = ""
        examples = {}
        source = ""
        body = content
        
        if content.startswith("---"):
            parts = content.split("---", 2)
            if len(parts) >= 3:
                meta = parts[1]
                body = parts[2]
                
                for line in meta.split("\n"):
                    if ":" in line:
                        key, value = line.split(":", 1)
                        key = key.strip().lower()
                        value = value.strip()
                        if key == "title":
                            title = value
                        elif key == "applicable":
                            applicable = value
                        elif key == "source":
                            source = value
                        elif key == "examples":
                            # 解析示例
                            pass
        
        return cls(
            file_path=file_path,
            rule_id=rule_id,
            type=rule_type,
            title=title or rule_id,
            content=body.strip(),
            applicable=applicable,
            source=source,
        )


class RuleFileManager:
    """
    规则文件管理器
    
    核心功能：
    1. 规则文件化存储（Markdown 格式）
    2. 渐进式加载（按需加载相关规则）
    3. 关键词 + 语义双通道检索
    """

    def __init__(self, rules_dir: Path):
        self.rules_dir = Path(rules_dir)
        self.rules_dir.mkdir(parents=True, exist_ok=True)
        
        # 规则类型目录
        self.type_dirs = {
            "field_format": "字段格式规范",
            "scenario_coverage": "场景覆盖",
            "business_logic": "业务逻辑",
            "boundary_value": "边界值",
            "general": "通用规则",
        }

    # =====================================================================
    # 规则 CRUD
    # =====================================================================

    def add_rule(
        self,
        rule_text: str,
        rule_type: str,
        title: str = "",
        applicable: str = "",
        examples: Dict[str, str] = None,
        source: str = "",
    ) -> str:
        """
        添加规则到文件
        
        Returns:
            rule_id: 规则文件 ID
        """
        examples = examples or {}
        if examples is None:
            examples = {}
        
        # 生成 rule_id
        existing = self.list_rules()
        max_num = 0
        for rule in existing:
            try:
                num = int(rule.rule_id.split("_")[-1])
                max_num = max(max_num, num)
            except:
                pass
        rule_num = max_num + 1
        rule_id = f"{rule_type}_{rule_num:03d}"
        
        # 文件路径
        file_path = self.rules_dir / rule_type / f"{rule_id}.md"
        file_path.parent.mkdir(parents=True, exist_ok=True)
        
        # 构建文件内容
        content = self._build_rule_content(
            title=title or rule_id,
            rule_text=rule_text,
            rule_type=rule_type,
            applicable=applicable,
            examples=examples,
            source=source,
            use_count=0,
            effective_count=0,
        )
        
        file_path.write_text(content, encoding="utf-8")
        return rule_id

    def _build_rule_content(
        self,
        title: str,
        rule_text: str,
        rule_type: str,
        applicable: str,
        examples: Dict[str, str],
        source: str,
        use_count: int,
        effective_count: int,
    ) -> str:
        """构建规则文件内容"""
        from datetime import datetime
        now = datetime.now().isoformat()
        
        lines = [
            "---",
            f"title: {title}",
            f"type: {rule_type}",
            f"applicable: {applicable}",
            f"source: {source}",
            f"use_count: {use_count}",
            f"effective_count: {effective_count}",
            f"created_at: {now}",
            "---",
            "",
            rule_text,
        ]
        
        if examples:
            lines.append("")
            lines.append("## 示例")
            if "correct" in examples:
                lines.append(f"✅ {examples['correct']}")
            if "wrong" in examples:
                lines.append(f"❌ {examples['wrong']}")
        
        return "\n".join(lines)

    def get_rule(self, rule_id: str) -> Optional[RuleFile]:
        """获取单个规则"""
        for type_dir in self.type_dirs.keys():
            file_path = self.rules_dir / type_dir / f"{rule_id}.md"
            if file_path.exists():
                return RuleFile.from_file(file_path)
        return None

    def list_rules(self, rule_type: str = None) -> List[RuleFile]:
        """列出规则"""
        rules = []
        types = [rule_type] if rule_type else self.type_dirs.keys()
        
        for rtype in types:
            pattern = str(self.rules_dir / rtype / "*.md")
            for file_path in glob.glob(pattern):
                if Path(file_path).name == ".gitkeep":
                    continue
                rules.append(RuleFile.from_file(Path(file_path)))
        
        return rules

    def delete_rule(self, rule_id: str) -> bool:
        """删除规则"""
        for type_dir in self.type_dirs.keys():
            file_path = self.rules_dir / type_dir / f"{rule_id}.md"
            if file_path.exists():
                file_path.unlink()
                return True
        return False

    # =====================================================================
    # 渐进式加载
    # =====================================================================

    def get_relevant_rules(
        self,
        keyword: str = "",
        rule_type: str = None,
        limit: int = 5,
    ) -> List[RuleFile]:
        """
        获取相关规则（渐进式加载）
        
        策略：
        1. 如果有关键词，用关键词匹配
        2. 如果有类型限制，按类型过滤
        3. 按使用次数排序
        """
        all_rules = self.list_rules(rule_type)
        
        if not keyword:
            # 无关键词，返回使用次数最高的
            sorted_rules = sorted(
                all_rules,
                key=lambda r: (r.use_count, r.effective_count),
                reverse=True
            )
            return sorted_rules[:limit]
        
        # 关键词匹配
        keyword_lower = keyword.lower()
        matched = []
        
        for rule in all_rules:
            score = 0
            text = f"{rule.title} {rule.content} {rule.applicable}".lower()
            
            if keyword_lower in text:
                score = text.count(keyword_lower)
            
            if score > 0:
                matched.append((rule, score))
        
        # 按匹配度排序
        matched.sort(key=lambda x: x[1], reverse=True)
        return [r for r, _ in matched[:limit]]

    def load_rules_for_context(
        self,
        requirement: str = "",
        limit: int = 5,
    ) -> str:
        """
        加载相关规则，生成注入 prompt 的文本
        
        Args:
            requirement: 需求描述（用于关键词匹配）
            limit: 最大加载规则数
        
        Returns:
            规则文本，可直接注入 prompt
        """
        # 提取关键词
        keywords = self._extract_keywords(requirement)
        
        # 渐进式加载
        rules = self.get_relevant_rules(
            keyword=" ".join(keywords) if keywords else "",
            limit=limit,
        )
        
        if not rules:
            return ""
        
        lines = ["\n【已学习规则】\n"]
        for i, rule in enumerate(rules, 1):
            lines.append(f"{i}. {rule.to_prompt_text()}")
        
        return "\n".join(lines)

    def _extract_keywords(self, text: str) -> List[str]:
        """从文本提取关键词"""
        if not text:
            return []
        
        # 简单分词
        words = re.findall(r'[\w]+', text.lower())
        
        # 过滤停用词
        stop_words = {"的", "是", "在", "和", "了", "一个", "需要", "包含", "支持"}
        keywords = [w for w in words if len(w) >= 2 and w not in stop_words]
        
        # 取前 5 个关键词
        return list(set(keywords))[:5]

    # =====================================================================
    # 统计
    # =====================================================================

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        all_rules = self.list_rules()
        
        by_type = {}
        for rule in all_rules:
            if rule.type not in by_type:
                by_type[rule.type] = {"count": 0, "total_use": 0}
            by_type[rule.type]["count"] += 1
            by_type[rule.type]["total_use"] += rule.use_count
        
        return {
            "total": len(all_rules),
            "by_type": by_type,
        }

    def increment_use_count(self, rule_id: str, effective: bool = True):
        """增加使用计数"""
        rule = self.get_rule(rule_id)
        if not rule:
            return
        
        rule.use_count += 1
        if effective:
            rule.effective_count += 1
        
        # 写回文件
        content = self._build_rule_content(
            title=rule.title,
            rule_text=rule.content,
            rule_type=rule.type,
            applicable=rule.applicable,
            examples=rule.examples,
            source=rule.source,
            use_count=rule.use_count,
            effective_count=rule.effective_count,
        )
        rule.file_path.write_text(content, encoding="utf-8")
